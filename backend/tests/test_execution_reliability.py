"""
Integration & Unit Tests for Execution Reliability & Gateway Hardening:
1. Idempotency replay (cached result returned without re-execution).
2. In-flight concurrent request conflict (HTTP 409 & MCP RATE_LIMITED).
3. Request correlation ID propagation across HTTP headers, tool_calls, and audit_logs.
4. Safe error masking (sanitized errors, raw connection secrets masked).
5. Timeout protection (asyncio timeout enforcement & 504 status).
6. Bounded retries (transient failure followed by success, multiple ToolCall audit attempts).
7. Tenant-aware tool discovery (HTTP and MCP respect effective tenant risk ceiling).
8. TokenMaskFilter redaction in logs and MCP SSE session lifecycle limits (cap & TTL).
"""

import asyncio
import json
import logging
import time
import pytest
from httpx import AsyncClient
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.onec.mcp_server import (
    MAX_SSE_SESSIONS,
    _active_sse_sessions,
    _sse_lock,
)
from app.integrations.onec.policy import RiskLevel
from app.integrations.onec.tools import ToolDefinition, registry
from app.main import TokenMaskFilter
from app.models.entities import AuditLog, Organization, ToolCall
from app.services.tool_service import ToolAdapterError


# =============================================================================
# 1. Idempotency & In-Flight Concurrency Tests
# =============================================================================

@pytest.mark.asyncio
async def test_idempotency_replay_returns_cached_result(
    client: AsyncClient,
    seed_tenants: dict,
    db_session: AsyncSession,
):
    headers = {
        **seed_tenants["headers_a"],
        "X-Idempotency-Key": "test-idemp-unique-123",
        "X-Request-ID": "req-initial-1",
    }
    payload = {
        "tool_name": "read.system.health_check",
        "params": {},
        "dry_run": False,
    }

    # First execution -> 200 OK
    resp1 = await client.post("/api/v1/tools/execute", json=payload, headers=headers)
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["tool"] == "read.system.health_check"
    assert data1["idempotency_key"] == "test-idemp-unique-123"

    # Second execution with same idempotency key but different request_id -> Returns cached result
    headers2 = {
        **seed_tenants["headers_a"],
        "X-Idempotency-Key": "test-idemp-unique-123",
        "X-Request-ID": "req-replay-2",
    }
    resp2 = await client.post("/api/v1/tools/execute", json=payload, headers=headers2)
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["tool"] == "read.system.health_check"
    assert data2["idempotency_key"] == "test-idemp-unique-123"

    # Verify only ONE ToolCall row was created for this idempotency key
    res = await db_session.execute(
        select(ToolCall).where(ToolCall.idempotency_key == "test-idemp-unique-123")
    )
    calls = res.scalars().all()
    assert len(calls) == 1
    assert calls[0].status == "SUCCESS"


@pytest.mark.asyncio
async def test_in_flight_concurrent_request_conflict_http(
    client: AsyncClient,
    seed_tenants: dict,
    db_session: AsyncSession,
):
    org_a = seed_tenants["org_a"]

    # Pre-seed an in-flight ToolCall row with status RUNNING
    in_flight_call = ToolCall(
        organization_id=org_a.id,
        tool_name="read.system.health_check",
        risk_level=RiskLevel.SAFE_READ.value,
        status="RUNNING",
        is_dry_run=False,
        params={},
        idempotency_key="in-flight-key-409",
        request_id="req-in-flight-first",
    )
    db_session.add(in_flight_call)
    await db_session.commit()

    # Attempting to execute with the same idempotency key must raise 409 Conflict
    headers = {
        **seed_tenants["headers_a"],
        "X-Idempotency-Key": "in-flight-key-409",
        "X-Request-ID": "req-in-flight-second",
    }
    payload = {
        "tool_name": "read.system.health_check",
        "params": {},
    }
    resp = await client.post("/api/v1/tools/execute", json=payload, headers=headers)
    assert resp.status_code == 409
    body = resp.json()
    assert body["error_code"] == "RATE_LIMITED"
    assert "in-flight" in body["message"].lower()


@pytest.mark.asyncio
async def test_in_flight_concurrent_request_conflict_mcp(
    client: AsyncClient,
    seed_tenants: dict,
    db_session: AsyncSession,
):
    org_a = seed_tenants["org_a"]

    in_flight_call = ToolCall(
        organization_id=org_a.id,
        tool_name="read.system.health_check",
        risk_level=RiskLevel.SAFE_READ.value,
        status="RUNNING",
        is_dry_run=False,
        params={},
        idempotency_key="mcp-in-flight-key",
        request_id="mcp-req-first",
    )
    db_session.add(in_flight_call)
    await db_session.commit()

    # Call tool via MCP with identical idempotency_key in _meta
    mcp_payload = {
        "jsonrpc": "2.0",
        "id": 99,
        "method": "tools/call",
        "params": {
            "name": "read.system.health_check",
            "arguments": {},
            "_meta": {"idempotency_key": "mcp-in-flight-key"},
        },
    }
    resp = await client.post("/mcp", json=mcp_payload, headers=seed_tenants["headers_a"])
    assert resp.status_code == 200
    res_data = resp.json()["result"]
    assert res_data["isError"] is True

    err_payload = json.loads(res_data["content"][0]["text"])
    assert err_payload["error_code"] == "RATE_LIMITED"


# =============================================================================
# 2. Correlation ID Propagation
# =============================================================================

@pytest.mark.asyncio
async def test_request_id_correlation_propagation(
    client: AsyncClient,
    seed_tenants: dict,
    db_session: AsyncSession,
):
    custom_corr_id = "corr-uuid-777-abc"
    headers = {
        **seed_tenants["headers_a"],
        "X-Request-ID": custom_corr_id,
    }
    payload = {
        "tool_name": "read.system.health_check",
        "params": {},
    }

    resp = await client.post("/api/v1/tools/execute", json=payload, headers=headers)
    assert resp.status_code == 200
    assert resp.headers.get("X-Request-ID") == custom_corr_id
    assert resp.json()["request_id"] == custom_corr_id

    # Check persistence in tool_calls
    call_q = await db_session.execute(
        select(ToolCall).where(ToolCall.request_id == custom_corr_id)
    )
    call_row = call_q.scalar_one_or_none()
    assert call_row is not None
    assert call_row.request_id == custom_corr_id

    # Check persistence in audit_logs
    audit_q = await db_session.execute(
        select(AuditLog).where(AuditLog.action == "TOOL_EXECUTED")
    )
    audit_rows = audit_q.scalars().all()
    matching_audits = [
        a for a in audit_rows if a.new_values and a.new_values.get("request_id") == custom_corr_id
    ]
    assert len(matching_audits) >= 1


# =============================================================================
# 3. Safe Error Masking & Timeout Protection
# =============================================================================

@pytest.mark.asyncio
async def test_safe_error_masking(
    client: AsyncClient,
    seed_tenants: dict,
    db_session: AsyncSession,
):
    """Verifies internal server details and credentials are never leaked in tool error responses."""
    class DummyInput(BaseModel):
        model_config = ConfigDict(extra="forbid")

    dummy_tool_name = "read.test.error_masking"
    secret_leak_attempt = "Internal Database Connection Error: postgres://admin:super_secret_pw@10.0.0.99:5432/onec"

    def leaking_executor(adapter, params):
        raise ConnectionError(secret_leak_attempt)

    registry.register(
        ToolDefinition(
            name=dummy_tool_name,
            description="Test error masking",
            risk_level=RiskLevel.SAFE_READ,
            input_schema_class=DummyInput,
            output_summary="N/A",
        ),
        leaking_executor,
    )

    try:
        resp = await client.post(
            "/api/v1/tools/execute",
            json={"tool_name": dummy_tool_name, "params": {}},
            headers=seed_tenants["headers_a"],
        )
        assert resp.status_code == 502
        body = resp.json()

        assert body["error_code"] == "ADAPTER_ERROR"
        # Secret credentials and internal IP must NOT leak
        assert "super_secret_pw" not in str(body)
        assert "10.0.0.99" not in str(body)

        # Check telemetry recorded
        res = await db_session.execute(
            select(ToolCall).where(ToolCall.tool_name == dummy_tool_name)
        )
        calls = res.scalars().all()
        assert len(calls) >= 1
        assert calls[-1].status == "FAILED"
        assert calls[-1].error_code == "ADAPTER_ERROR"
    finally:
        registry._tools.pop(dummy_tool_name, None)
        registry._executors.pop(dummy_tool_name, None)


@pytest.mark.asyncio
async def test_timeout_protection(
    client: AsyncClient,
    seed_tenants: dict,
    db_session: AsyncSession,
    monkeypatch,
):
    """Verifies timeout triggers HTTP 504 and logs TIMEOUT_ERROR."""
    class DummyInput(BaseModel):
        model_config = ConfigDict(extra="forbid")

    dummy_timeout_name = "read.test.timeout_guard"

    async def slow_executor(adapter, params):
        await asyncio.sleep(1.5)
        return {"ok": True}

    registry.register(
        ToolDefinition(
            name=dummy_timeout_name,
            description="Test timeout",
            risk_level=RiskLevel.SAFE_READ,
            input_schema_class=DummyInput,
            output_summary="N/A",
        ),
        slow_executor,
    )

    # Temporarily set timeout to 1 second
    monkeypatch.setattr(settings, "ONEC_TOOL_TIMEOUT_SECONDS", 1)

    try:
        resp = await client.post(
            "/api/v1/tools/execute",
            json={"tool_name": dummy_timeout_name, "params": {}},
            headers=seed_tenants["headers_a"],
        )
        assert resp.status_code == 504
        body = resp.json()
        assert body["error_code"] == "TIMEOUT_ERROR"

        # Telemetry in tool_calls
        res = await db_session.execute(
            select(ToolCall).where(ToolCall.tool_name == dummy_timeout_name)
        )
        calls = res.scalars().all()
        assert len(calls) >= 1
        assert calls[-1].status == "FAILED"
        assert calls[-1].error_code == "TIMEOUT_ERROR"
    finally:
        registry._tools.pop(dummy_timeout_name, None)
        registry._executors.pop(dummy_timeout_name, None)


# =============================================================================
# 4. Bounded Retries
# =============================================================================

@pytest.mark.asyncio
async def test_bounded_retries_transient_failure_then_success(
    client: AsyncClient,
    seed_tenants: dict,
    db_session: AsyncSession,
):
    """Verifies flaky adapter retries once and logs both attempt telemetry records."""
    class DummyInput(BaseModel):
        model_config = ConfigDict(extra="forbid")

    dummy_retry_name = "read.test.flaky_retry"
    attempt_counter = {"count": 0}

    def flaky_executor(adapter, params):
        attempt_counter["count"] += 1
        if attempt_counter["count"] == 1:
            raise ToolAdapterError("Temporary network blip")
        return {"status": "recovered", "attempts": attempt_counter["count"]}

    registry.register(
        ToolDefinition(
            name=dummy_retry_name,
            description="Test flaky retry",
            risk_level=RiskLevel.SAFE_READ,
            input_schema_class=DummyInput,
            output_summary="N/A",
        ),
        flaky_executor,
    )

    corr_id = "retry-test-corr-456"
    headers = {
        **seed_tenants["headers_a"],
        "X-Request-ID": corr_id,
    }

    try:
        resp = await client.post(
            "/api/v1/tools/execute",
            json={"tool_name": dummy_retry_name, "params": {}},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["data"]["status"] == "recovered"
        assert attempt_counter["count"] == 2

        # Check telemetry in tool_calls: must have recorded 2 rows under the same correlation ID
        res = await db_session.execute(
            select(ToolCall).where(ToolCall.tool_name == dummy_retry_name)
        )
        calls = res.scalars().all()
        assert len(calls) == 2
        # First attempt failed
        assert calls[0].status == "FAILED"
        assert calls[0].error_code == "ADAPTER_ERROR"
        assert calls[0].request_id == corr_id
        # Second attempt succeeded
        assert calls[1].status == "SUCCESS"
        assert calls[1].request_id == corr_id
    finally:
        registry._tools.pop(dummy_retry_name, None)
        registry._executors.pop(dummy_retry_name, None)


# =============================================================================
# 5. Tenant-Aware Tool Discovery
# =============================================================================

@pytest.mark.asyncio
async def test_tenant_aware_tool_discovery_http_and_mcp(
    client: AsyncClient,
    seed_tenants: dict,
    db_session: AsyncSession,
):
    """
    Verifies that when an organization's risk ceiling is set to SAFE_READ,
    both HTTP /api/v1/tools and MCP tools/list only discover SAFE_READ tools.
    """
    org_a = seed_tenants["org_a"]
    org_in_db = await db_session.get(Organization, org_a.id)
    org_in_db.max_onec_risk_level = "SAFE_READ"
    await db_session.commit()

    try:
        # 1. HTTP Discovery
        http_resp = await client.get("/api/v1/tools", headers=seed_tenants["headers_a"])
        assert http_resp.status_code == 200
        http_tools = http_resp.json()
        tool_names = [t["name"] for t in http_tools]

        assert "read.system.health_check" in tool_names
        assert "read.documents.get_unposted" in tool_names
        # ANALYTICS_READ tools must be excluded
        assert "read.analytics.get_debtors" not in tool_names
        assert "read.warehouse.get_inventory" not in tool_names

        # 2. MCP Discovery (tools/list)
        mcp_payload = {
            "jsonrpc": "2.0",
            "id": 101,
            "method": "tools/list",
            "params": {},
        }
        mcp_resp = await client.post("/mcp", json=mcp_payload, headers=seed_tenants["headers_a"])
        assert mcp_resp.status_code == 200
        mcp_tools = mcp_resp.json()["result"]["tools"]
        mcp_tool_names = [t["name"] for t in mcp_tools]

        assert "read.system.health_check" in mcp_tool_names
        assert "read.documents.get_unposted" in mcp_tool_names
        assert "read.analytics.get_debtors" not in mcp_tool_names
        assert "read.warehouse.get_inventory" not in mcp_tool_names

    finally:
        org_in_db.max_onec_risk_level = "ADMIN_WRITE"
        await db_session.commit()


# =============================================================================
# 6. Log Redaction & MCP SSE Lifecycle Hardening
# =============================================================================

def test_token_mask_filter():
    """Verifies that TokenMaskFilter redacts token query parameter values."""
    filt = TokenMaskFilter()

    # Case 1: token in msg string
    rec1 = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="GET /mcp/sse?token=sensitive_jwt_token_123&foo=bar",
        args=(),
        exc_info=None,
    )
    filt.filter(rec1)
    assert "token=***" in rec1.msg
    assert "sensitive_jwt_token_123" not in rec1.msg

    # Case 2: token in args tuple
    rec2 = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="%s - %s",
        args=("127.0.0.1", "/mcp?token=secret_in_args"),
        exc_info=None,
    )
    filt.filter(rec2)
    assert "token=***" in rec2.args[1]
    assert "secret_in_args" not in rec2.args[1]


@pytest.mark.asyncio
async def test_mcp_sse_session_cap_and_ttl(
    client: AsyncClient,
    seed_tenants: dict,
):
    token = seed_tenants["headers_a"]["Authorization"].split(" ")[1]

    # Test 1: Concurrency Cap
    async with _sse_lock:
        original_sessions = dict(_active_sse_sessions)
        # Fill sessions to cap
        for i in range(MAX_SSE_SESSIONS):
            _active_sse_sessions[f"dummy_session_{i}"] = {
                "user": seed_tenants["user_a"],
                "queue": asyncio.Queue(),
                "created_at": time.time(),
                "last_active": time.time(),
            }

    try:
        # Next connection must be rejected with 503 Service Unavailable
        resp_cap = await client.get(f"/mcp/sse?token={token}")
        assert resp_cap.status_code == 503
        assert "Maximum concurrent MCP SSE sessions reached" in resp_cap.json()["detail"]
    finally:
        async with _sse_lock:
            _active_sse_sessions.clear()
            _active_sse_sessions.update(original_sessions)

    # Test 2: Idle Session TTL Expiration
    expired_sid = "expired_test_session"
    async with _sse_lock:
        _active_sse_sessions[expired_sid] = {
            "user": seed_tenants["user_a"],
            "queue": asyncio.Queue(),
            "created_at": time.time() - 3600,
            "last_active": time.time() - 3600,  # 1 hour ago (> 30 min TTL)
        }

    try:
        post_resp = await client.post(
            f"/mcp/messages?session_id={expired_sid}",
            json={"jsonrpc": "2.0", "id": 105, "method": "ping", "params": {}},
        )
        assert post_resp.status_code == 401
        assert "expired due to inactivity" in post_resp.json()["detail"]
    finally:
        async with _sse_lock:
            _active_sse_sessions.pop(expired_sid, None)
