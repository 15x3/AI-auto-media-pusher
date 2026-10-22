from worker.adapters.base import HealthReport, HealthStatus, PlatformAdapter, PlatformPost, PublishResult, Trend


class FineAdapter(PlatformAdapter):
    platform_id = "fine"
    display_name = "正常适配器"

    def check_health(self):
        return HealthReport(HealthStatus.OK)

    def fetch_trends(self):
        return []

    def compose_post(self, title, body, images):
        return PlatformPost(title=title, body=body)

    def execute_publish(self, post):
        return PublishResult(success=True)
