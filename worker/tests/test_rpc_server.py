import asyncio
import json

import websockets

from worker.rpc.protocol import Request, Response
from worker.rpc.server import RpcServer


async def test_roundtrip_and_unknown_method():
    server = RpcServer(host="127.0.0.1", port=0)

    @server.method("echo")
    async def echo(params):
        return params

    async with server.start():
        async with websockets.connect(server.url) as ws:
            await ws.send(json.dumps(Request(method="echo", params={"v": 1}).to_json()))
            ok = Response.from_json(json.loads(await ws.recv()))
            assert ok.result == {"v": 1} and ok.error is None

            await ws.send(json.dumps(Request(method="nope").to_json()))
            err = Response.from_json(json.loads(await ws.recv()))
            assert "unknown method" in err.error


async def test_broadcast_reaches_clients():
    server = RpcServer(host="127.0.0.1", port=0)

    @server.method("trigger")
    async def trigger(params):
        await server.broadcast("stage_changed", {"stage": "review"})

    async with server.start():
        async with websockets.connect(server.url) as ws:
            async with websockets.connect(server.url) as ws2:
                await ws.send(json.dumps(Request(method="trigger").to_json()))
                got1, got2 = json.loads(await ws.recv()), json.loads(await ws2.recv())
                notifications = [m for m in (got1, got2) if m.get("method") == "stage_changed"]
                assert len(notifications) == 2  # 两客户端在触发前都已连接，广播必须都到达


async def test_broadcast_isolates_dead_client_failures():
    server = RpcServer(host="127.0.0.1", port=0)

    @server.method("trigger")
    async def trigger(params):
        await server.broadcast("stage_changed", {"stage": "review"})
        return "done"

    async with server.start():
        async with websockets.connect(server.url) as ws:

            class DeadClient:  # 模拟已断开但尚未被 discard 的客户端
                async def send(self, payload):
                    raise RuntimeError("connection closed")

            server._clients.add(DeadClient())
            await ws.send(json.dumps(Request(method="trigger").to_json()))
            # 先收到广播 notification，再收到方法响应；只认带 id 的响应
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
                if "method" not in msg:
                    break
            ok = Response.from_json(msg)
            assert ok.result == "done" and ok.error is None  # 单个死客户端不能把广播变成假错误


async def test_handler_exception_returns_error_and_connection_survives():
    server = RpcServer(host="127.0.0.1", port=0)

    @server.method("boom")
    async def boom(params):
        raise ValueError("boom")

    @server.method("echo")
    async def echo(params):
        return params

    async with server.start():
        async with websockets.connect(server.url) as ws:
            await ws.send(json.dumps(Request(method="boom").to_json()))
            err = Response.from_json(json.loads(await ws.recv()))
            assert err.error == "boom"
            await ws.send(json.dumps(Request(method="echo", params={"alive": True}).to_json()))
            ok = Response.from_json(json.loads(await ws.recv()))
            assert ok.result == {"alive": True}


async def test_malformed_messages_do_not_kill_connection():
    server = RpcServer(host="127.0.0.1", port=0)

    @server.method("echo")
    async def echo(params):
        return params

    async with server.start():
        async with websockets.connect(server.url) as ws:
            await ws.send("not-json")
            await ws.send(json.dumps([1, 2, 3]))  # 非 dict
            await ws.send(json.dumps(Request(method="echo", params={"alive": True}).to_json()))
            ok = Response.from_json(json.loads(await ws.recv()))
            assert ok.result == {"alive": True}  # 连接仍活、正常请求得到响应
