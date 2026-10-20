import pytest

from worker.adapters.base import (
    AdapterRegistry,
    ContractError,
    CONTRACT_METHODS,
    HealthReport,
    HealthStatus,
    PlatformAdapter,
)


class _Full(PlatformAdapter):
    platform_id = "full"

    def check_health(self):
        return HealthReport(HealthStatus.OK)

    def fetch_trends(self):
        return []

    def compose_post(self, title, body, images):
        return None

    def execute_publish(self, post):
        return None


class _Missing(_Full):
    platform_id = "missing"
    fetch_trends = None  # 契约破坏：方法缺失


def test_register_accepts_full_contract():
    registry = AdapterRegistry()
    registry.register(_Full())
    assert registry.get("full").platform_id == "full"
    assert set(registry.all()) == {"full"}


def test_register_rejects_broken_contract():
    with pytest.raises(ContractError, match="fetch_trends"):
        AdapterRegistry().register(_Missing())


def test_register_rejects_missing_platform_id():
    class _NoId(_Full):
        platform_id = ""

    with pytest.raises(ContractError, match="platform_id"):
        AdapterRegistry().register(_NoId())


def test_register_rejects_duplicate_platform_id():
    registry = AdapterRegistry()
    registry.register(_Full())
    with pytest.raises(ContractError, match="platform_id 冲突"):
        registry.register(_Full())


def test_contract_methods_match_abstract_interface():
    assert set(CONTRACT_METHODS) == set(PlatformAdapter.__abstractmethods__)


def test_load_adapters_autoregisters_demo(tmp_path, monkeypatch):
    from worker.adapters.base import load_adapters

    monkeypatch.chdir(tmp_path)
    registry = load_adapters()
    assert "demo" in registry.all()
    # 假平台真实可走完四方法
    a = registry.get("demo")
    assert a.check_health().status.value == "ok"
    assert a.fetch_trends()[0].title
    post = a.compose_post("t", "b", [])
    r = a.execute_publish(post)
    assert r.success
    import json

    data = json.loads((tmp_path / "demo_published.json").read_text(encoding="utf-8"))
    assert data[-1]["title"] == "[demo] t"


def test_load_adapters_ignores_reexported_classes():
    from worker.adapters.base import load_adapters

    # reexport.py 转手引入 RealAdapter（定义于 real.py）：只应注册一次
    registry = load_adapters("tests.synth_adapters.reexport_case")
    assert set(registry.all()) == {"real"}


def test_load_adapters_skips_idless_intermediate_classes():
    from worker.adapters.base import load_adapters

    # shared.py 是四方法齐全但无 platform_id 的共享基类：跳过；只收终端适配器
    registry = load_adapters("tests.synth_adapters.shared_case")
    assert set(registry.all()) == {"terminal"}
