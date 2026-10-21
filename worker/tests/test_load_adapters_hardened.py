"""builder 钩子与 per-module 容错。合成包方案沿袭计划 1 的 tests/synth_adapters 模式。"""
import sys
from pathlib import Path

from worker.adapters.base import load_adapters

SYNTH = Path(__file__).parent / "synth_v2"


def _make_pkg(name: str, mod_name: str, body: str) -> None:
    pkg = SYNTH / name
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / f"{mod_name}.py").write_text(body, encoding="utf-8")


def test_builder_hook_injects_dependencies(tmp_path):
    _make_pkg("builder_case", "frozen", '''\
from worker.adapters.base import HealthReport, HealthStatus, PlatformAdapter, PlatformPost, PublishResult, Trend


class FrozenAdapter(PlatformAdapter):
    platform_id = "frozen"
    display_name = "注入适配器"

    def __init__(self, deps=None):
        self.deps = deps

    def check_health(self):
        return HealthReport(HealthStatus.OK)

    def fetch_trends(self):
        return [Trend("t", 1.0)]

    def compose_post(self, title, body, images):
        return PlatformPost(title=title, body=body)

    def execute_publish(self, post):
        return PublishResult(success=True)
''')
    sys.path.insert(0, str(SYNTH))
    try:
        registry = load_adapters("builder_case", builder=lambda cls: cls(deps={"pw": True}))
        assert registry.get("frozen").deps == {"pw": True}
    finally:
        sys.path.remove(str(SYNTH))


def test_broken_module_skipped_with_warning_not_fatal(capsys):
    # import nonexistent_module_xyz 确定性触发 ImportError，模拟可选依赖（如 playwright）缺失
    _make_pkg("tolerant_case", "needs_playwright", "import nonexistent_module_xyz  # 模拟可选依赖缺失\n")
    _make_pkg("tolerant_case", "fine", '''\
from worker.adapters.base import HealthReport, HealthStatus, PlatformAdapter, PlatformPost, PublishResult, Trend


class FineAdapter(PlatformAdapter):
    platform_id = "fine"
    display_name = "正常适配器"

    def check_health(self):
        return HealthReport(HealthStatus.OK)

    def fetch_trends(self):
        return []

    def compose_post(self, title, body, images):
        return PlatformPost(title=title, body=body)

    def execute_publish(self, post):
        return PublishResult(success=True)
''')
    sys.path.insert(0, str(SYNTH))
    try:
        registry = load_adapters("tolerant_case")
        assert set(registry.all()) == {"fine"}   # 坏模块被跳过，好模块照常注册
        err = capsys.readouterr().err
        assert "needs_playwright" in err and "跳过" in err
    finally:
        sys.path.remove(str(SYNTH))
