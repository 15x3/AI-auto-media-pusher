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


def test_cli_run_construction_runtimeerror_friendly(tmp_path, monkeypatch, capsys):
    """构造期 RuntimeError（如 GlobalMemory embedding 探测失败）也打友好错误而非裸 traceback。"""

    from worker import cli
    import pytest

    def _boom(*a, **k):
        raise RuntimeError("embeddings 重试 2 次后仍失败: 401")

    monkeypatch.setattr(cli, "_pipeline", _boom)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as ei:
        cli.main(["run", "demo"])
    assert ei.value.code == 1
    err = capsys.readouterr().err
    assert "运行失败" in err and "embeddings" in err


def test_cli_with_config_assembles_real_clients(tmp_path, monkeypatch):
    from worker import cli
    from worker.llm.client import StubEmbedder

    cfg = tmp_path / "config.toml"
    cfg.write_text("""
[llm]
base_url = "https://api.example.com/v1"
api_key = "sk-x"
model = "m"
""", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    built = {}
    real_chat = cli.OpenAIChatClient
    monkeypatch.setattr(cli, "OpenAIChatClient",
                        lambda c, transport=None: built.setdefault("chat", real_chat(c, transport)))
    try:
        pipe = cli._pipeline(str(tmp_path / "agent.db"), str(cfg))
        assert "chat" in built                    # 真实 LLM 分支走通
        assert pipe.image_client is None          # 未配置 [image] → 图片桩
        assert isinstance(pipe.embedder, StubEmbedder)  # embedding 无配置 → 桩
    finally:
        cli.OpenAIChatClient = real_chat


def test_cli_login_forces_headless_false(tmp_path, monkeypatch):
    """login 需要扫码，即使配置 headless=true 也强制可见浏览器。"""
    from worker import cli

    cfg = tmp_path / "config.toml"
    cfg.write_text("[browser]\nheadless = true\n", encoding="utf-8")

    built_kwargs = []

    class _FakeAdapter:
        platform_id = "demo"
        display_name = "d"

        def __init__(self, **kwargs):
            built_kwargs.append(kwargs)

        def login(self):
            from worker.adapters.base import HealthReport, HealthStatus
            return HealthReport(HealthStatus.OK, "已登录")

        def close(self):
            pass

    class _FakeRegistry:
        def __init__(self, builder):
            self._adapter = builder(_FakeAdapter)

        def get(self, pid):
            return self._adapter

        def all(self):
            return {"demo": self._adapter}

    monkeypatch.setattr(cli, "load_adapters", lambda *a, **k: _FakeRegistry(k.get("builder")))
    monkeypatch.chdir(tmp_path)
    cli.main(["login", "demo"])
    assert built_kwargs and built_kwargs[0]["headless"] is False


def test_cli_explicit_config_missing_raises(tmp_path, monkeypatch):
    """显式 --config 指向不存在文件时报错，而非静默回退桩模式。"""
    from worker import cli
    import pytest

    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError, match="--config"):
        cli._load_config_if_any("nope.toml")


def test_cli_run_unknown_platform_friendly(tmp_path, monkeypatch, capsys):
    """run 遇未知平台打友好错误并退出码 1（python -m worker adapters 可查）。"""
    from worker import cli
    import pytest

    class _FakeRegistry:
        def get(self, pid):
            raise KeyError("weibo")

        def all(self):
            return {}

    monkeypatch.setattr(cli, "load_adapters", lambda *a, **k: _FakeRegistry())
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as ei:
        cli.main(["run", "weibo"])
    assert ei.value.code == 1
    assert "未知平台" in capsys.readouterr().err


def test_cli_login_unknown_platform_friendly(tmp_path, monkeypatch, capsys):
    """login 遇未知平台打友好错误并退出码 1。"""
    from worker import cli
    import pytest

    class _FakeRegistry:
        def get(self, pid):
            raise KeyError("weibo")

        def all(self):
            return {}

    monkeypatch.setattr(cli, "load_adapters", lambda *a, **k: _FakeRegistry())
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as ei:
        cli.main(["login", "weibo"])
    assert ei.value.code == 1
    assert "未知平台" in capsys.readouterr().err


def test_cli_run_hint_distinguishes_missing_image_section(tmp_path, monkeypatch, capsys):
    """有配置但缺 [image] 段时，占位封面提示应指向 [image] 段而非桩模式。"""
    from worker import cli

    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[llm]\nbase_url = "https://api.example.com/v1"\napi_key = "sk-x"\nmodel = "m"\n',
        encoding="utf-8",
    )

    class _FakeChat:
        def __init__(self, llm_cfg, transport=None):
            pass

        def complete(self, system, user):
            return "假正文"

    monkeypatch.setattr(cli, "OpenAIChatClient", _FakeChat)
    monkeypatch.chdir(tmp_path)
    cli.main(["run", "demo"])
    out = capsys.readouterr().out
    assert "未配置 [image] 段" in out
    assert "config.example.toml" not in out
