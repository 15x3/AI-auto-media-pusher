from worker.llm.client import StubEmbedder
from worker.memory.l3 import GlobalMemory
from worker.memory.store import connect


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
