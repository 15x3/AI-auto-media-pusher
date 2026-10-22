"""RPC 服务层：把 registry / pipeline 接成 JSON-RPC 方法。阻塞调用经执行器卸载，不卡事件循环。"""
import asyncio
import sqlite3

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

    async def _run(fn, *args):
        # Playwright/LLM 都是阻塞调用——在协程内取运行环卸载到执行器（3.12 禁在无运行环处 get_event_loop）
        return await asyncio.get_running_loop().run_in_executor(None, fn, *args)

    @server.method("adapters")
    async def adapters(params):
        return [{"platform_id": pid, "display_name": a.display_name} for pid, a in registry.all().items()]

    @server.method("health")
    async def health(params):
        report = await _run(registry.get(params["platform"]).check_health)
        return {"status": report.status.value, "detail": report.detail}

    @server.method("run")
    async def run(params):
        await server.broadcast("stage_changed", {"stage": "research", "platform": params["platform"]})
        draft = await _run(pipeline.run, params["platform"])
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
        result = await _run(
            pipeline.approve, params["draft_id"],
            params.get("title"), params.get("body"),
        )
        await server.broadcast("drafts_changed", {"draft_id": params["draft_id"]})
        return {"success": result.success, "post_url": result.post_url,
                "error": result.error.value if result.error else None, "detail": result.detail}

    @server.method("reject")
    async def reject(params):
        await _run(pipeline.reject, params["draft_id"], params["reason"])
        await server.broadcast("drafts_changed", {"draft_id": params["draft_id"]})
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
