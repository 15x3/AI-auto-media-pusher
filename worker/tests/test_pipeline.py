import json

import pytest

from worker.adapters.base import (
    AdapterRegistry,
    HealthReport,
    HealthStatus,
    PlatformAdapter,
    PlatformPost,
    PublishResult,
)
from worker.adapters.demo import DemoAdapter
from worker.llm.client import StubEmbedder, StubLLM
from worker.memory.store import connect
from worker.pipeline import Pipeline


class _EmptyTrends(PlatformAdapter):
    platform_id = "empty"
    display_name = "空热榜平台"

    def check_health(self):
        return HealthReport(HealthStatus.OK)

    def fetch_trends(self):
        return []

    def compose_post(self, title, body, images):
        return PlatformPost(title=title, body=body)

    def execute_publish(self, post):
        return PublishResult(success=True)


def make_pipeline(tmp_path, db="a.db"):
    con = connect(tmp_path / db)
    registry = AdapterRegistry()
    registry.register(DemoAdapter(out_file=tmp_path / "demo_published.json"))
    return Pipeline(
        registry=registry,
        llm=StubLLM(),
        embedder=StubEmbedder(),
        con=con,
        agent_id="tech-笔记官",
    )


def test_run_produces_pending_review_draft(tmp_path):
    pipe = make_pipeline(tmp_path)
    draft = pipe.run(platform_id="demo")

    assert draft.status == "pending_review"
    assert draft.platform == "demo"
    assert draft.title == "AI Agent 一周动态"  # 热度最高选题
    assert draft.post.title.startswith("[demo]")  # compose_post 已套用平台规范
    assert draft.images  # 配图占位存在
    assert "StubLLM" in draft.body  # 写作经 LLM 桩
    assert draft.draft_id in pipe.drafts


def test_run_second_time_recalls_history_into_draft(tmp_path):
    pipe = make_pipeline(tmp_path)
    first = pipe.run(platform_id="demo")
    pipe.approve(first.draft_id)  # 发布后写回 L3

    second = pipe.run(platform_id="demo")
    # 第二次运行召回列表应包含第一篇（风格样例注入写作）
    assert any(first.title == r["title"] for r in pipe.last_context.recalled)


def test_run_empty_trends_raises_clear_error(tmp_path):
    con = connect(tmp_path / "b.db")
    registry = AdapterRegistry()
    registry.register(_EmptyTrends())
    pipe = Pipeline(registry=registry, llm=StubLLM(), embedder=StubEmbedder(), con=con)
    with pytest.raises(ValueError, match="热榜为空"):
        pipe.run(platform_id="empty")


def test_new_instance_draft_ids_do_not_collide_after_failed_run(tmp_path):
    con = connect(tmp_path / "c.db")
    registry = AdapterRegistry()
    registry.register(DemoAdapter(out_file=tmp_path / "demo_published.json"))
    registry.register(_EmptyTrends())

    pipe1 = Pipeline(registry=registry, llm=StubLLM(), embedder=StubEmbedder(), con=con)
    pipe1.run(platform_id="demo")  # d1
    with pytest.raises(ValueError, match="热榜为空"):
        pipe1.run(platform_id="empty")  # 编号 2 被消耗，留下空隙（无草稿落库）
    pipe1.run(platform_id="demo")  # 同进程编号推进到 d3
    assert set(pipe1.drafts) == {"d1", "d3"}

    pipe2 = Pipeline(registry=registry, llm=StubLLM(), embedder=StubEmbedder(), con=con)
    new_draft = pipe2.run(platform_id="demo")

    # 新实例不得复用已存在的编号（RED 时为 "d3"，ON CONFLICT 会静默覆盖待审草稿）
    assert new_draft.draft_id not in {"d1", "d3"}
    # 旧待审草稿仍在库中，未被覆盖：3 篇草稿各占一行
    (n,) = con.execute("SELECT COUNT(*) FROM draft").fetchone()
    assert n == 3
