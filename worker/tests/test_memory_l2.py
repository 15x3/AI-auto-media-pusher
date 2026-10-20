from worker.memory.l2 import AgentMemory
from worker.memory.store import connect

KEYS = {
    "agent_pref",
    "post_archive",
    "draft",
}


def test_connect_creates_schema(tmp_path):
    con = connect(tmp_path / "a.db")
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert KEYS <= names


def test_prefs_roundtrip_and_rejections(tmp_path):
    con = connect(tmp_path / "a.db")
    mem = AgentMemory(con, agent_id="tech-笔记官")
    assert mem.get_prefs() == {}

    mem.set_pref("tone", "克制、有数据支撑")
    mem.record_rejection("标题太标题党")
    mem.record_rejection("缺少个人观点")

    prefs = mem.get_prefs()
    assert prefs["tone"] == "克制、有数据支撑"
    assert prefs["rejections"] == ["标题太标题党", "缺少个人观点"]

    # 按 agent 隔离
    other = AgentMemory(con, agent_id="ai-测评员")
    assert other.get_prefs() == {}
