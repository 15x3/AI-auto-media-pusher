import base64
import contextlib
from pathlib import Path

import pytest

from worker.adapters.base import HealthStatus, PlatformPost, PublishError
from worker.adapters.xiaohongshu import XiaohongshuAdapter

FIXTURES = Path(__file__).parent / "fixtures"


def make_adapter(tmp_path, **routes: Path) -> XiaohongshuAdapter:
    a = XiaohongshuAdapter(profiles_root=tmp_path / "profiles", headless=True)
    a.FIXTURE_ROUTES = dict(routes)
    return a


def _make_png(path: Path) -> Path:
    path.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    ))
    return path


def test_check_health_ok_when_logged_in(tmp_path):
    a = make_adapter(tmp_path, **{"**://creator.xiaohongshu.com/**": FIXTURES / "xhs_home_logged_in.html"})
    try:
        assert a.check_health().status is HealthStatus.OK
    finally:
        a.close()


def test_check_health_needs_login_when_login_marker_present(tmp_path):
    # 登录态判定双保险：URL 含 /login（真实重定向）或页面出现登录容器（fixture 契约）
    a = make_adapter(tmp_path, **{"**://creator.xiaohongshu.com/**": FIXTURES / "xhs_home_logged_out.html"})
    try:
        report = a.check_health()
        assert report.status is HealthStatus.NEEDS_LOGIN
    finally:
        a.close()


def test_fetch_trends_parses_titles_and_heat(tmp_path):
    a = make_adapter(tmp_path, **{"**://www.xiaohongshu.com/hot**": FIXTURES / "xhs_trends.html"})
    try:
        trends = a.fetch_trends()
        assert [t.title for t in trends] == ["AI Agent 一周动态", "桌面端工具极客界面", "多平台内容分发"]
        assert trends[0].heat == pytest.approx(9.1)
    finally:
        a.close()


def test_compose_post_enforces_platform_specs(tmp_path):
    a = make_adapter(tmp_path)
    post = a.compose_post(
        title="这个标题很长很长很长很长很长很长很长很长很长很长很长很长",
        body="正文" * 600,   # 1200 字 → 截到 1000
        images=[str(_make_png(tmp_path / "c.png"))],
    )
    assert len(post.title) <= 20
    assert len(post.body) <= 1000
    assert post.title.startswith("这个标题很长")
    assert post.images == [str(tmp_path / "c.png")]


def test_execute_publish_success_flow(tmp_path):
    # 提交后跳转到成功页：改写 fixture 注入 onclick 跳转
    html = (FIXTURES / "xhs_publish.html").read_text(encoding="utf-8").replace(
        '<button class="submit_btn">发布</button>',
        '<button class="submit_btn" onclick="location.href=\'https://creator.xiaohongshu.com/publish/success\'">发布</button>',
    )
    patched = tmp_path / "xhs_publish_patched.html"  # 写 tmp_path，不污染仓库 fixtures 目录
    patched.write_text(html, encoding="utf-8")

    # 路由按 LIFO 派发：publish/success 须后注册，才能优先于更宽的 publish** 模式命中
    a = make_adapter(tmp_path,
                     **{"**://creator.xiaohongshu.com/publish**": patched,
                        "**://creator.xiaohongshu.com/publish/success**": FIXTURES / "xhs_publish_success.html"})
    try:
        post = a.compose_post("标题", "正文", [str(_make_png(tmp_path / "c.png"))])
        result = a.execute_publish(post)
        assert result.success
        assert "note-6510f2ab" in result.post_url
    finally:
        a.close()


def test_execute_publish_classifies_login_expired(tmp_path):
    # 发布页落在未登录状态：路由到 logged_out fixture（登录容器可见）→ LOGIN_EXPIRED
    a = make_adapter(tmp_path,
                     **{"**://creator.xiaohongshu.com/publish**": FIXTURES / "xhs_home_logged_out.html"})
    try:
        post = a.compose_post("t", "b", [])
        result = a.execute_publish(post)
        assert not result.success
        assert result.error is PublishError.LOGIN_EXPIRED
    finally:
        a.close()


def test_execute_publish_classifies_selector_broken(tmp_path):
    a = make_adapter(tmp_path,
                     **{"**://creator.xiaohongshu.com/publish**": FIXTURES / "xhs_home_logged_in.html"})  # 页面没有表单
    try:
        post = a.compose_post("t", "b", [])
        result = a.execute_publish(post)
        assert not result.success
        assert result.error is PublishError.SELECTOR_BROKEN
    finally:
        a.close()


def test_check_health_broken_when_no_markers(tmp_path):
    """决策 #22 相关：无任何已知标记的页面 → BROKEN（校准期最先撞上的路径）。"""
    blank = tmp_path / "blank.html"
    blank.write_text("<html><body><div>空白页</div></body></html>", encoding="utf-8")
    a = make_adapter(tmp_path, **{"**://creator.xiaohongshu.com/**": blank})
    try:
        report = a.check_health()
        assert report.status is HealthStatus.BROKEN
    finally:
        a.close()


def test_execute_publish_platform_rejected_bucket_semantics(tmp_path, monkeypatch):
    """环境类异常（非超时，如浏览器崩溃/断网）→ SELECTOR_BROKEN 的待维护语义；
    PLATFORM_REJECTED 留给真实的平台内容拒绝（校准期接入检测，决策 #22）。"""
    from playwright.sync_api import Error as PlaywrightError

    a = make_adapter(tmp_path)

    @contextlib.contextmanager
    def crashed_browser():
        raise PlaywrightError("Target page has been closed")
        yield  # pragma: no cover

    monkeypatch.setattr(a, "browser_page", crashed_browser)  # 浏览器一启动即崩溃
    result = a.execute_publish(a.compose_post("t", "b", []))
    assert not result.success
    assert result.error is PublishError.SELECTOR_BROKEN
    assert "环境异常" in result.detail
