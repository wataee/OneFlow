import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check_endpoint(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"
    assert data["demo_mode"] is True


@pytest.mark.asyncio
async def test_dashboard_aggregated_metrics(client: AsyncClient, seed_tenants: dict):
    headers = seed_tenants["headers_a"]

    # Create 2 tasks
    await client.post(
        "/api/v1/tasks/",
        headers=headers,
        json={"type": "DOCUMENT_PROCESSING", "input_data": {"test": 1}},
    )
    await client.post(
        "/api/v1/tasks/",
        headers=headers,
        json={"type": "BANK_OPERATION", "input_data": {"test": 2}},
    )

    metrics_resp = await client.get("/api/v1/dashboard/metrics", headers=headers)
    assert metrics_resp.status_code == 200
    metrics = metrics_resp.json()
    assert metrics["total_tasks"] >= 2
    # In eager Celery mode, tasks are immediately processed to either REVIEW or COMPLETED
    assert metrics["completed"] + metrics["in_review"] + metrics["pending"] >= 2
