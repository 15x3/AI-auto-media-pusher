from pathlib import Path

import pytest

from worker.adapters.base import HealthStatus
from worker.adapters.xiaohongshu import XiaohongshuAdapter

FIXTURES = Path(__file__).parent / "fixtures"


def make_adapter(tmp_path, **routes: Path) -> XiaohongshuAdapter:
    a = XiaohongshuAdapter(profiles_root=tmp_path / "profiles", headless=True)
    a.FIXTURE_ROUTES = dict(routes)
    return a


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
