"""小红书适配器。选择器契约见 tests/fixtures/xhs_*.html——真实页面漂移时先改 SELECTORS。"""
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .base import HealthReport, HealthStatus, PlatformPost, PublishResult, Trend
from .browser import PlaywrightBase

HOME_URL = "https://creator.xiaohongshu.com"
TRENDS_URL = "https://www.xiaohongshu.com/hot"

# ---- 选择器（fixture 契约；真实页面校准点）----
SEL_LOGIN_MARKER = ".login_container"
SEL_LOGGED_IN_MARKER = ".publish_entry"
SEL_TREND_ITEM = ".trend_item"
SEL_TREND_TITLE = ".title"
SEL_TREND_HEAT = ".heat"


class XiaohongshuAdapter(PlaywrightBase):
    platform_id = "xiaohongshu"
    display_name = "小红书"
    LOGIN_URL = "https://creator.xiaohongshu.com/login"

    def check_health(self) -> HealthReport:
        with self.browser_page() as page:
            page.goto(HOME_URL, wait_until="domcontentloaded")
            # 登录态判定：URL 跳转（真实场景）或登录容器可见（fixture 契约）
            if "/login" in page.url or page.locator(SEL_LOGIN_MARKER).count() > 0:
                return HealthReport(HealthStatus.NEEDS_LOGIN, "处于未登录状态，需要扫码")
            try:
                page.locator(SEL_LOGGED_IN_MARKER).first.wait_for(timeout=5000)
                return HealthReport(HealthStatus.OK)
            except PlaywrightTimeoutError:
                return HealthReport(HealthStatus.BROKEN, "登录态页面结构不符（选择器待校准）")

    def fetch_trends(self) -> list[Trend]:
        with self.browser_page() as page:
            page.goto(TRENDS_URL, wait_until="domcontentloaded")
            items = page.locator(SEL_TREND_ITEM).all()
            trends = []
            for item in items:
                title = item.locator(SEL_TREND_TITLE).inner_text().strip()
                heat_text = item.locator(SEL_TREND_HEAT).inner_text().strip()
                try:
                    heat = float(heat_text)
                except ValueError:
                    heat = 0.0
                trends.append(Trend(title=title, heat=heat))
            return trends

    def compose_post(self, title: str, body: str, images: list[str]) -> PlatformPost:
        raise NotImplementedError("Task 7 实现")

    def execute_publish(self, post) -> PublishResult:
        raise NotImplementedError("Task 7 实现")
