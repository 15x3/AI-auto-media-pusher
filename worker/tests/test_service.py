import asyncio
import json

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
