import pytest

from worker.adapters.base import (
    AdapterRegistry,
    ContractError,
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
