from worker.adapters.base import HealthReport, HealthStatus, PlatformAdapter


class SharedBase(PlatformAdapter):
    """共享中间具体类：四方法齐全但未声明 platform_id，扫描器应跳过而非炸掉。"""

    def check_health(self):
        return HealthReport(HealthStatus.OK)

    def fetch_trends(self):
        return []

    def compose_post(self, title, body, images):
        return None

    def execute_publish(self, post):
        return None
