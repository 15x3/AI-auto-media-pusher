import pytest


def test_cli_run_and_approve_roundtrip(tmp_path, monkeypatch, capsys):
    from worker import cli

    monkeypatch.chdir(tmp_path)
    cli.main(["run", "demo"])
    out1 = capsys.readouterr().out
    assert "pending_review" in out1
    assert "AI Agent 一周动态" in out1

    draft_id = out1.split("draft_id=")[1].split()[0]
    cli.main(["approve", draft_id])
    out2 = capsys.readouterr().out
    assert "published" in out2
    assert (tmp_path / "demo_published.json").exists()


def test_cli_approve_failure_reports_real_status_and_exits_nonzero(tmp_path, monkeypatch, capsys):
    from worker import cli
    from worker.adapters.base import (
        AdapterRegistry,
        HealthReport,
        HealthStatus,
        PlatformAdapter,
        PlatformPost,
        PublishResult,
        Trend,
    )

    class _FailPublish(PlatformAdapter):
        platform_id = "failpub"
        display_name = "发布必败平台"

        def check_health(self):
            return HealthReport(HealthStatus.OK)

        def fetch_trends(self):
            return [Trend("必败选题", heat=5.0)]

        def compose_post(self, title, body, images):
            return PlatformPost(title=title, body=body)

        def execute_publish(self, post):
            return PublishResult(success=False, detail="模拟发布失败")

    monkeypatch.chdir(tmp_path)
    registry = AdapterRegistry()
    registry.register(_FailPublish())
    monkeypatch.setattr(cli, "load_adapters", lambda *a, **k: registry)  # 同步：装配层现在传 builder

    cli.main(["run", "failpub"])
    draft_id = capsys.readouterr().out.split("draft_id=")[1].split()[0]

    with pytest.raises(SystemExit) as exc_info:
        cli.main(["approve", draft_id])
    assert exc_info.value.code == 1
    out2 = capsys.readouterr().out
    assert "status=pending_review success=False" in out2


def test_cli_approve_blank_edit_normalized_to_no_edit(tmp_path, monkeypatch, capsys):
    from worker import cli
    from worker.memory.store import connect

    monkeypatch.chdir(tmp_path)
    cli.main(["run", "demo"])
    draft_id = capsys.readouterr().out.split("draft_id=")[1].split()[0]

    cli.main(["approve", draft_id, "--title", "  "])
    out2 = capsys.readouterr().out
    assert "success=True" in out2

    # 纯空白改写被规整为 None → 未视为改写 → L3 不降权
    con = connect(tmp_path / "agent.db")
    (edited,) = con.execute("SELECT edited_by_user FROM post_archive").fetchone()
    assert edited == 0
