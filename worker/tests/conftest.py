"""测试公共夹具。

_thread_playwright 的线程内单例在两次调用之间保持线程的 running-loop 标记
（playwright sync greenlet 机制）——不停止的话，先跑浏览器测试会让主线程
带着"伪运行"标记，后续 pytest-asyncio 测试触发 "Runner.run() cannot be
called from a running event loop"。每个测试后停掉当前线程的实例并清标记。
"""
import pytest

from worker.adapters import browser


@pytest.fixture(autouse=True)
def _reset_thread_playwright():
    yield
    pw = getattr(browser._tls, "pw", None)
    if pw is not None:
        browser._stop_quietly(pw)
        browser._tls.pw = None
