"""平台适配器契约：四方法 + 元数据 + 自动注册表。"""
import importlib
import pkgutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class HealthStatus(str, Enum):
    OK = "ok"
    NEEDS_LOGIN = "needs_login"
    BROKEN = "broken"


class PublishError(str, Enum):
    LOGIN_EXPIRED = "login_expired"
    SELECTOR_BROKEN = "selector_broken"
    PLATFORM_REJECTED = "platform_rejected"


@dataclass
class HealthReport:
    status: HealthStatus
    detail: str = ""


@dataclass
class Trend:
    title: str
    heat: float = 0.0
    url: str = ""


@dataclass
class PlatformPost:
    title: str
    body: str
    tags: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)


@dataclass
class PublishResult:
    success: bool
    post_url: str = ""
    error: PublishError | None = None
    detail: str = ""


CONTRACT_METHODS = ("check_health", "fetch_trends", "compose_post", "execute_publish")


class ContractError(Exception):
    """适配器未满足四方法契约。"""


class PlatformAdapter(ABC):
    platform_id: str = ""
    display_name: str = ""

    @abstractmethod
    def check_health(self) -> HealthReport: ...

    @abstractmethod
    def fetch_trends(self) -> list[Trend]: ...

    @abstractmethod
    def compose_post(self, title: str, body: str, images: list[str]) -> PlatformPost: ...

    @abstractmethod
    def execute_publish(self, post: PlatformPost) -> PublishResult: ...


class AdapterRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, PlatformAdapter] = {}

    def register(self, adapter: PlatformAdapter) -> None:
        cls = type(adapter)
        missing = [m for m in CONTRACT_METHODS if not callable(getattr(cls, m, None))]
        if missing:
            raise ContractError(f"{cls.__name__} 缺少契约方法: {missing}")
        if not adapter.platform_id:
            raise ContractError(f"{cls.__name__} 缺少 platform_id")
        if adapter.platform_id in self._adapters:
            raise ContractError(
                f"platform_id 冲突: {adapter.platform_id!r} 已注册于 "
                f"{type(self._adapters[adapter.platform_id]).__name__}"
            )
        self._adapters[adapter.platform_id] = adapter

    def get(self, platform_id: str) -> PlatformAdapter:
        return self._adapters[platform_id]

    def all(self) -> dict[str, PlatformAdapter]:
        return dict(self._adapters)


def load_adapters(package: str = "worker.adapters") -> "AdapterRegistry":
    """扫描适配器包目录，放即注册：凡继承 PlatformAdapter 的具体类自动进入注册表。"""
    registry = AdapterRegistry()
    pkg = importlib.import_module(package)
    for mod_info in pkgutil.iter_modules(pkg.__path__):
        if mod_info.name == "base":
            continue
        module = importlib.import_module(f"{package}.{mod_info.name}")
        for obj in vars(module).values():
            if (
                isinstance(obj, type)
                and issubclass(obj, PlatformAdapter)
                and obj is not PlatformAdapter
                and obj.__module__.startswith(package)
                and not getattr(obj, "__abstractmethods__", None)
            ):
                registry.register(obj())
    return registry
