"""Agent 流水线：调研 → L3 召回 → 写作 → 配图 → compose → 待审；审核后发布并写回 L3。"""
import json
import sqlite3
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .adapters.base import AdapterRegistry, PlatformPost, PublishResult
from .llm.client import Embedder, LLMClient
from .memory.l1 import RunContext
from .memory.l2 import AgentMemory
from .memory.l3 import GlobalMemory

WRITER_SYSTEM = """你是一位图文创作者。参考以下本人历史帖的风格：
{style_block}
遵守以下偏好约束：
{prefs_block}
以自然、克制的口吻写作。"""


class Stage(str, Enum):
    RESEARCH = "research"
    WRITE = "write"
    IMAGE = "image"
    REVIEW = "review"
    PUBLISHED = "published"


@dataclass
class Draft:
    draft_id: str
    platform: str
    title: str
    body: str
    images: list[str] = field(default_factory=list)
    post: PlatformPost | None = None
    status: str = "pending_review"  # pending_review / published / rejected


class Pipeline:
    def __init__(
        self,
        registry: AdapterRegistry,
        llm: LLMClient,
        embedder: Embedder,
        con: sqlite3.Connection,
        agent_id: str = "default",
        image_client=None,                       # 可选：OpenAIImageClient（协议 generate(prompt, out_path) -> Path）
        images_root: Path = Path("data/images"),
    ) -> None:
        self.registry = registry
        self.llm = llm
        self.agent = AgentMemory(con, agent_id)
        self.global_mem = GlobalMemory(con, embedder)
        self._con = con
        self._run_no = self._count_runs()
        self.drafts: dict[str, Draft] = {}
        self.last_context: RunContext | None = None
        self.image_client = image_client
        self.images_root = Path(images_root).resolve()
        self._load_drafts()

    # ---- 运行 ----

    def run(self, platform_id: str) -> Draft:
        self._run_no += 1
        ctx = RunContext(run_id=self._run_no)
        adapter = self.registry.get(platform_id)

        trends = adapter.fetch_trends()  # ① 调研
        if not trends:
            raise ValueError(f"平台 {platform_id} 热榜为空，本轮无法选题")
        topic = max(trends, key=lambda t: t.heat).title
        ctx.topic = topic

        ctx.recalled = self.global_mem.recall(topic, k=3)  # ② 写作前召回（风格样例）
        style_block = "\n".join(f"- {r['title']}" for r in ctx.recalled) or "（暂无历史帖）"
        prefs = dict(self.agent.get_prefs())
        rejections = prefs.pop("rejections", [])
        if len(rejections) > 10:
            prefs["rejections_摘要"] = f"共 {len(rejections)} 条（仅列最近 10 条）"
            prefs["rejections"] = rejections[-10:]
        elif rejections:
            prefs["rejections"] = rejections[-10:]
        prefs_block = json.dumps(prefs, ensure_ascii=False)
        body = self.llm.complete(WRITER_SYSTEM.format(style_block=style_block, prefs_block=prefs_block), topic)

        if self.image_client is not None:
            cover = self.image_client.generate(
                prompt=f"封面图：{topic}", out_path=self.images_root / f"d{self._run_no}" / "cover.png"
            )
            images = [str(cover)]  # 配图：真实文生图封面
        else:
            images = [f"cover-stub:{topic[:12]}"]  # 配图占位（无真实客户端时）
        post = adapter.compose_post(topic, body, images)  # ④ 平台规范适配
        draft = Draft(
            draft_id=f"d{self._run_no}",
            platform=platform_id,
            title=topic,
            body=body,
            images=images,
            post=post,
            status="pending_review",
        )
        self.drafts[draft.draft_id] = draft
        self._save_draft(draft)

        ctx.draft_id = draft.draft_id
        self.last_context = ctx
        ctx.archive()  # L1 归档
        return draft

    # ---- 审核动作（人机边界：compose 之后、publish 之前）----

    def approve(self, draft_id: str, edited_title: str | None = None, edited_body: str | None = None) -> PublishResult:
        draft = self.drafts.get(draft_id)
        if draft is None:
            raise ValueError(f"draft {draft_id} 不存在")
        edited_title = edited_title.strip() or None if edited_title is not None else None
        edited_body = edited_body.strip() or None if edited_body is not None else None
        if draft.status != "pending_review":
            raise ValueError(f"draft {draft_id} 状态为 {draft.status}，不能发布")

        edited = edited_title is not None or edited_body is not None
        title = edited_title or draft.title
        body = edited_body or draft.body
        adapter = self.registry.get(draft.platform)
        if edited or draft.post is None:
            # 改写后需重新适配平台规范；跨进程加载的草稿 post 为 None（_load_drafts 不持久化
            # PlatformPost），发布前必须重建——tags 本就是 compose 时平台侧生成的
            draft.post = adapter.compose_post(title, body, draft.images)
        result = adapter.execute_publish(draft.post)
        if result.success:
            draft.status = "published"
            # 注意：发布后 DB 写失败会遮蔽成功事实（at-least-once 语义，决策 #10）
            self._save_draft(draft)
            try:
                self.global_mem.add(  # L3 写回；被改写的帖子 edited=True → 召回降权
                    text=f"{title}\n{body}", platform=draft.platform, title=title, body=body, edited=edited
                )
            except Exception as exc:  # noqa: BLE001 - 记忆写失败不遮蔽发布成功
                print(f"[memory] L3 写回失败（发布已成功）: {exc}", file=sys.stderr)
        return result

    def reject(self, draft_id: str, reason: str) -> None:
        reason = reason.strip() or "(未填理由)"  # 空理由规整，不裸入库
        draft = self.drafts.get(draft_id)
        if draft is None:
            raise ValueError(f"draft {draft_id} 不存在")
        if draft.status != "pending_review":
            raise ValueError(f"draft {draft_id} 状态为 {draft.status}，不能驳回")
        draft.status = "rejected"
        self._save_draft(draft)
        self.agent.record_rejection(reason)  # 驳回理由沉淀为 L2 偏好

    # ---- 持久化 ----

    def _count_runs(self) -> int:
        (n,) = self._con.execute(
            "SELECT COALESCE(MAX(CAST(substr(draft_id, 2) AS INTEGER)), 0) FROM draft"
        ).fetchone()
        return n

    def _save_draft(self, draft: Draft) -> None:
        self._con.execute(
            "INSERT INTO draft(draft_id, platform, title, body, images_json, status) VALUES(?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(draft_id) DO UPDATE SET title=excluded.title, body=excluded.body, "
            "images_json=excluded.images_json, status=excluded.status",
            (
                draft.draft_id,
                draft.platform,
                draft.title,
                draft.body,
                json.dumps(draft.images, ensure_ascii=False),
                draft.status,
            ),
        )
        self._con.commit()

    def _load_drafts(self) -> None:
        for row in self._con.execute("SELECT draft_id, platform, title, body, images_json, status FROM draft"):
            draft_id, platform, title, body, images_json, status = row
            self.drafts[draft_id] = Draft(
                draft_id=draft_id, platform=platform, title=title, body=body,
                images=json.loads(images_json), status=status,
            )
