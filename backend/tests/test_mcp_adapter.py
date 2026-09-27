import json
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import AuditLog, Organization, ToolCall
from app.integrations.onec.tools import tool_registry


# =============================================================================
# 1. MCP Authentication Tests
# =============================================================================

@pytest.mark.asyncio
async def test_mcp_unauthorized_without_token(client: AsyncClient):
    # 1. POST /mcp without token -> 401 Unauthorized
    resp_post = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
    )
    assert resp_post.status_code == 401
    assert "WWW-Authenticate" in resp_post.headers

    # 2. GET /mcp/sse without token -> 401 Unauthorized
    resp_sse = await client.get("/mcp/sse")
    assert resp_sse.status_code == 401

    # 3. POST /mcp/messages without token or session -> 401 Unauthorized
    resp_messages = await client.post(
        "/mcp/messages",
        json={"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}},
    )
    assert resp_messages.status_code == 401


@pytest.mark.asyncio
async def test_mcp_auth_via_query_param(client: AsyncClient, seed_tenants: dict):
    token = seed_tenants["headers_a"]["Authorization"].split(" ")[1]

    # Authenticate via ?token= query parameter instead of Authorization header
    resp = await client.post(
        f"/mcp?token={token}",
        json={"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"] == {}


@pytest.mark.asyncio
async def test_mcp_metadata_endpoint(client: AsyncClient):
    resp = await client.get("/mcp")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "online"
    assert data["server"] == "oneflow-mcp"
    assert "/mcp" in data["endpoints"]["streamable_http"]
    assert "/mcp/sse" in data["endpoints"]["sse"]


# =============================================================================
# 2. MCP Tools Discovery (tools/list)
# =============================================================================

@pytest.mark.asyncio
async def test_mcp_tools_list(client: AsyncClient, seed_tenants: dict):
    headers = seed_tenants["headers_a"]

    payload = {
        "jsonrpc": "2.0",
        "id": 10,
        "method": "tools/list",
        "params": {},
    }
    resp = await client.post("/mcp", json=payload, headers=headers)
    assert resp.status_code == 200

    body = resp.json()
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == 10
    result = body["result"]
    assert "tools" in result

    tools = result["tools"]
    registered_names = {t.name for t in tool_registry.list()}
    returned_names = {t["name"] for t in tools}

    # All registered tools must be present
    assert registered_names == returned_names
    assert "read.system.health_check" in returned_names
    assert "read.analytics.get_debtors" in returned_names
    assert "read.warehouse.get_inventory" in returned_names
    assert "read.documents.get_unposted" in returned_names

    # Check schema and description format
    debtors_tool = next(t for t in tools if t["name"] == "read.analytics.get_debtors")
    assert "ANALYTICS_READ" in debtors_tool["description"]
    assert "read-only: True" in debtors_tool["description"]
    assert debtors_tool["inputSchema"]["type"] == "object"
    assert "min_debt" in debtors_tool["inputSchema"]["properties"]
    assert "limit" in debtors_tool["inputSchema"]["properties"]


# =============================================================================
# 3. MCP Tools Execution (tools/call) with Telemetry & Audit
# =============================================================================

@pytest.mark.asyncio
async def test_mcp_tools_call_success_with_telemetry(
    client: AsyncClient,
    seed_tenants: dict,
    db_session: AsyncSession,
):
    headers = seed_tenants["headers_a"]

    payload = {
        "jsonrpc": "2.0",
        "id": 20,
        "method": "tools/call",
        "params": {
            "name": "read.analytics.get_debtors",
            "arguments": {"min_debt": 0.0, "limit": 5},
        },
    }
    resp = await client.post("/mcp", json=payload, headers=headers)
    assert resp.status_code == 200

    body = resp.json()
    assert body["jsonrpc"] == "2.0"
    assert body["id"] == 20
    result = body["result"]
    assert result["isError"] is False
    assert len(result["content"]) == 1
    assert result["content"][0]["type"] == "text"

    # Verify returned JSON content
    parsed_content = json.loads(result["content"][0]["text"])
    assert parsed_content["tool"] == "read.analytics.get_debtors"
    assert parsed_content["risk_level"] == "ANALYTICS_READ"
    assert len(parsed_content["data"]) > 0

    # Verify sensitive data masking
    first_row = parsed_content["data"][0]
    assert "******" in first_row["bin"]

    # Verify tool_calls table telemetry has source="mcp"
    call_q = await db_session.execute(
        select(ToolCall).where(
            ToolCall.tool_name == "read.analytics.get_debtors",
        )
    )
    calls = call_q.scalars().all()
    assert len(calls) >= 1
    latest_call = calls[-1]
    assert latest_call.status == "SUCCESS"
    assert latest_call.params.get("_source") == "mcp"
    assert latest_call.latency_ms is not None

    # Verify audit_logs table has source="mcp"
    audit_q = await db_session.execute(
        select(AuditLog).where(
            AuditLog.action == "TOOL_EXECUTED",
        )
    )
    logs = audit_q.scalars().all()
    mcp_logs = [l for l in logs if l.new_values and l.new_values.get("source") == "mcp"]
    assert len(mcp_logs) >= 1
    assert mcp_logs[-1].new_values.get("status") == "SUCCESS"


@pytest.mark.asyncio
async def test_mcp_tools_call_validation_error(client: AsyncClient, seed_tenants: dict):
    headers = seed_tenants["headers_a"]

    # Input validation error: limit=9999 exceeds le=100
    payload = {
        "jsonrpc": "2.0",
        "id": 30,
        "method": "tools/call",
        "params": {
            "name": "read.documents.get_unposted",
            "arguments": {"limit": 9999},
        },
    }
    resp = await client.post("/mcp", json=payload, headers=headers)
    assert resp.status_code == 200

    body = resp.json()
    result = body["result"]
    assert result["isError"] is True
    assert "Validation error" in result["content"][0]["text"]


@pytest.mark.asyncio
async def test_mcp_tools_call_policy_violation(
    client: AsyncClient,
    seed_tenants: dict,
    db_session: AsyncSession,
):
    headers = seed_tenants["headers_a"]
    org_a = seed_tenants["org_a"]

    # Restrict organization's max risk level to SAFE_READ
    org_in_db = await db_session.get(Organization, org_a.id)
    org_in_db.max_onec_risk_level = "SAFE_READ"
    await db_session.commit()

    # Attempting ANALYTICS_READ operation must be blocked by policy
    payload = {
        "jsonrpc": "2.0",
        "id": 40,
        "method": "tools/call",
        "params": {
            "name": "read.analytics.get_debtors",
            "arguments": {"min_debt": 0.0, "limit": 10},
        },
    }
    resp = await client.post("/mcp", json=payload, headers=headers)
    assert resp.status_code == 200

    body = resp.json()
    result = body["result"]
    assert result["isError"] is True
    assert "Policy violation" in result["content"][0]["text"]

    # Verify AuditLog has recorded failure with action TOOL_EXECUTION_BLOCKED and source=mcp
    audit_q = await db_session.execute(
        select(AuditLog).where(
            AuditLog.organization_id == org_a.id,
            AuditLog.action == "TOOL_EXECUTION_BLOCKED",
        )
    )
    blocked_logs = audit_q.scalars().all()
    assert len(blocked_logs) >= 1
    assert blocked_logs[-1].new_values.get("source") == "mcp"

    # Reset organization risk level
    org_in_db.max_onec_risk_level = "ADMIN_WRITE"
    await db_session.commit()


# =============================================================================
# 4. MCP SSE Transport & Session Messages
# =============================================================================

@pytest.mark.asyncio
async def test_mcp_sse_session_flow(client: AsyncClient, seed_tenants: dict):
    token = seed_tenants["headers_a"]["Authorization"].split(" ")[1]

    # 1. Connect to SSE stream and verify initial event
    async with client.stream("GET", f"/mcp/sse?token={token}&single_event=true") as response:
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]

        endpoint_uri = None
        async for line in response.aiter_lines():
            if line.startswith("data: "):
                endpoint_uri = line[6:].strip()
                break

        assert endpoint_uri is not None
        assert "/mcp/messages?session_id=" in endpoint_uri

    # 2. Post message to /mcp/messages endpoint with Bearer auth
    post_resp = await client.post(
        "/mcp/messages",
        json={"jsonrpc": "2.0", "id": 50, "method": "tools/list", "params": {}},
        headers=seed_tenants["headers_a"],
    )
    assert post_resp.status_code == 200
    msg_data = post_resp.json()
    assert msg_data["id"] == 50
    assert "tools" in msg_data["result"]
