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
    from worker.adapters import demo as demo_mod
    from worker.adapters.base import load_adapters

    monkeypatch.chdir(tmp_path)
    registry = load_adapters()
    assert "demo" in registry.all()
    # 假平台真实可走完四方法
    a = registry.get("demo")
    assert a.check_health().status.value == "ok"
    assert a.fetch_trends()[0].title
