from worker.adapters.base import HealthReport, HealthStatus, PlatformAdapter


class RealAdapter(PlatformAdapter):
    platform_id = "real"

    def check_health(self):
        return HealthReport(HealthStatus.OK)

    def fetch_trends(self):
        return []

    def compose_post(self, title, body, images):
        return None

    def execute_publish(self, post):
        return None
