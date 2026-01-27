import os

from locust import HttpUser, TaskSet, between, task


class AuthTask(TaskSet):
    @task(1)
    def auth_telegram(self) -> None:
        init_data = os.getenv("LOCUST_INIT_DATA", "")
        if not init_data:
            return
        response = self.client.post(
            "/api/v1/auth/telegram",
            json={"init_data": init_data},
            name="/api/v1/auth/telegram",
        )
        if response.status_code == 200:
            payload = response.json()
            self.user.access_token = payload.get("access_token")


class CreateCampaignTask(TaskSet):
    @task(1)
    def create_campaign(self) -> None:
        if not self.user.access_token:
            return
        project_id = os.getenv("LOCUST_PROJECT_ID")
        if not project_id:
            return
        payload = {
            "project_id": int(project_id),
            "name": "Locust Campaign",
            "source_id": int(os.getenv("LOCUST_SOURCE_ID", "0")) or None,
            "target_id": int(os.getenv("LOCUST_TARGET_ID", "0")) or None,
            "max_invites_per_hour": 1,
            "max_invites_per_day": 5,
        }
        self.client.post(
            "/api/v1/campaigns",
            headers=self.user.auth_headers(),
            json=payload,
            name="/api/v1/campaigns",
        )


class StartCampaignTask(TaskSet):
    @task(2)
    def start_campaign(self) -> None:
        campaign_id = os.getenv("LOCUST_CAMPAIGN_ID")
        if not campaign_id or not self.user.access_token:
            return
        self.client.post(
            f"/api/v1/campaigns/{campaign_id}/start",
            headers=self.user.auth_headers(),
            name="/api/v1/campaigns/{id}/start",
        )


class AdminStatsTask(TaskSet):
    @task(1)
    def admin_stats(self) -> None:
        admin_token = os.getenv("LOCUST_ADMIN_TOKEN")
        if not admin_token:
            return
        self.client.get(
            "/api/v1/admin/stats",
            headers={"Authorization": f"Bearer {admin_token}"},
            name="/api/v1/admin/stats",
        )


class ApiUser(HttpUser):
    wait_time = between(1, 3)
    tasks = [AuthTask, CreateCampaignTask, StartCampaignTask, AdminStatsTask]
    access_token: str | None = None

    def auth_headers(self) -> dict[str, str]:
        if not self.access_token:
            return {}
        return {"Authorization": f"Bearer {self.access_token}"}
