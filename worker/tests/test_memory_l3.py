import pytest

from worker.llm.client import StubEmbedder
from worker.memory.l3 import GlobalMemory
from worker.memory.store import connect


class BoomEmbedder(StubEmbedder):
    """带 BOOM 标记的文本触发抛错，模拟计划 2 真实 embedding API 网络失败。"""

    def embed(self, texts: list[str]) -> list[list[float]]:
        if any("BOOM" in t for t in texts):
            raise RuntimeError("embedding api down")
        return super().embed(texts)


class FixedEmbedder(StubEmbedder):
    """文本→固定向量映射，未知文本退回全零，用于构造可控距离几何。"""

    def __init__(self, dims: int, mapping: dict[str, list[float]]) -> None:
        super().__init__(dims=dims)
        self.mapping = mapping

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.mapping.get(t, [0.0] * self.dims) for t in texts]


def _mem(tmp_path, dims=8):
    con = connect(tmp_path / "a.db")
    return GlobalMemory(con, StubEmbedder(dims=dims))


def test_add_and_recall_returns_nearest_first(tmp_path):
    mem = _mem(tmp_path)
    mem.add("AI Agent 一周动态", platform="demo", title="AI Agent 一周动态", body="正文A", edited=False)
    mem.add("桌面端工具的极客界面", platform="demo", title="桌面端工具的极客界面", body="正文B", edited=False)
    hits = mem.recall("AI Agent 动态", k=2)
    assert hits[0]["title"] == "AI Agent 一周动态"
    assert len(hits) == 2


def test_edited_posts_deprioritized(tmp_path):
    mem = _mem(tmp_path)
    mem.add("AI Agent 一周动态", platform="demo", title="AI Agent 一周动态", body="A", edited=True)
    mem.add("AI Agent 框架对比", platform="demo", title="AI Agent 框架对比", body="B", edited=False)
    hits = mem.recall("AI Agent 一周动态", k=1)
    assert hits[0]["title"] == "AI Agent 框架对比"  # 主题更近但被改写的帖子让位


def test_recall_empty_library(tmp_path):
    assert _mem(tmp_path).recall("任何主题", k=3) == []


def test_add_embedder_failure_rolls_back_no_orphan(tmp_path):
    con = connect(tmp_path / "a.db")
    mem = GlobalMemory(con, BoomEmbedder(dims=8))
    with pytest.raises(RuntimeError):
        mem.add("BOOM 主题", platform="demo", title="孤儿", body="b", edited=False)
    assert con.in_transaction is False
    assert con.execute("SELECT COUNT(*) FROM post_archive").fetchone()[0] == 0


def test_recall_window_covers_far_clean_posts_in_edited_cluster(tmp_path):
    con = connect(tmp_path / "a.db")
    mapping = {
        "查询": [1.0, 0.0],
        **{f"edited-{i}": [1.0, 0.0] for i in range(6)},  # 与查询零距离
        **{f"clean-{i}": [0.8, 0.6] for i in range(2)},  # 较远但未改写
    }
    mem = GlobalMemory(con, FixedEmbedder(dims=2, mapping=mapping), dims=2)
    for i in range(6):
        mem.add(f"edited-{i}", platform="demo", title=f"edited-{i}", body="x", edited=True)
    for i in range(2):
        mem.add(f"clean-{i}", platform="demo", title=f"clean-{i}", body="x", edited=False)
    hits = mem.recall("查询", k=3)  # k*2=6 恰被 6 条零距离 edited 填满
    titles = {h["title"] for h in hits}
    assert {"clean-0", "clean-1"} <= titles  # 较远的未改写帖不被挤出召回窗口


def test_dim_mismatch_raises_at_construction(tmp_path):
    con = connect(tmp_path / "a.db")
    with pytest.raises(ValueError):
        GlobalMemory(con, StubEmbedder(dims=8), dims=16)


def test_dims_auto_inferred_when_none(tmp_path):
    """决策 #16：dims=None 时以哨兵探测长度自动建表——真实 embedding 接入的关键路径。"""
    from worker.llm.client import StubEmbedder

    con = connect(tmp_path / "auto.db")
    mem = GlobalMemory(con, StubEmbedder(dims=16))   # 不传 dims → 自动 16
    mem.add("文本A", platform="demo", title="A", body="a", edited=False)
    hits = mem.recall("文本A", k=1)
    assert hits[0]["title"] == "A"
