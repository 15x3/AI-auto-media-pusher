"""Playwright 浏览器适配器公共基类：持久化用户数据目录（会话保持）、fixture 路由钩子、扫码登录。

不声明 platform_id —— 自动扫描只收终端适配器（计划 1 决策 #2）。
FIXTURE_ROUTES 为空时直连真实平台；测试注入 {url模式: 本地HTML} 后全链路离线可测。
选择器契约：终端适配器的选择器以 fixture 页为唯一测试契约，真实页面漂移由
PublishError.SELECTOR_BROKEN 分类捕获后校准（见各适配器 SELECTORS 常量注释）。
使用约定：FIXTURE_ROUTES 只允许整体赋值（实例属性覆盖类属性）；context 建立后修改不生效（需 close 重开）；
本基类为单线程使用设计（sync Playwright API 线程亲和）：playwright 实例按线程单例共享
（见 _thread_playwright），多线程并发使用由 service 层单线程执行器保证不发生。
"""
import atexit
import threading
import time
from contextlib import contextmanager, suppress
from pathlib import Path

from .base import HealthReport, HealthStatus, PlatformAdapter

LOGIN_TIMEOUT_SECONDS = 180

_tls = threading.local()


def _thread_playwright():
    """当前线程的 playwright 实例（惰性单例）。

    同线程第二次 sync_playwright().start() 必抛 "Sync API inside the asyncio
    loop"——sync API 的 greenlet 机制在两次调用之间保持线程的 running-loop
    标记；而一个实例跨线程使用又违反 greenlet 线程绑定。因此按线程单例：
    同线程全部适配器共用，跨线程各自持有。进程退出时经 atexit 统一停止。
    """
    pw = getattr(_tls, "pw", None)
    if pw is None:
        from playwright.sync_api import sync_playwright

        pw = sync_playwright().start()
        _tls.pw = pw
        atexit.register(lambda: _stop_quietly(pw))
    return pw


def _stop_quietly(pw) -> None:
    with suppress(Exception):
        pw.stop()


def _make_fixture_handler(fixture: Path):
    """构造 fixture 路由处理器：Playwright 以 (route, request) 两个位置参数调用处理器，
    fixture 路径须经闭包捕获（不能占处理器形参位，否则被 request 覆盖）。"""

    def handler(route, request=None):
        route.fulfill(
            status=200, content_type="text/html; charset=utf-8",
            body=Path(fixture).read_text(encoding="utf-8"),
        )

    return handler


class PlaywrightBase(PlatformAdapter):
    LOGIN_URL: str = ""
    FIXTURE_ROUTES: dict[str, Path] = {}

    def __init__(self, profiles_root: Path | None = None, headless: bool = False) -> None:
        self._profiles_root = Path(profiles_root) if profiles_root else Path("data/profiles")
        self._headless = headless
        self._context = None

    @property
    def _profile_dir(self) -> Path:
        return self._profiles_root / self.platform_id

    @contextmanager
    def browser_page(self):
        if self._context is None:
            pw = _thread_playwright()
            self._context = pw.chromium.launch_persistent_context(
                user_data_dir=str(self._profile_dir),
                headless=self._headless,
                viewport={"width": 1280, "height": 860},
            )
            for pattern, fixture in self.FIXTURE_ROUTES.items():
                self._context.route(pattern, _make_fixture_handler(Path(fixture)))
        page = self._context.new_page()
        page.set_default_timeout(10000)              # 动作超时 10s（真实 React 水合留余量）
        page.set_default_navigation_timeout(30000)   # 导航超时 30s（慢网络 goto 不误判）
        try:
            yield page
        finally:
            with suppress(Exception):
                page.close()

    def login(self) -> HealthReport:
        """打开登录页，人工扫码/输入，轮询 check_health 直到 OK 或超时。"""
        with self.browser_page() as page:
            page.goto(self.LOGIN_URL, wait_until="domcontentloaded")
            deadline = time.time() + LOGIN_TIMEOUT_SECONDS
            while time.time() < deadline:
                try:
                    healthy = self.check_health().status is HealthStatus.OK
                except Exception:  # noqa: BLE001 - 网络抖动/导航瞬时错误不打断 180 秒扫码等待
                    healthy = False
                if healthy:
                    return HealthReport(HealthStatus.OK, "登录成功")
                page.wait_for_timeout(3000)
        return HealthReport(HealthStatus.NEEDS_LOGIN, f"{LOGIN_TIMEOUT_SECONDS} 秒内未完成登录")

    def close(self) -> None:
        # 只关 context；playwright 实例归线程单例所有（跨适配器共享），由 atexit 统一停止
        if self._context is not None:
            try:
                self._context.close()
            finally:
                self._context = None
