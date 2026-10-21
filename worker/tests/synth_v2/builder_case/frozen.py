from worker.adapters.base import HealthReport, HealthStatus, PlatformAdapter, PlatformPost, PublishResult, Trend


class FrozenAdapter(PlatformAdapter):
    platform_id = "frozen"
    display_name = "注入适配器"

    def __init__(self, deps=None):
        self.deps = deps

    def check_health(self):
        return HealthReport(HealthStatus.OK)

    def fetch_trends(self):
        return [Trend("t", 1.0)]

    def compose_post(self, title, body, images):
        return PlatformPost(title=title, body=body)

    def execute_publish(self, post):
        return PublishResult(success=True)
