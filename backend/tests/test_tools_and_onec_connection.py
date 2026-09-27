import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.core.security import decrypt_onec_credential, encrypt_onec_credential
from app.integrations.onec.adapter import MockAdapter, ODataAdapter, OneCAdapter
from app.integrations.onec.client import OneCClientWrapper
from app.integrations.onec.policy import (
    FORBIDDEN_OPERATIONS,
    OneCPolicyEnforcer,
    PolicyViolationError,
    RiskLevel,
)
from app.integrations.onec.ssrf import SSRFValidationError, validate_onec_base_url
from app.integrations.onec.tools import (
    ToolDefinition,
    ToolRegistry,
    registry as global_tool_registry,
)
from app.models.entities import AuditLog, Organization, ToolCall
from app.services.tool_service import (
    ExecutionContext,
    ToolExecutionService,
    ToolNotFoundError,
    ToolValidationError,
)


# =============================================================================
# 1. Unit Tests
# =============================================================================

def test_tool_registry_registration_and_forbidden_denylist():
    reg = ToolRegistry()

    class SampleInput(BaseModel):
        query: str

    sample_tool = ToolDefinition(
        name="read.test.sample",
        description="Sample read operation",
        risk_level=RiskLevel.SAFE_READ,
        input_schema_class=SampleInput,
        output_summary="Sample output",
    )

    reg.register(sample_tool, lambda adapter, params: {"ok": True})
    assert reg.get("read.test.sample") is not None
    assert len(reg.list()) == 1

    # Attempting to register any forbidden operation must fail at registration time
    for forbidden_name in FORBIDDEN_OPERATIONS:
        bad_tool = ToolDefinition(
            name=forbidden_name,
            description="Dangerous forbidden call",
            risk_level=RiskLevel.SAFE_READ,
            input_schema_class=SampleInput,
            output_summary="Should not be registered",
        )
        with pytest.raises(ValueError) as exc_info:
            reg.register(bad_tool, lambda adapter, params: None)
        assert "FORBIDDEN_OPERATIONS denylist" in str(exc_info.value)


def test_onec_adapter_interface_conformance():
    # Structural verification that ODataAdapter and MockAdapter implement OneCAdapter
    mock_adapter = MockAdapter()
    assert isinstance(mock_adapter, OneCAdapter)
    assert mock_adapter.is_mock is True

    client = OneCClientWrapper(base_url="https://mock-company-1c.kz/odata/standard.odata")
    odata_adapter = ODataAdapter(client)
    assert isinstance(odata_adapter, OneCAdapter)
    assert odata_adapter.is_mock is False


def test_credential_encryption_roundtrip():
    secret = "SuperSecretPassword123!"
    ciphertext = encrypt_onec_credential(secret)

    # Ciphertext must not match raw secret
    assert ciphertext != secret
    assert len(ciphertext) > len(secret)

    # Decryption recovers exact plaintext
    decrypted = decrypt_onec_credential(ciphertext)
    assert decrypted == secret

    # Empty string handling
    assert encrypt_onec_credential("") == ""
    assert decrypt_onec_credential("") == ""


def test_ssrf_validator_blocks_internal_hosts():
    # Forbidden loopback and private names
    forbidden_urls = [
        "http://localhost:8000/odata",
        "http://127.0.0.1:8080/standard.odata",
        "http://0.0.0.0:8000",
        "http://postgres:5432",
        "http://redis:6379",
        "http://backend:8000",
        "http://internal-server.local",
        "http://10.0.0.1/odata",
        "http://192.168.1.50/odata",
        "http://172.16.0.5:8080",
        "http://169.254.169.254/latest/meta-data",
        "ftp://company.kz/odata",  # Invalid scheme
    ]

    for bad_url in forbidden_urls:
        with pytest.raises(SSRFValidationError):
            validate_onec_base_url(bad_url)

    # Allowed external URL
    valid_url = "https://1c.mycompany.kz/corp/odata/standard.odata/"
    sanitized = validate_onec_base_url(valid_url)
    assert sanitized == "https://1c.mycompany.kz/corp/odata/standard.odata"


# =============================================================================
# 2. Integration Tests: Tool Registry Discovery & Execution
# =============================================================================

@pytest.mark.asyncio
async def test_tools_discovery_api(client: AsyncClient, seed_tenants: dict):
    headers = seed_tenants["headers_a"]
    resp = await client.get("/api/v1/tools", headers=headers)
    assert resp.status_code == 200

    tools = resp.json()
    assert len(tools) >= 4

    tool_names = [t["name"] for t in tools]
    assert "read.system.health_check" in tool_names
    assert "read.documents.get_unposted" in tool_names
    assert "read.analytics.get_debtors" in tool_names
    assert "read.warehouse.get_inventory" in tool_names

    # Check input_schema is valid JSON schema
    for t in tools:
        assert "properties" in t["input_schema"]
        assert "risk_level" in t
        assert "output_summary" in t


@pytest.mark.asyncio
async def test_tool_execute_dry_run(client: AsyncClient, seed_tenants: dict, db_session: AsyncSession):
    headers = seed_tenants["headers_a"]

    # Dry-run execution of health_check
    payload = {
        "tool_name": "read.system.health_check",
        "params": {},
        "dry_run": True,
    }
    resp = await client.post("/api/v1/tools/execute", json=payload, headers=headers)
    assert resp.status_code == 200

    data = resp.json()
    assert data["tool"] == "read.system.health_check"
    assert data["dry_run"] is True
    assert data["data"] is None

    # Check audit log: must contain TOOL_DRY_RUN_REQUESTED, NOT TOOL_EXECUTED
    res = await db_session.execute(
        select(AuditLog).where(AuditLog.action == "TOOL_DRY_RUN_REQUESTED")
    )
    dry_runs = res.scalars().all()
    assert len(dry_runs) >= 1


@pytest.mark.asyncio
async def test_tool_execute_not_found_and_validation_error(client: AsyncClient, seed_tenants: dict):
    headers = seed_tenants["headers_a"]

    # 1. Tool not found -> 404
    resp_404 = await client.post(
        "/api/v1/tools/execute",
        json={"tool_name": "read.unknown.non_existent", "params": {}},
        headers=headers,
    )
    assert resp_404.status_code == 404

    # 2. Invalid parameters (limit > 100 violates le=100) -> 422
    resp_422 = await client.post(
        "/api/v1/tools/execute",
        json={
            "tool_name": "read.documents.get_unposted",
            "params": {"limit": 9999},
        },
        headers=headers,
    )
    assert resp_422.status_code == 422


@pytest.mark.asyncio
async def test_tool_execute_real_call_with_telemetry(client: AsyncClient, seed_tenants: dict, db_session: AsyncSession):
    headers = seed_tenants["headers_a"]

    # Execute debtors analysis
    payload = {
        "tool_name": "read.analytics.get_debtors",
        "params": {"min_debt": 0.0, "limit": 10},
        "dry_run": False,
    }
    resp = await client.post("/api/v1/tools/execute", json=payload, headers=headers)
    assert resp.status_code == 200

    data = resp.json()
    assert data["tool"] == "read.analytics.get_debtors"
    assert data["risk_level"] == "ANALYTICS_READ"
    assert data["dry_run"] is False
    assert len(data["data"]) > 0

    # Output filter must have masked the Kazakhstani BIN & IBAN
    first_item = data["data"][0]
    assert "981240001122" not in first_item["bin"]
    assert "******" in first_item["bin"]

    # Check telemetry stored in tool_calls table
    call_res = await db_session.execute(
        select(ToolCall).where(ToolCall.tool_name == "read.analytics.get_debtors")
    )
    calls = call_res.scalars().all()
    assert len(calls) >= 1
    assert calls[0].status == "SUCCESS"
    assert calls[0].is_dry_run is False
    assert calls[0].latency_ms is not None


# =============================================================================
# 3. Security Tests: Role Authorization, Password Encryption, SSRF
# =============================================================================

@pytest.mark.asyncio
async def test_onec_connection_admin_role_restriction(client: AsyncClient, seed_tenants: dict):
    # Member user (role=user) attempting to update 1C configuration -> 403 Forbidden
    member_headers = seed_tenants["headers_a_member"]
    update_payload = {
        "base_url": "https://onec.company.kz/standard.odata",
        "username": "admin_user",
        "password": "SecretPassword123!",
        "is_writable": False,
    }
    resp_forbidden = await client.put(
        "/api/v1/onec-connection", json=update_payload, headers=member_headers
    )
    assert resp_forbidden.status_code == 403
    assert "Administrative privileges required" in resp_forbidden.json()["detail"]


@pytest.mark.asyncio
async def test_onec_connection_ssrf_protection_api(client: AsyncClient, seed_tenants: dict):
    admin_headers = seed_tenants["headers_a"]

    # Admin trying to configure internal docker host or localhost -> 400 Bad Request
    ssrf_payload = {
        "base_url": "http://localhost:8000/odata",
        "username": "hacker",
        "password": "pwd",
        "is_writable": False,
    }
    resp_ssrf = await client.put("/api/v1/onec-connection", json=ssrf_payload, headers=admin_headers)
    assert resp_ssrf.status_code == 400
    assert "forbidden" in resp_ssrf.json()["detail"].lower()


@pytest.mark.asyncio
async def test_onec_password_encrypted_in_db_and_not_in_audit(
    client: AsyncClient, seed_tenants: dict, db_session: AsyncSession
):
    admin_headers = seed_tenants["headers_a"]
    plain_password = "MyHighlyConfidential1CPassword!"

    update_payload = {
        "base_url": "https://my-1c.company.kz/standard.odata",
        "username": "1c_login",
        "password": plain_password,
        "is_writable": False,
    }
    resp = await client.put("/api/v1/onec-connection", json=update_payload, headers=admin_headers)
    assert resp.status_code == 200

    # GET response must NOT expose the password
    get_resp = await client.get("/api/v1/onec-connection", headers=admin_headers)
    assert get_resp.status_code == 200
    assert "password" not in get_resp.json()

    # Query DB directly to verify raw password is NOT stored in plain text
    org_res = await db_session.execute(
        select(Organization).where(Organization.id == seed_tenants["org_a"].id)
    )
    org = org_res.scalars().first()
    stored_cfg = org.onec_config
    assert stored_cfg is not None
    assert plain_password not in stored_cfg["password"]
    # Verify it can be decrypted back
    assert decrypt_onec_credential(stored_cfg["password"]) == plain_password

    # Check AuditLog: new_values must NOT contain plaintext password
    audit_res = await db_session.execute(
        select(AuditLog).where(AuditLog.action == "ONEC_CONNECTION_UPDATED")
    )
    logs = audit_res.scalars().all()
    assert len(logs) >= 1
    for log in logs:
        new_val_str = str(log.new_values)
        assert plain_password not in new_val_str


# =============================================================================
# 4. Multi-Tenancy Isolation Tests
# =============================================================================

@pytest.mark.asyncio
async def test_onec_connection_multi_tenancy_isolation(
    client: AsyncClient, seed_tenants: dict, db_session: AsyncSession
):
    headers_a = seed_tenants["headers_a"]
    headers_b = seed_tenants["headers_b"]

    # Organization A configures its 1C endpoint
    await client.put(
        "/api/v1/onec-connection",
        json={"base_url": "https://tenant-a-1c.company.kz/odata", "is_writable": False},
        headers=headers_a,
    )

    # Organization B reads its own configuration
    resp_b = await client.get("/api/v1/onec-connection", headers=headers_b)
    data_b = resp_b.json()
    assert data_b["base_url"] != "https://tenant-a-1c.company.kz/odata"
    assert data_b["is_configured"] is False

    # Execute tool in Org A with dry_run=True so it logs telemetry without external network call
    await client.post(
        "/api/v1/tools/execute",
        json={"tool_name": "read.system.health_check", "params": {}, "dry_run": True},
        headers=headers_a,
    )

    # Verify Org B cannot view Org A's tool_calls history
    history_b = await client.get("/api/v1/tools/history", headers=headers_b)
    assert len(history_b.json()) == 0


# =============================================================================
# 5. Risk Engine: Organization Ceiling Override
# =============================================================================

@pytest.mark.asyncio
async def test_organization_stricter_risk_ceiling_blocks_operation(
    client: AsyncClient, seed_tenants: dict, db_session: AsyncSession
):
    headers_a = seed_tenants["headers_a"]
    org_a = seed_tenants["org_a"]

    # Set Organization A risk ceiling to SAFE_READ (L0) in DB (keeping mock mode active)
    org_a.max_onec_risk_level = "SAFE_READ"
    db_session.add(org_a)
    await db_session.commit()

    # 1. Health check (L0: SAFE_READ) -> Allowed (executes via MockAdapter and returns 200)
    res_safe = await client.post(
        "/api/v1/tools/execute",
        json={"tool_name": "read.system.health_check", "params": {}},
        headers=headers_a,
    )
    assert res_safe.status_code == 200
    assert res_safe.json()["data"]["status"] == "connected"

    # 2. Debtors (L1: ANALYTICS_READ) -> Blocked by organization's SAFE_READ ceiling!
    res_blocked = await client.post(
        "/api/v1/tools/execute",
        json={"tool_name": "read.analytics.get_debtors", "params": {"min_debt": 0.0}},
        headers=headers_a,
    )
    assert res_blocked.status_code == 403
    assert "exceeds maximum allowed risk level" in res_blocked.json()["detail"]


# =============================================================================
# 6. Mock Determinism & Failure Handling
# =============================================================================

@pytest.mark.asyncio
async def test_mock_adapter_determinism():
    mock = MockAdapter()
    call1 = await mock.list_document("ПлатежноеПоручениеИсходящее", top=10)
    call2 = await mock.list_document("ПлатежноеПоручениеИсходящее", top=10)
    assert call1 == call2

    debtors1 = await mock.list_accumulation_register("ВзаиморасчетыСКонтрагентами", top=10)
    debtors2 = await mock.list_accumulation_register("ВзаиморасчетыСКонтрагентами", top=10)
    assert debtors1 == debtors2


# =============================================================================
# 7. Idempotency of Read Tools
# =============================================================================

@pytest.mark.asyncio
async def test_read_tools_idempotency(client: AsyncClient, seed_tenants: dict):
    headers = seed_tenants["headers_a"]
    params = {"doc_type": "ПлатежноеПоручениеИсходящее", "limit": 10}

    resp1 = await client.post(
        "/api/v1/tools/execute",
        json={"tool_name": "read.documents.get_unposted", "params": params},
        headers=headers,
    )
    resp2 = await client.post(
        "/api/v1/tools/execute",
        json={"tool_name": "read.documents.get_unposted", "params": params},
        headers=headers,
    )
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json()["data"] == resp2.json()["data"]
