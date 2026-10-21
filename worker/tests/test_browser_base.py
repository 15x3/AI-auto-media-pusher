from pathlib import Path

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
