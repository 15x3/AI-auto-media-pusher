"""RPC 服务层：把 registry / pipeline 接成 JSON-RPC 方法。阻塞调用经执行器卸载，不卡事件循环。"""
import asyncio
import sqlite3
from concurrent.futures import ThreadPoolExecutor

from .rpc.server import RpcServer


def _draft_row(row) -> dict:
    import json as _json

    draft_id, platform, title, body, images_json, status, created_at = row
    return {
        "draft_id": draft_id, "platform": platform, "title": title, "body": body,
        "images": _json.loads(images_json), "status": status, "created_at": created_at,
    }


def build_service(registry, pipeline, real_mode: bool, has_image: bool = False,
                  has_embedding: bool = False) -> RpcServer:
    server = RpcServer()
    # run/approve/reject 共用一把锁串行化变更型操作：防并发 run 算出相同 draft_id 互相覆盖，
    # 也关闭 approve/reject 与 run 在共享 sqlite 连接上的跨线程事务交错窗口
    state_lock = asyncio.Lock()
    # Playwright sync 适配器线程亲和且同一 profile 不支持并发浏览器：全部阻塞调用
    # 固定到单线程执行器串行执行（run 进行中 health 排队——自用工具可接受，
    # 与 state_lock 的串行语义一致；此前用默认多线程池，并发 health 会让两个
    # 适配器同时起 playwright，触发 "Sync API inside the asyncio loop" 等竞态）
    blocking = ThreadPoolExecutor(max_workers=1, thread_name_prefix="worker-blocking")

    async def _run(fn, *args):
        # Playwright/LLM 都是阻塞调用——在协程内取运行环卸载到专用单线程执行器
        return await asyncio.get_running_loop().run_in_executor(blocking, fn, *args)

    def _platform(params) -> str:
        pid = params.get("platform")
        if not pid:
            raise ValueError("缺少参数: platform")
        if pid not in registry.all():
            raise ValueError(f"未知平台: {pid}（python -m worker adapters 查看已注册平台）")
        return pid

    def _draft_id(params) -> str:
        draft_id = params.get("draft_id")
        if not draft_id:
            raise ValueError("缺少参数: draft_id")
        return draft_id

    @server.method("adapters")
    async def adapters(params):
        return [{"platform_id": pid, "display_name": a.display_name} for pid, a in registry.all().items()]

    @server.method("health")
    async def health(params):
        report = await _run(registry.get(_platform(params)).check_health)
        return {"status": report.status.value, "detail": report.detail}

    @server.method("run")
    async def run(params):
        async with state_lock:
            pid = _platform(params)
            await server.broadcast("stage_changed", {"stage": "research", "platform": pid})
            draft = await _run(pipeline.run, pid)
            await server.broadcast("drafts_changed", {"draft_id": draft.draft_id})
            return {"draft_id": draft.draft_id, "platform": draft.platform,
                    "title": draft.title, "body": draft.body,
                    "images": draft.images, "status": draft.status}

    @server.method("drafts")
    async def drafts(params):
        rows = pipeline._con.execute(
            "SELECT draft_id, platform, title, body, images_json, status, created_at FROM draft "
            "ORDER BY created_at DESC"
        ).fetchall()
        return [_draft_row(r) for r in rows]

    @server.method("approve")
    async def approve(params):
        async with state_lock:
            draft_id = _draft_id(params)
            result = await _run(
                pipeline.approve, draft_id,
                params.get("title"), params.get("body"),
            )
            await server.broadcast("drafts_changed", {"draft_id": draft_id})
            return {"success": result.success, "post_url": result.post_url,
                    "error": result.error.value if result.error else None, "detail": result.detail}

    @server.method("reject")
    async def reject(params):
        async with state_lock:
            draft_id = _draft_id(params)
            # 空理由交给 Pipeline 规整为「(未填理由)」，与 CLI 行为一致
            await _run(pipeline.reject, draft_id, params.get("reason") or "")
            await server.broadcast("drafts_changed", {"draft_id": draft_id})
            return {}

    @server.method("memory_stats")
    async def memory_stats(params):
        con: sqlite3.Connection = pipeline._con
        (l2,) = con.execute("SELECT COUNT(*) FROM agent_pref").fetchone()
        (l3,) = con.execute("SELECT COUNT(*) FROM post_archive").fetchone()
        return {"l2_prefs": l2, "l3_posts": l3}

    @server.method("config_status")
    async def config_status(params):
        return {"real_llm": real_mode, "has_image": has_image, "has_embedding": has_embedding}

    return server
