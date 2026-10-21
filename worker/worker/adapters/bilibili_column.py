"""B站专栏适配器。选择器契约见 tests/fixtures/bili_*.html——真实页面漂移时先改 SELECTORS。"""
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .base import (
    HealthReport,
    HealthStatus,
    PlatformPost,
    PublishError,
    PublishResult,
    Trend,
)
from .browser import PlaywrightBase

HOME_URL = "https://member.bilibili.com/platform/home"
TRENDS_URL = "https://www.bilibili.com/v/popular/rank/all"
PUBLISH_URL = "https://member.bilibili.com/platform/upload-text/edit"

# ---- 选择器（fixture 契约；真实页面校准点）----
SEL_LOGIN_MARKER = ".bili-mini-login"
SEL_LOGGED_IN_MARKER = ".create-entry"
SEL_TREND_ITEM = ".hot-rank-item"
SEL_TREND_TITLE = ".rank-title"
SEL_TREND_HEAT = ".rank-score"
SEL_COVER_UPLOAD = ".cover-upload"
SEL_TITLE_INPUT = ".title-input"
SEL_CONTENT_INPUT = ".content-input"
SEL_SUBMIT = ".submit-btn"
SEL_SUCCESS = ".success-toast"

TITLE_MAX = 80


class BilibiliColumnAdapter(PlaywrightBase):
    platform_id = "bilibili_column"
    display_name = "B站专栏"
    LOGIN_URL = "https://passport.bilibili.com/login"

    def check_health(self) -> HealthReport:
        with self.browser_page() as page:
            page.goto(HOME_URL, wait_until="domcontentloaded")
            if "passport.bilibili.com" in page.url or page.locator(SEL_LOGIN_MARKER).count() > 0:
                return HealthReport(HealthStatus.NEEDS_LOGIN, "处于未登录状态")
            try:
                page.locator(SEL_LOGGED_IN_MARKER).first.wait_for(timeout=5000)
                return HealthReport(HealthStatus.OK)
            except PlaywrightTimeoutError:
                # 决策 #22②：迟到跳转窗口复查
                if "passport.bilibili.com" in page.url or page.locator(SEL_LOGIN_MARKER).count() > 0:
                    return HealthReport(HealthStatus.NEEDS_LOGIN, "页面延迟跳转到登录态")
                return HealthReport(HealthStatus.BROKEN, "创作中心页面结构不符（选择器待校准）")

    def fetch_trends(self) -> list[Trend]:
        with self.browser_page() as page:
            page.goto(TRENDS_URL, wait_until="domcontentloaded")
            trends = []
            for item in page.locator(SEL_TREND_ITEM).all():
                title = item.locator(SEL_TREND_TITLE).inner_text().strip()
                try:
                    heat = float(item.locator(SEL_TREND_HEAT).inner_text().strip().replace(",", ""))
                except ValueError:
                    heat = 0.0
                trends.append(Trend(title=title, heat=heat))
            return trends

    def compose_post(self, title: str, body: str, images: list[str]) -> PlatformPost:
        return PlatformPost(
            title=title.strip()[:TITLE_MAX],
            body=body.strip(),
            tags=["B站专栏"],
            images=list(images),
        )

    def execute_publish(self, post: PlatformPost) -> PublishResult:
        try:
            with self.browser_page() as page:
                try:
                    page.goto(PUBLISH_URL, wait_until="domcontentloaded")
                    if "passport.bilibili.com" in page.url or page.locator(SEL_LOGIN_MARKER).count() > 0:
                        return PublishResult(success=False, error=PublishError.LOGIN_EXPIRED,
                                             detail="发布页处于未登录状态，请重新 login")
                    if post.images:
                        page.locator(SEL_COVER_UPLOAD).first.set_input_files(post.images[0])
                    page.locator(SEL_TITLE_INPUT).fill(post.title)
                    page.locator(SEL_CONTENT_INPUT).fill(post.body)
                    page.locator(SEL_SUBMIT).click()
                    page.locator(SEL_SUCCESS).first.wait_for(timeout=15000)
                    cv_id = page.locator(SEL_SUCCESS).first.get_attribute("data-cv-id") or ""
                    return PublishResult(success=True, post_url=f"https://www.bilibili.com/read/{cv_id}")
                except PlaywrightTimeoutError:
                    if "passport.bilibili.com" in page.url or page.locator(SEL_LOGIN_MARKER).count() > 0:
                        return PublishResult(success=False, error=PublishError.LOGIN_EXPIRED,
                                             detail="发布过程中跳转到登录态")
                    return PublishResult(success=False, error=PublishError.SELECTOR_BROKEN,
                                         detail="专栏编辑器选择器超时——页面结构可能已改版，需校准 SELECTORS")
        except PlaywrightTimeoutError:  # browser_page 启动/路由注册超时（goto 在内层已捕获）
            return PublishResult(success=False, error=PublishError.SELECTOR_BROKEN,
                                 detail="编辑器加载超时，需校准")
        except Exception as exc:  # 浏览器崩溃/断网等环境问题（决策 #24）
            return PublishResult(success=False, error=PublishError.SELECTOR_BROKEN,
                                 detail=f"环境异常: {str(exc)[:200]}")
