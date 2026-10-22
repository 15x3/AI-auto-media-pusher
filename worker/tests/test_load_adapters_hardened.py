"""builder 钩子与 per-module 容错。合成包静态提交，沿袭计划 1 的 tests/synth_adapters 模式。"""
from worker.adapters.base import load_adapters


def test_builder_hook_injects_dependencies():
    registry = load_adapters("tests.synth_v2.builder_case", builder=lambda cls: cls(deps={"pw": True}))
    assert registry.get("frozen").deps == {"pw": True}


def test_broken_module_skipped_with_warning_not_fatal(capsys):
    # needs_playwright.py 顶层 import 不存在的模块，模拟可选依赖（如 playwright）缺失
    registry = load_adapters("tests.synth_v2.tolerant_case")
    assert set(registry.all()) == {"fine"}   # 坏模块被跳过，好模块照常注册
    err = capsys.readouterr().err
    assert "needs_playwright" in err and "跳过" in err
