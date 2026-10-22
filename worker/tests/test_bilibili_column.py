from pathlib import Path

import base64

import pytest

from worker.adapters.base import HealthStatus, PublishError
from worker.adapters.bilibili_column import BilibiliColumnAdapter

FIXTURES = Path(__file__).parent / "fixtures"


def make_adapter(tmp_path, **routes: Path) -> BilibiliColumnAdapter:
    a = BilibiliColumnAdapter(profiles_root=tmp_path / "profiles", headless=True)
    a.FIXTURE_ROUTES = dict(routes)
    return a


def _make_png(path: Path) -> Path:
    path.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    ))
    return path


def test_check_health_ok(tmp_path):
    a = make_adapter(tmp_path, **{"**://member.bilibili.com/**": FIXTURES / "bili_home_logged_in.html"})
    try:
        assert a.check_health().status is HealthStatus.OK
    finally:
        a.close()


def test_check_health_needs_login(tmp_path):
    a = make_adapter(tmp_path, **{"**://member.bilibili.com/**": FIXTURES / "bili_home_logged_out.html"})
    try:
        assert a.check_health().status is HealthStatus.NEEDS_LOGIN
    finally:
        a.close()


def test_fetch_trends(tmp_path):
    a = make_adapter(tmp_path, **{"**://www.bilibili.com/v/**": FIXTURES / "bili_trends.html"})
    try:
        trends = a.fetch_trends()
        assert [t.title for t in trends] == ["AI Agent 进展盘点", "编程工具评测"]
        assert trends[0].heat == pytest.approx(289000.0)
    finally:
        a.close()


def test_compose_post_specs(tmp_path):
    a = make_adapter(tmp_path)
    post = a.compose_post(title="t" * 100, body="b" * 10, images=[])
    assert len(post.title) <= 80
    assert post.tags == ["B站专栏"]


def test_execute_publish_success(tmp_path):
    # 提交后注入成功 toast：patched fixture 写 tmp_path（不污染仓库 fixtures）
    html = (FIXTURES / "bili_publish.html").read_text(encoding="utf-8").replace(
        '<button class="submit-btn">发布专栏</button>',
        '<button class="submit-btn" onclick="'
        "document.body.insertAdjacentHTML('beforeend', "
        # JS 字符串用单引号界定；注入 HTML 的属性用 &quot; 实体（解码后不破坏外层属性）
        "'<div class=&quot;success-toast&quot; data-cv-id=&quot;cv3829104&quot;>成功</div>')"
        '">'
        '发布专栏</button>',
    )
    patched = tmp_path / "bili_publish_patched.html"
    patched.write_text(html, encoding="utf-8")
    a = make_adapter(tmp_path,
                     **{"**://member.bilibili.com/platform/upload-text/edit**": patched})
    try:
        post = a.compose_post("标题", "正文", [str(_make_png(tmp_path / "c.png"))])
        result = a.execute_publish(post)
        assert result.success and "cv3829104" in result.post_url
    finally:
        a.close()


def test_execute_publish_classifies_login_expired(tmp_path):
    a = make_adapter(tmp_path,
                     **{"**://member.bilibili.com/platform/upload-text/edit**": FIXTURES / "bili_home_logged_out.html"})
    try:
        post = a.compose_post("t", "b", [])
        result = a.execute_publish(post)
        assert not result.success
        assert result.error is PublishError.LOGIN_EXPIRED
    finally:
        a.close()


def test_execute_publish_classifies_selector_broken(tmp_path):
    a = make_adapter(tmp_path,
                     **{"**://member.bilibili.com/platform/upload-text/edit**": FIXTURES / "bili_home_logged_in.html"})
    try:
        post = a.compose_post("t", "b", [])
        result = a.execute_publish(post)
        assert not result.success
        assert result.error is PublishError.SELECTOR_BROKEN
    finally:
        a.close()


def test_check_health_broken_when_no_markers(tmp_path):
    blank = tmp_path / "blank.html"
    blank.write_text("<html><body><div>空白页</div></body></html>", encoding="utf-8")
    a = make_adapter(tmp_path, **{"**://member.bilibili.com/**": blank})
    try:
        assert a.check_health().status is HealthStatus.BROKEN
    finally:
        a.close()


def test_execute_publish_env_exception_bucket(tmp_path, monkeypatch):
    """环境类异常（非超时）→ SELECTOR_BROKEN 待维护语义（决策 #24）。"""
    import contextlib

    from playwright.sync_api import Error as PlaywrightError

    a = make_adapter(tmp_path)

    @contextlib.contextmanager
    def raising_ctx():
        raise PlaywrightError("Target page has been closed")
        yield  # pragma: no cover

    monkeypatch.setattr(type(a), "browser_page", lambda self: raising_ctx())
    post = a.compose_post("t", "b", [])
    result = a.execute_publish(post)
    assert not result.success
    assert result.error is PublishError.SELECTOR_BROKEN
    assert "环境异常" in result.detail
