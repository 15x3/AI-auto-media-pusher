from pathlib import Path


def test_cli_login_command_calls_adapter_and_closes(tmp_path, monkeypatch, capsys):
    from worker import cli

    closed = []

    class _FakeAdapter:
        platform_id = "demo"
        display_name = "本地演示平台"

        def login(self):
            from worker.adapters.base import HealthReport, HealthStatus
            return HealthReport(HealthStatus.OK, "已登录")

        def close(self):
            closed.append(True)

    class _FakeRegistry:
        def get(self, pid):
            return _FakeAdapter()

        def all(self):
            return {"demo": _FakeAdapter()}

    monkeypatch.setattr(cli, "load_adapters", lambda *a, **k: _FakeRegistry())
    monkeypatch.chdir(tmp_path)
    cli.main(["login", "demo"])
    assert closed == [True]                       # 决策 #20：login 后必 close
    assert "已登录" in capsys.readouterr().out


def test_cli_login_failure_exits_nonzero(tmp_path, monkeypatch):
    from worker import cli

    class _FakeAdapter:
        platform_id = "demo"
        display_name = "d"

        def login(self):
            from worker.adapters.base import HealthReport, HealthStatus
            return HealthReport(HealthStatus.NEEDS_LOGIN, "超时")

        def close(self):
            pass

    class _FakeRegistry:
        def get(self, pid):
            return _FakeAdapter()

        def all(self):
            return {"demo": _FakeAdapter()}

    monkeypatch.setattr(cli, "load_adapters", lambda *a, **k: _FakeRegistry())
    monkeypatch.chdir(tmp_path)
    import pytest

    with pytest.raises(SystemExit) as ei:
        cli.main(["login", "demo"])
    assert ei.value.code == 1


def test_cli_without_config_uses_stubs_and_hints(tmp_path, monkeypatch, capsys):
    from worker import cli

    monkeypatch.chdir(tmp_path)
    cli.main(["run", "demo"])
    out = capsys.readouterr().out
    assert "pending_review" in out                 # demo + 桩照常工作
    assert "config.example.toml" in out            # 桩模式提示


def test_cli_run_runtimeerror_friendly(tmp_path, monkeypatch, capsys):
    """决策 #26⑥：run 的 RuntimeError 打友好错误而非裸 traceback。"""
    from worker import cli
    import pytest

    class _BoomPipeline:
        def __init__(self, *a, **k):
            pass

        def run(self, platform_id):
            raise RuntimeError("chat/completions 重试 2 次后仍失败: 500")

    monkeypatch.setattr(cli, "_pipeline", lambda *a, **k: _BoomPipeline())
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as ei:
        cli.main(["run", "demo"])
    assert ei.value.code == 1
    err = capsys.readouterr().err
    assert "运行失败" in err and "chat/completions" in err
