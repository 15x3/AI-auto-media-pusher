from pathlib import Path

import pytest

from worker.adapters.base import AdapterRegistry
from worker.adapters.demo import DemoAdapter
from worker.llm.client import StubEmbedder, StubLLM
from worker.memory.store import connect
from worker.pipeline import Pipeline


class FakeImageClient:
    """落盘假 PNG，记录 prompt（满足 OpenAIImageClient 协议：generate(prompt, out_path) -> Path）。"""

    def __init__(self):
        self.prompts = []

    def generate(self, prompt: str, out_path: Path) -> Path:
        self.prompts.append(prompt)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"\x89PNG-fake")
        return out_path


def make_pipeline(tmp_path, image_client=None, agent_id="tech-笔记官") -> Pipeline:
    con = connect(tmp_path / "a.db")
    registry = AdapterRegistry()
    registry.register(DemoAdapter(out_file=tmp_path / "demo_published.json"))
    return Pipeline(
        registry=registry,
        llm=StubLLM(),
        embedder=StubEmbedder(),
        con=con,
        agent_id=agent_id,
        image_client=image_client,
        images_root=tmp_path / "images",
    )


def test_real_image_client_generates_cover_file(tmp_path):
    fake = FakeImageClient()
    pipe = make_pipeline(tmp_path, image_client=fake)
    draft = pipe.run(platform_id="demo")
    assert draft.images and Path(draft.images[0]).exists()
    assert str(draft.images[0]).startswith(str(tmp_path / "images"))
    assert draft.title in fake.prompts[0]


def test_stub_mode_when_no_image_client(tmp_path):
    pipe = make_pipeline(tmp_path, image_client=None)
    draft = pipe.run(platform_id="demo")
    assert draft.images[0].startswith("cover-stub:")   # 计划 1 行为保持


def test_approve_unknown_id_raises_value_error(tmp_path):
    pipe = make_pipeline(tmp_path)
    with pytest.raises(ValueError, match="不存在"):
        pipe.approve("nope")


def test_approve_blank_edits_normalized_as_no_edit(tmp_path):
    pipe = make_pipeline(tmp_path)
    d = pipe.run(platform_id="demo")
    pipe.approve(d.draft_id, edited_title="   ")   # 纯空白 → 视为未改写（决策 #13）
    hits = pipe.global_mem.recall(d.title, k=1)
    assert hits[0]["edited"] is False


def test_l3_writeback_failure_does_not_mask_publish(tmp_path, capsys, monkeypatch):
    pipe = make_pipeline(tmp_path)
    d = pipe.run(platform_id="demo")

    def boom(*args, **kwargs):
        raise RuntimeError("L3 挂了")

    monkeypatch.setattr(pipe.global_mem, "add", boom)
    result = pipe.approve(d.draft_id)
    assert result.success                                  # 发布事实优先（决策 #10）
    assert pipe.drafts[d.draft_id].status == "published"
    assert "L3 写回失败" in capsys.readouterr().err


def test_rejections_capped_in_prompt(tmp_path):
    pipe = make_pipeline(tmp_path)
    for i in range(12):
        pipe.agent.record_rejection(f"理由{i}")

    class SpyLLM2(StubLLM):
        def __init__(self):
            super().__init__()
            self.last_system = ""

        def complete(self, system, user):
            self.last_system = system
            return super().complete(system, user)

    spy = SpyLLM2()
    con = connect(tmp_path / "a.db")
    registry = AdapterRegistry()
    registry.register(DemoAdapter(out_file=tmp_path / "demo_published.json"))
    pipe2 = Pipeline(registry=registry, llm=spy, embedder=StubEmbedder(), con=con, agent_id="tech-笔记官")
    pipe2.run(platform_id="demo")
    assert "理由11" in spy.last_system        # 最近一条保留（决策 #7：截到最近 10 条）
    assert "理由0" not in spy.last_system     # 最早的被截断
    assert "共 12 条" in spy.last_system      # 汇总计数
