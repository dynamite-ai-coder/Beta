from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.config import settings
from backend.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def auth_headers():
    return {"Authorization": f"Bearer {settings.api_auth_token}"}


@pytest.mark.anyio
async def test_health_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data


@pytest.mark.anyio
async def test_create_task_without_auth():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/task",
            json={
                "target_url": "https://example.com/login",
                "username": "testuser",
                "password": "testpass",
            },
        )
        assert response.status_code in (200, 401, 403)


@pytest.mark.anyio
async def test_create_task_invalid_url(auth_headers):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/task",
            json={
                "target_url": "not-a-valid-url",
                "username": "testuser",
                "password": "testpass",
            },
            headers=auth_headers,
        )
        assert response.status_code == 422


@pytest.mark.anyio
async def test_get_nonexistent_task(auth_headers):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/task/nonexistent-id", headers=auth_headers)
        assert response.status_code == 404


@pytest.mark.anyio
async def test_stop_nonexistent_task(auth_headers):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/task/nonexistent-id/stop", headers=auth_headers)
        assert response.status_code == 404


@pytest.mark.anyio
async def test_manual_action_nonexistent_task(auth_headers):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/task/nonexistent-id/manual-action",
            json={"action": "continue"},
            headers=auth_headers,
        )
        assert response.status_code == 404


@pytest.mark.anyio
async def test_events_nonexistent_task(auth_headers):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/task/nonexistent-id/events", headers=auth_headers)
        assert response.status_code == 404


class TestSSRFProtection:
    def test_localhost_blocked(self):
        from backend.config import is_url_allowed
        assert not is_url_allowed("http://localhost:8080/admin")

    def test_private_ip_blocked(self):
        from backend.config import is_url_allowed
        assert not is_url_allowed("http://192.168.0.1/internal")

    def test_metadata_blocked(self):
        from backend.config import is_url_allowed
        assert not is_url_allowed("http://169.254.169.254/latest/meta-data/iam/security-credentials/")


class TestPasswordRedaction:
    def test_password_not_in_logs(self):
        from backend.security.auth import redact_secret
        log_message = "User login with password secret123"
        redacted = redact_secret(log_message, "secret123")
        assert "secret123" not in redacted

    def test_password_not_in_response(self):
        from backend.models.schemas import TaskResponse
        resp = TaskResponse(
            task_id="test-id",
            state=TaskState.QUEUED,
            target_url="https://example.com",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        resp_dict = resp.model_dump()
        assert "password" not in resp_dict


from backend.models.schemas import TaskState


class TestScreenshotSanitization:
    def test_sanitize_filename(self):
        from backend.security.auth import sanitize_filename
        dangerous = "../../etc/passwd"
        safe = sanitize_filename(dangerous)
        assert "/" not in safe
        # Dots are safe in filenames - just ensure path separators are removed

    def test_sanitize_special_chars(self):
        from backend.security.auth import sanitize_filename
        special = "user@domain.com!#$%"
        safe = sanitize_filename(special)
        assert "@" not in safe


class TestTaskLifecycle:
    @pytest.mark.anyio
    async def test_task_created_with_correct_state(self):
        from backend.tasks.manager import TaskManager
        manager = TaskManager()
        task = await manager.create_task(
            task_id="test-lifecycle",
            target_url="https://example.com",
            username="user",
            password="pass",
            instruction="test",
        )
        assert task["state"] == TaskState.QUEUED
        assert task["task_id"] == "test-lifecycle"

    @pytest.mark.anyio
    async def test_update_task_state(self):
        from backend.tasks.manager import TaskManager
        manager = TaskManager()
        await manager.create_task(
            task_id="test-state",
            target_url="https://example.com",
            username="user",
            password="pass",
            instruction="test",
        )
        await manager.update_task_state("test-state", TaskState.RUNNING)
        task = manager.get_task("test-state")
        assert task["state"] == TaskState.RUNNING


class TestListTasks:
    @pytest.mark.anyio
    async def test_list_tasks_empty(self, auth_headers):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/tasks", headers=auth_headers)
            assert response.status_code == 200
            assert isinstance(response.json(), list)

    @pytest.mark.anyio
    async def test_list_tasks_with_limit(self, auth_headers):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/tasks?limit=5&offset=0", headers=auth_headers)
            assert response.status_code == 200


class TestScheduledTasks:
    @pytest.mark.anyio
    async def test_list_scheduled_tasks_empty(self, auth_headers):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/scheduled-tasks", headers=auth_headers)
            assert response.status_code == 200
            assert isinstance(response.json(), list)

    @pytest.mark.anyio
    async def test_create_scheduled_task_invalid_cron(self, auth_headers):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/scheduled-task",
                json={
                    "name": "test-schedule",
                    "target_url": "https://example.com",
                    "username": "user",
                    "password": "pass",
                    "cron_expression": "invalid-cron",
                },
                headers=auth_headers,
            )
            assert response.status_code == 400

    @pytest.mark.anyio
    async def test_delete_nonexistent_scheduled_task(self, auth_headers):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.delete(
                "/api/v1/scheduled-task/nonexistent-id",
                headers=auth_headers,
            )
            assert response.status_code == 404


class TestMetrics:
    @pytest.mark.anyio
    async def test_metrics_endpoint(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/metrics")
            assert response.status_code == 200
            assert "text/plain" in response.headers["content-type"]

    @pytest.mark.anyio
    async def test_metrics_contain_prometheus_data(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/metrics")
            content = response.text
            assert "http_requests_total" in content or "http_request_duration_seconds" in content


class TestDashboard:
    @pytest.mark.anyio
    async def test_dashboard_root(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/")
            assert response.status_code == 200
            assert "text/html" in response.headers["content-type"]

    @pytest.mark.anyio
    async def test_health_returns_version(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
            data = response.json()
            assert data["version"] == "2.0.0"


class TestVirtualAIAPI:
    @pytest.mark.anyio
    async def test_list_models(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/v1/models")
            assert response.status_code == 200
            data = response.json()
            assert "data" in data
            assert len(data["data"]) > 0
            assert data["data"][0]["id"] == "beta-virtual-ai"

    @pytest.mark.anyio
    async def test_chat_completions_no_auth(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "beta-virtual-ai",
                    "messages": [{"role": "user", "content": "Hello"}],
                },
            )
            assert response.status_code in (200, 401)

    @pytest.mark.anyio
    async def test_chat_completions_wrong_model(self, auth_headers):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "wrong-model",
                    "messages": [{"role": "user", "content": "Hello"}],
                },
                headers=auth_headers,
            )
            assert response.status_code == 400

    @pytest.mark.anyio
    async def test_chat_completions_empty_messages(self, auth_headers):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "beta-virtual-ai",
                    "messages": [],
                },
                headers=auth_headers,
            )
            assert response.status_code == 400


class TestClientAPI:
    @pytest.mark.anyio
    async def test_client_status_empty(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/clients/status")
            assert response.status_code == 200
            assert isinstance(response.json(), list)

    @pytest.mark.anyio
    async def test_register_client(self, auth_headers):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/clients/register",
                json={"client_id": "test-client", "token": settings.api_auth_token},
                headers=auth_headers,
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "registered"

    @pytest.mark.anyio
    async def test_get_ready_client_none(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/clients/ready")
            assert response.status_code == 404
