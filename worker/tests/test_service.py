import asyncio
import json
import time

import websockets

from worker.adapters.base import AdapterRegistry
from worker.adapters.demo import DemoAdapter
from worker.llm.client import StubEmbedder, StubLLM
from worker.memory.store import connect
from worker.pipeline import Pipeline
from worker.rpc.server import RpcServer
from worker.service import build_service


def make_service(tmp_path) -> RpcServer:
    con = connect(tmp_path / "a.db")
    registry = AdapterRegistry()
    registry.register(DemoAdapter(out_file=tmp_path / "demo_published.json"))
    pipeline = Pipeline(registry=registry, llm=StubLLM(), embedder=StubEmbedder(),
                        con=con, agent_id="ui")
    return build_service(registry=registry, pipeline=pipeline, real_mode=False)


async def _call(ws, method, params=None):
    await ws.send(json.dumps({"jsonrpc": "2.0", "id": method, "method": method, "params": params or {}}))
    while True:
        msg = json.loads(await ws.recv())
        if msg.get("id") == method:          # 跳过广播通知（决策 #14 同款过滤）
            return msg


async def test_service_roundtrip(tmp_path):
    server = make_service(tmp_path)
    async with server.start():
        async with websockets.connect(server.url) as ws:
            adapters = (await _call(ws, "adapters"))["result"]
            assert adapters == [{"platform_id": "demo", "display_name": "本地演示平台"}]

            health = (await _call(ws, "health", {"platform": "demo"}))["result"]
            assert health["status"] == "ok"

            stats = (await _call(ws, "memory_stats"))["result"]
            assert stats == {"l2_prefs": 0, "l3_posts": 0}

            cfg = (await _call(ws, "config_status"))["result"]
            assert cfg == {"real_llm": False, "has_image": False, "has_embedding": False}

            draft = (await _call(ws, "run", {"platform": "demo"}))["result"]
            assert draft["status"] == "pending_review"

            drafts = (await _call(ws, "drafts"))["result"]
            assert len(drafts) == 1 and drafts[0]["draft_id"] == draft["draft_id"]
            assert drafts[0]["created_at"]                    # 决策 #8 的列现在被消费
            assert "images" in drafts[0] and "body" in drafts[0]

            approved = (await _call(ws, "approve", {"draft_id": draft["draft_id"]}))["result"]
            assert approved["success"] is True

            d2 = (await _call(ws, "run", {"platform": "demo"}))["result"]
            await _call(ws, "reject", {"draft_id": d2["draft_id"], "reason": "测试驳回"})
            drafts2 = (await _call(ws, "drafts"))["result"]
            by_id = {d["draft_id"]: d for d in drafts2}
            assert by_id[draft["draft_id"]]["status"] == "published"
            assert by_id[d2["draft_id"]]["status"] == "rejected"


async def test_service_broadcasts_on_run(tmp_path):
    server = make_service(tmp_path)
    events = []
    async with server.start():
        async with websockets.connect(server.url) as ws:
            await ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "run", "params": {"platform": "demo"}}))
            while True:
                msg = json.loads(await ws.recv())
                if "method" in msg:                          # 通知帧
                    events.append(msg["method"])
                    if msg["method"] == "drafts_changed":
                        break
                elif msg.get("id") == 1:
                    continue
    assert "stage_changed" in events and "drafts_changed" in events


async def test_concurrent_runs_are_serialized(tmp_path):
    """两个客户端几乎同时 run：必须串行化——draft_id 互不相同且无覆盖。

    同连接的请求本就被 RpcServer._handle 逐条 await 串行处理，重入窗口在跨连接处；
    SlowLLM 放大无锁时两个执行器线程的重叠（竞态→算出同一 draft_id 互相覆盖）。
    """
    con = connect(tmp_path / "b.db")
    registry = AdapterRegistry()
    registry.register(DemoAdapter(out_file=tmp_path / "demo_published.json"))

    class SlowLLM(StubLLM):
        def complete(self, system: str, user: str) -> str:
            time.sleep(0.05)
            return super().complete(system, user)

    pipeline = Pipeline(registry=registry, llm=SlowLLM(), embedder=StubEmbedder(), con=con, agent_id="ui")
    server = build_service(registry=registry, pipeline=pipeline, real_mode=False)

    async def _recv_result(ws, mid):
        while True:
            msg = json.loads(await ws.recv())
            if msg.get("id") == mid:
                return msg["result"]["draft_id"]

    async with server.start():
        async with websockets.connect(server.url) as ws1, websockets.connect(server.url) as ws2:
            await ws1.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "run", "params": {"platform": "demo"}}))
            await ws2.send(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "run", "params": {"platform": "demo"}}))
            id1, id2 = await asyncio.gather(_recv_result(ws1, 1), _recv_result(ws2, 2))
            assert id1 != id2
            drafts = (await _call(ws1, "drafts"))["result"]
            assert len(drafts) == 2


async def test_health_unknown_platform_friendly_error(tmp_path):
    server = make_service(tmp_path)
    async with server.start():
        async with websockets.connect(server.url) as ws:
            resp = await _call(ws, "health", {"platform": "weibo"})
            assert "未知平台" in resp["error"]
