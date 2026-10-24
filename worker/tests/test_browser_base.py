import threading
from pathlib import Path

from worker.adapters import browser
from worker.adapters.browser import PlaywrightBase

FIXTURES = Path(__file__).parent / "fixtures"


def _local_page_adapter(routes: dict[str, Path]):
    """构造只挂 fixture 路由的测试基类实例（不声明 platform_id，不经注册表）。"""

    class _Local(PlaywrightBase):
        platform_id = "local-test"   # 仅测试用；不会被自动扫描（不在 worker.adapters 包内）

        def check_health(self):
            raise NotImplementedError

        def fetch_trends(self):
            raise NotImplementedError

        def compose_post(self, title, body, images):
            raise NotImplementedError

        def execute_publish(self, post):
            raise NotImplementedError

    a = _Local(profiles_root=Path(__file__).parent / "tmp_profiles", headless=True)
    a.FIXTURE_ROUTES = routes
    return a


def test_fixture_route_serves_local_html(tmp_path):
    (tmp_path / "page.html").write_text("<h1 class='marker'>本地页面</h1>", encoding="utf-8")
    a = _local_page_adapter({"**://fake.local/**": tmp_path / "page.html"})
    try:
        with a.browser_page() as page:
            page.goto("https://fake.local/anything", wait_until="domcontentloaded")
            assert page.locator(".marker").inner_text() == "本地页面"
    finally:
        a.close()


def test_persistent_profile_reused_across_pages(tmp_path):
    cookie_value = "session-marker-42"
    (tmp_path / "page.html").write_text("<h1>ok</h1>", encoding="utf-8")
    a = _local_page_adapter({"**://fake.local/**": tmp_path / "page.html"})
    try:
        with a.browser_page() as page:
            page.goto("https://fake.local/", wait_until="domcontentloaded")
            page.context.add_cookies([{"name": "sid", "value": cookie_value, "url": "https://fake.local"}])
        with a.browser_page() as page:   # 新 page，同一持久化上下文
            cookies = {c["name"]: c["value"] for c in page.context.cookies("https://fake.local")}
            assert cookies["sid"] == cookie_value
    finally:
        a.close()


def test_playwright_instance_shared_per_thread(monkeypatch, tmp_path):
    """同线程的多个适配器必须共用一个 playwright 实例（按线程单例）。

    playwright sync 在两次同步调用之间保持线程的 running-loop 标记——
    同线程第二次 sync_playwright().start() 必抛 "Sync API inside the
    asyncio loop"（serve 场景实测：health(bilibili) 后线程归还池，
    health(xiaohongshu) 复用该线程启动第二实例即触发）。
    """
    starts = []

    class FakePage:
        def set_default_timeout(self, ms): ...
        def set_default_navigation_timeout(self, ms): ...
        def close(self): ...

    class FakeContext:
        def route(self, pattern, handler): ...
        def new_page(self):
            return FakePage()
        def close(self): ...

    class FakePw:
        chromium = type("Chromium", (), {"launch_persistent_context": staticmethod(lambda **kw: FakeContext())})()

        def stop(self): ...

    def fake_sync_playwright():
        class _Cm:
            def start(self):
                starts.append(threading.get_ident())
                return FakePw()

        return _Cm()

    monkeypatch.setattr("playwright.sync_api.sync_playwright", fake_sync_playwright)
    # 隔离线程内单例状态：换掉整个 thread-local，测试结束自动还原
    # raising=False：修复前模块尚无 _tls，测试仍应因「二次 start」断言而红
    monkeypatch.setattr(browser, "_tls", threading.local(), raising=False)

    a1 = _local_page_adapter({})
    a2 = _local_page_adapter({})
    try:
        with a1.browser_page():
            pass
        with a2.browser_page():
            pass
    finally:
        a1.close()
        a2.close()

    assert starts, "sync_playwright 未被调用——browser_page 未走到启动分支"
    assert len(starts) == 1, f"同线程第二个适配器再次 start()（{len(starts)} 次）——必抛 Sync API inside asyncio loop"
