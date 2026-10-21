"""小红书适配器。选择器契约见 tests/fixtures/xhs_*.html——真实页面漂移时先改 SELECTORS。"""
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .base import HealthReport, HealthStatus, PlatformPost, PublishError, PublishResult, Trend
from .browser import PlaywrightBase

HOME_URL = "https://creator.xiaohongshu.com"
TRENDS_URL = "https://www.xiaohongshu.com/hot"
PUBLISH_URL = "https://creator.xiaohongshu.com/publish/publish?source=official"

# ---- 选择器（fixture 契约；真实页面校准点）----
SEL_LOGIN_MARKER = ".login_container"
SEL_LOGGED_IN_MARKER = ".publish_entry"
SEL_TREND_ITEM = ".trend_item"
SEL_TREND_TITLE = ".title"
SEL_TREND_HEAT = ".heat"

# ---- 发布页选择器（fixture 契约；真实页面校准点）----
SEL_TAB_NOTE = ".tab_note"
SEL_UPLOAD_INPUT = ".upload_input"
SEL_TITLE_INPUT = ".title_input"
SEL_BODY_INPUT = ".body_input"
SEL_SUBMIT = ".submit_btn"
SEL_SUCCESS = ".publish_success"

TITLE_MAX = 20
BODY_MAX = 1000


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
                # 决策 #22②：超时后复查 URL/登录标记——迟到跳转窗口内应报 NEEDS_LOGIN 而非 BROKEN
                if "/login" in page.url or page.locator(SEL_LOGIN_MARKER).count() > 0:
                    return HealthReport(HealthStatus.NEEDS_LOGIN, "页面延迟跳转到登录态")
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
        trimmed_title = title.strip()[:TITLE_MAX]
        trimmed_body = body.strip()[:BODY_MAX]
        tags = ["AI", "自动化"]
        return PlatformPost(title=trimmed_title, body=trimmed_body, tags=tags, images=list(images))

    def execute_publish(self, post: PlatformPost) -> PublishResult:
        try:
            with self.browser_page() as page:
                try:
                    page.goto(PUBLISH_URL, wait_until="domcontentloaded")
                    if "/login" in page.url or page.locator(SEL_LOGIN_MARKER).count() > 0:
                        return PublishResult(success=False, error=PublishError.LOGIN_EXPIRED,
                                             detail="发布页处于未登录状态，请重新 login")
                    page.locator(SEL_TAB_NOTE).click()
                    if post.images:
                        page.locator(SEL_UPLOAD_INPUT).first.set_input_files(post.images)
                    page.locator(SEL_TITLE_INPUT).fill(post.title)
                    page.locator(SEL_BODY_INPUT).fill(post.body)
                    page.locator(SEL_SUBMIT).click()
                    page.locator(SEL_SUCCESS).first.wait_for(timeout=15000)
                    note_id = page.locator(SEL_SUCCESS).first.get_attribute("data-note-id") or ""
                    return PublishResult(success=True, post_url=f"https://www.xiaohongshu.com/explore/{note_id}")
                except PlaywrightTimeoutError:
                    # 决策 #22② 对称：超时后复查 URL/登录标记（page 尚未关闭）——迟到跳转报 LOGIN_EXPIRED
                    if "/login" in page.url or page.locator(SEL_LOGIN_MARKER).count() > 0:
                        return PublishResult(success=False, error=PublishError.LOGIN_EXPIRED,
                                             detail="发布过程中跳转到登录态")
                    return PublishResult(success=False, error=PublishError.SELECTOR_BROKEN,
                                         detail="发布页选择器超时——页面结构可能已改版，需校准 SELECTORS")
        except PlaywrightTimeoutError:  # goto 阶段超时（with 内未捕获的边界）
            return PublishResult(success=False, error=PublishError.SELECTOR_BROKEN,
                                 detail="发布页加载超时，需校准")
        except Exception as exc:  # 浏览器崩溃/断网等环境问题 → 待维护语义；真正的平台拒绝需校准期检测
            return PublishResult(success=False, error=PublishError.SELECTOR_BROKEN,
                                 detail=f"环境异常: {str(exc)[:200]}")
