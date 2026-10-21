"""WebSocket JSON-RPC 服务器：方法路由 + 事件广播。"""
import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from websockets.asyncio.server import ServerConnection, serve

Handler = Callable[[dict[str, Any]], Awaitable[Any]]


class RpcServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.host = host
        self.port = port
        self._methods: dict[str, Handler] = {}
        self._clients: set[ServerConnection] = set()

    @property
    def url(self) -> str:
        return f"ws://{self.host}:{self.port}"

    def method(self, name: str) -> Callable[[Handler], Handler]:
        def register(fn: Handler) -> Handler:
            self._methods[name] = fn
            return fn

        return register

    async def broadcast(self, method: str, params: dict[str, Any]) -> None:
        if not self._clients:
            return
        payload = json.dumps({"jsonrpc": "2.0", "method": method, "params": params}, ensure_ascii=False)
        await asyncio.gather(*(ws.send(payload) for ws in list(self._clients)), return_exceptions=True)

    async def _handle(self, ws: ServerConnection) -> None:
        self._clients.add(ws)
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if not isinstance(msg, dict):
                    continue
                reply = await self._dispatch(msg)
                await ws.send(json.dumps(reply, ensure_ascii=False))
        finally:
            self._clients.discard(ws)

    async def _dispatch(self, msg: dict[str, Any]) -> dict[str, Any]:
        name, mid = msg.get("method"), msg.get("id")
        if name not in self._methods:
            return {"jsonrpc": "2.0", "id": mid, "error": f"unknown method: {name}"}
        try:
            result = await self._methods[name](msg.get("params") or {})
            return {"jsonrpc": "2.0", "id": mid, "result": result}
        except Exception as exc:  # 错误必须回传调用方，不能让服务器崩溃
            return {"jsonrpc": "2.0", "id": mid, "error": str(exc)}

    @asynccontextmanager
    async def start(self) -> AsyncIterator["RpcServer"]:
        """启动监听；port=0 时由 OS 分配并回填 self.port，server.url 随之可用。"""
        async with serve(self._handle, self.host, self.port) as s:
            if self.port == 0:
                self.port = s.sockets[0].getsockname()[1]
            yield self
