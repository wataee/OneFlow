import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.domain_repos import TaskRepository


@pytest.mark.asyncio
async def test_multi_tenancy_isolation(client: AsyncClient, db_session: AsyncSession, seed_tenants: dict):
    headers_a = seed_tenants["headers_a"]
    headers_b = seed_tenants["headers_b"]
    org_a = seed_tenants["org_a"]
    org_b = seed_tenants["org_b"]

    # 1. Tenant A creates a task
    create_resp = await client.post(
        "/api/v1/tasks/",
        headers=headers_a,
        json={
            "type": "DOCUMENT_PROCESSING",
            "input_data": {"confidential_invoice_id": "ORG_A_SECRET_DOC_999"},
        },
    )
    assert create_resp.status_code == 202
    task_a_data = create_resp.json()
    task_a_id = task_a_data["id"]

    # 2. Tenant A lists tasks -> sees task_a_id
    list_a_resp = await client.get("/api/v1/tasks/", headers=headers_a)
    assert list_a_resp.status_code == 200
    ids_in_a = [t["id"] for t in list_a_resp.json()["items"]]
    assert task_a_id in ids_in_a

    # 3. Tenant B lists tasks -> MUST NOT SEE task_a_id
    list_b_resp = await client.get("/api/v1/tasks/", headers=headers_b)
    assert list_b_resp.status_code == 200
    ids_in_b = [t["id"] for t in list_b_resp.json()["items"]]
    assert task_a_id not in ids_in_b

    # 4. Tenant B attempts direct access by ID -> MUST return 404 Not Found (not 200)
    direct_get_resp = await client.get(f"/api/v1/tasks/{task_a_id}", headers=headers_b)
    assert direct_get_resp.status_code == 404

    # 5. Direct Repository enforcement verification
    repo_b = TaskRepository(db_session, org_b.id)
    retrieved = await repo_b.get_by_id(task_a_id)
    assert retrieved is None, "Repository layer failed to enforce multi-tenant isolation!"
