import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.onec.output_filter import OneCOutputFilter, mask_sensitive_string
from app.integrations.onec.policy import (
    OneCPolicyEnforcer,
    PolicyViolationError,
    RiskLevel,
)
from app.services.onec_service import OneCService


def test_risk_level_policy_enforcement():
    # 1. Enforcer with max risk ANALYTICS_READ and read-only mode ON
    enforcer = OneCPolicyEnforcer(
        global_read_only=True,
        max_allowed_risk=RiskLevel.ANALYTICS_READ,
        is_tenant_writable=False,
    )

    # L0: SAFE_READ -> Allowed
    dec_safe = enforcer.evaluate("read.system.health_check", RiskLevel.SAFE_READ)
    assert dec_safe.allowed is True

    # L1: ANALYTICS_READ -> Allowed
    dec_analytics = enforcer.evaluate("read.analytics.get_debtors", RiskLevel.ANALYTICS_READ)
    assert dec_analytics.allowed is True

    # L2: SENSITIVE_READ -> Exceeds max allowed ceiling (ANALYTICS_READ) -> Blocked
    dec_sensitive = enforcer.evaluate("read.payroll.get_salaries", RiskLevel.SENSITIVE_READ)
    assert dec_sensitive.allowed is False
    assert "exceeds maximum allowed risk level" in dec_sensitive.reason

    # L3: WRITE_DRAFT -> Blocked by global read-only mode
    dec_write = enforcer.evaluate("write.documents.create_draft", RiskLevel.WRITE_DRAFT)
    assert dec_write.allowed is False
    assert "READ_ONLY_MODE=true" in dec_write.reason

    # Forbidden operation denylist -> Always unconditionally blocked
    dec_forbidden = enforcer.evaluate("raw_odata_query", RiskLevel.SAFE_READ)
    assert dec_forbidden.allowed is False
    assert "denylist" in dec_forbidden.reason

    with pytest.raises(PolicyViolationError):
        enforcer.verify_or_raise("raw_odata_query", RiskLevel.SAFE_READ)


def test_output_filter_sensitive_masking_and_row_limiting():
    filter_service = OneCOutputFilter(default_max_rows=2)

    # 1. Kazakhstani BIN / IIN masking
    text_sample = "Контрагент ТОО Базис с БИН 981240001122 и счетом KZ120000000000123456"
    masked = mask_sensitive_string(text_sample)
    assert "981240001122" not in masked
    assert "9812******22" in masked
    assert "KZ120000000000123456" not in masked
    assert "KZ12************3456" in masked

    # 2. Row limiting
    items = [
        {"id": 1, "name": "Item 1", "bin": "050140001122"},
        {"id": 2, "name": "Item 2", "bin": "060240002233"},
        {"id": 3, "name": "Item 3", "bin": "070340003344"},
        {"id": 4, "name": "Item 4", "bin": "080440004455"},
    ]
    sanitized, is_truncated = filter_service.filter_result(items, max_rows=2)
    assert len(sanitized) == 2
    assert is_truncated is True
    # Verify nested masking
    assert sanitized[0]["bin"] == "0501******22"


@pytest.mark.asyncio
async def test_onec_operations_end_to_end_flow(db_session: AsyncSession, seed_tenants: dict):
    org_a_id = seed_tenants["org_a"].id
    user_a_id = seed_tenants["user_a"].id

    service = OneCService(db_session, org_a_id)

    # 1. Execute health check
    res_health = await service.check_health(user_id=user_a_id)
    assert res_health["operation"] == "read.system.health_check"
    assert res_health["risk_level"] == "SAFE_READ"
    assert res_health["data"]["status"] == "connected"

    # 2. Execute debtors analysis
    res_debtors = await service.get_debtors(min_debt=1000.0, limit=10, user_id=user_a_id)
    assert res_debtors["operation"] == "read.analytics.get_debtors"
    assert res_debtors["risk_level"] == "ANALYTICS_READ"
    assert len(res_debtors["data"]) > 0
    # Ensure BIN was masked by output filter before returning
    first_debtor = res_debtors["data"][0]
    assert "981240001122" not in first_debtor["bin"]
    assert "******" in first_debtor["bin"]

    # 3. Verify audit log entry was written to DB
    audit_res = await db_session.execute(
        text("SELECT action, entity_type, entity_id, new_values FROM audit_logs WHERE action = 'ONEC_OPERATION_EXECUTED'")
    )
    audit_rows = audit_res.fetchall()
    assert len(audit_rows) >= 2
    actions = [row[2] for row in audit_rows]
    assert "read.system.health_check" in actions
    assert "read.analytics.get_debtors" in actions


@pytest.mark.asyncio
async def test_onec_api_endpoints(client: AsyncClient, seed_tenants: dict):
    headers = seed_tenants["headers_a"]

    # Health endpoint
    resp_health = await client.get("/api/v1/onec/health", headers=headers)
    assert resp_health.status_code == 200
    assert resp_health.json()["operation"] == "read.system.health_check"

    # Debtors endpoint
    resp_debtors = await client.get("/api/v1/onec/debtors", headers=headers)
    assert resp_debtors.status_code == 200
    data = resp_debtors.json()["data"]
    assert len(data) > 0
    # BIN must be masked
    assert "******" in data[0]["bin"]

    # Unposted documents endpoint
    resp_unposted = await client.get("/api/v1/onec/unposted", headers=headers)
    assert resp_unposted.status_code == 200
    unposted_data = resp_unposted.json()["data"]
    assert len(unposted_data) > 0
