"""本地演示适配器：把发布写入 JSON 文件，用于契约测试与离线开发。"""
import json
from pathlib import Path

from .base import (
    HealthReport,
    HealthStatus,
    PlatformAdapter,
    PlatformPost,
    PublishResult,
    Trend,
)


class DemoAdapter(PlatformAdapter):
    platform_id = "demo"
    display_name = "本地演示平台"

    def __init__(self, out_file: Path | None = None) -> None:
        self._out = Path(out_file) if out_file else Path("demo_published.json")

    def check_health(self) -> HealthReport:
        return HealthReport(HealthStatus.OK, "演示平台永远在线")

    def fetch_trends(self) -> list[Trend]:
        return [
            Trend("AI Agent 一周动态", heat=9.1),
            Trend("桌面端工具的极客界面", heat=8.4),
            Trend("多平台内容分发实践", heat=7.6),
        ]

    def compose_post(self, title: str, body: str, images: list[str]) -> PlatformPost:
        return PlatformPost(title=f"[demo] {title}", body=body, tags=["AI", "自动化"], images=images)

    def execute_publish(self, post: PlatformPost) -> PublishResult:
        data = json.loads(self._out.read_text(encoding="utf-8")) if self._out.exists() else []
        data.append({"title": post.title, "tags": post.tags})
        self._out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return PublishResult(success=True, post_url=f"demo://posts/{len(data)}")
