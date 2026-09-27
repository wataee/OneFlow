import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import TaskStatus
from app.services.task_service import InvalidStateTransitionError, validate_transition


@pytest.mark.asyncio
async def test_task_lifecycle_and_review_flow(client: AsyncClient, seed_tenants: dict):
    headers = seed_tenants["headers_a"]

    # 1. Create a task that triggers human review (confidence below threshold)
    resp = await client.post(
        "/api/v1/tasks/",
        headers=headers,
        json={
            "type": "DOCUMENT_PROCESSING",
            "input_data": {"force_review": True, "invoice_total": 500000},
        },
    )
    assert resp.status_code == 202
    task = resp.json()
    task_id = task["id"]
    assert task["status"] == "PENDING"

    # 2. Run pipeline execution
    sync_resp = await client.post(f"/api/v1/tasks/{task_id}/execute-sync", headers=headers)
    assert sync_resp.status_code == 200
    processed_task = sync_resp.json()
    assert processed_task["status"] == "REVIEW"
    assert processed_task["confidence"] < 0.85

    # 3. Find created ReviewTask
    reviews_resp = await client.get("/api/v1/reviews/", headers=headers)
    assert reviews_resp.status_code == 200
    reviews = reviews_resp.json()["items"]
    matching_review = next(r for r in reviews if r["task_id"] == task_id)
    assert matching_review is not None
    review_id = matching_review["id"]
    assert matching_review["status"] == "PENDING"

    # 4. Human-in-the-loop: EDIT decision with custom human modification
    edited_payload = {"invoice_total": 500000, "human_verified": True, "tax_rate": 0.12}
    decision_resp = await client.post(
        f"/api/v1/reviews/{review_id}/decision",
        headers=headers,
        json={
            "decision": "edit",
            "edited_value": edited_payload,
        },
    )
    assert decision_resp.status_code == 200
    resolved_review = decision_resp.json()
    assert resolved_review["status"] == "RESOLVED"
    assert resolved_review["user_decision"] == "edit"

    # 5. Verify task is now COMPLETED with edited_payload
    task_after_review = await client.get(f"/api/v1/tasks/{task_id}", headers=headers)
    assert task_after_review.status_code == 200
    assert task_after_review.json()["status"] == "COMPLETED"
    assert task_after_review.json()["output_data"] == edited_payload

    # 6. Verify audit logs captured everything
    audit_resp = await client.get("/api/v1/audit/", headers=headers)
    assert audit_resp.status_code == 200
    actions = [a["action"] for a in audit_resp.json()["items"]]
    assert "TASK_CREATED" in actions
    assert "TASK_SENT_TO_REVIEW" in actions
    assert "REVIEW_EDITED" in actions


@pytest.mark.asyncio
async def test_fsm_invalid_transition():
    # Attempting to go COMPLETED -> PROCESSING directly must fail
    with pytest.raises(InvalidStateTransitionError):
        validate_transition(TaskStatus.COMPLETED, TaskStatus.PROCESSING)

    # Attempting PENDING -> COMPLETED directly must fail (must go through PROCESSING)
    with pytest.raises(InvalidStateTransitionError):
        validate_transition(TaskStatus.PENDING, TaskStatus.COMPLETED)


@pytest.mark.asyncio
async def test_audit_log_immutability(client: AsyncClient, db_session: AsyncSession, seed_tenants: dict):
    headers = seed_tenants["headers_a"]

    # Create task to generate an audit log entry
    await client.post(
        "/api/v1/tasks/",
        headers=headers,
        json={"type": "BANK_OPERATION", "input_data": {"test": 1}},
    )

    # Fetch audit log ID from DB
    res = await db_session.execute(text("SELECT id, action FROM audit_logs LIMIT 1"))
    row = res.first()
    assert row is not None
    audit_id, action = row

    # Attempt direct SQL UPDATE on audit_logs table -> MUST FAIL due to trigger
    with pytest.raises(Exception) as exc_update:
        await db_session.execute(
            text(f"UPDATE audit_logs SET action = 'HACKED' WHERE id = '{audit_id}'")
        )
    assert "immutable" in str(exc_update.value).lower()

    # Attempt direct SQL DELETE on audit_logs table -> MUST FAIL due to trigger
    with pytest.raises(Exception) as exc_delete:
        await db_session.execute(
            text(f"DELETE FROM audit_logs WHERE id = '{audit_id}'")
        )
    assert "immutable" in str(exc_delete.value).lower()
