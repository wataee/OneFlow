"""
Tests for Reference-Based Architectural Enhancements:
1. 1C OData Error Envelope Parsing (JSON & XML) (hacker-cb/1c-odata, efinskiy/onec-odata)
2. Tool Poisoning Protection & Schema Fingerprinting (Niraven/mcp-gateway)
3. Per-Tool RBAC & Role Permissioning (PanosSalt/MCP-Gateway)
4. Dynamic 1C Metadata Introspection Tool (vgtitov/bsl-ai-toolkit, pyrfor/onec-odata-mcp)
5. Dynamic Safe Catalog Query Tool (hacker-cb/1c-odata)
6. Human-in-the-Loop Approval Gate via ReviewTask FSM (openai/openai-agents-python)
7. MCP Ping & JSON-RPC Protocol Compliance (modelcontextprotocol/python-sdk)
"""

import json
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.integrations.onec.adapter import MockAdapter
from app.integrations.onec.error_parser import parse_onec_error_response
from app.integrations.onec.policy import PolicyViolationError, RiskLevel
from app.integrations.onec.tools import ToolDefinition, ToolRegistry
from app.main import app
from app.models.entities import Organization, ReviewDecision, ReviewStatus, User, UserRole
from app.repositories.domain_repos import ReviewRepository, ToolCallRepository
from app.services.review_service import ReviewService
from app.services.tool_service import ExecutionContext, ToolExecutionService, ToolValidationError


# =============================================================================
# 1. 1C OData Error Envelope Parser Tests
# =============================================================================

def test_parse_onec_error_response_json():
    # Standard OData v3 JSON error envelope
    json_payload = json.dumps({
        "odata.error": {
            "code": "400",
            "message": {
                "lang": "ru",
                "value": "Ошибка разбора условия отбора: поле 'NonExistent' не найдено"
            }
        }
    })
    msg = parse_onec_error_response(json_payload, status_code=400)
    assert msg == "Ошибка разбора условия отбора: поле 'NonExistent' не найдено"

    # Alternative error envelope format
    alt_json = json.dumps({"error": {"code": "500", "message": "Infobase locked for maintenance"}})
    assert parse_onec_error_response(alt_json, status_code=500) == "Infobase locked for maintenance"


def test_parse_onec_error_response_xml():
    # Standard OData v3 XML error envelope
    xml_payload = """<?xml version="1.0" encoding="utf-8"?>
    <m:error xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">
      <m:code>400</m:code>
      <m:message xml:lang="ru">Поле 'Номер' не заполнено</m:message>
    </m:error>
    """
    msg = parse_onec_error_response(xml_payload, status_code=400)
    assert msg == "Поле 'Номер' не заполнено"

    # Fallback HTML / plain text
    plain_text = "502 Bad Gateway: nginx/1.24.0"
    assert "502 Bad Gateway" in parse_onec_error_response(plain_text, status_code=502)


# =============================================================================
# 2. Tool Poisoning Protection & Schema Fingerprinting
# =============================================================================

class SampleToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    counterparty: str = Field(description="Name of partner")
    amount: float = Field(ge=0.0)


def test_schema_fingerprinting_stability_and_drift():
    tool = ToolDefinition(
        name="read.test.sample",
        description="Sample tool for fingerprint testing",
        risk_level=RiskLevel.SAFE_READ,
        input_schema_class=SampleToolInput,
        output_summary="Sample output",
    )
    initial_hash = tool.schema_hash
    assert len(initial_hash) == 64  # SHA-256 hex digest

    # Deterministic: repeated calls yield identical fingerprint
    assert tool.schema_hash == initial_hash

    # Drift detection: mutating any property alters hash
    tampered_tool = ToolDefinition(
        name="read.test.sample",
        description="Sample tool for fingerprint testing",
        risk_level=RiskLevel.ANALYTICS_READ,  # Drift in risk level
        input_schema_class=SampleToolInput,
        output_summary="Sample output",
    )
    assert tampered_tool.schema_hash != initial_hash


# =============================================================================
# 3. Per-Tool RBAC Role Authorization
# =============================================================================

@pytest.mark.asyncio
async def test_per_tool_rbac_authorization(db_session: AsyncSession):
    org = Organization(name="RBAC Org")
    db_session.add(org)
    await db_session.flush()

    user = User(
        email="employee@rbac.kz",
        hashed_password="fakehash",
        full_name="Employee",
        role=UserRole.USER,
        organization_id=org.id,
    )
    admin = User(
        email="boss@rbac.kz",
        hashed_password="fakehash",
        full_name="Boss",
        role=UserRole.ADMIN,
        organization_id=org.id,
    )
    db_session.add_all([user, admin])
    await db_session.commit()

    test_registry = ToolRegistry()

    class AdminOnlyInput(BaseModel):
        model_config = ConfigDict(extra="forbid")

    admin_tool = ToolDefinition(
        name="read.system.audit_export",
        description="Admin-only audit export tool",
        risk_level=RiskLevel.SAFE_READ,
        input_schema_class=AdminOnlyInput,
        output_summary="Exported logs",
        allowed_roles=["admin"],
    )
    test_registry.register(admin_tool, lambda adapter, params: {"exported": True})

    service = ToolExecutionService(db_session, org.id, tool_registry=test_registry)

    # 1. Employee cannot see admin-only tool during discovery
    user_tools = await service.list_tools_for_tenant(user_role="user")
    assert not any(t.name == "read.system.audit_export" for t in user_tools)

    # 2. Admin can see tool
    admin_tools = await service.list_tools_for_tenant(user_role="admin")
    assert any(t.name == "read.system.audit_export" for t in admin_tools)

    # 3. Employee execution is blocked by RBAC
    user_ctx = ExecutionContext(
        organization_id=org.id,
        user_id=user.id,
        role="user",
    )
    with pytest.raises(PolicyViolationError) as exc_info:
        await service.execute_tool("read.system.audit_export", {}, user_ctx)
    assert "not authorized" in str(exc_info.value)

    # 4. Admin execution succeeds
    admin_ctx = ExecutionContext(
        organization_id=org.id,
        user_id=admin.id,
        role="admin",
    )
    res = await service.execute_tool("read.system.audit_export", {}, admin_ctx)
    assert res["data"]["exported"] is True


# =============================================================================
# 4. Dynamic 1C Metadata & Safe Catalog Query Tools
# =============================================================================

@pytest.mark.asyncio
async def test_dynamic_metadata_and_catalog_query_tools(db_session: AsyncSession):
    org = Organization(name="Metadata Org")
    db_session.add(org)
    await db_session.flush()

    user = User(
        email="analyst@meta.kz",
        hashed_password="fakehash",
        full_name="Analyst",
        role=UserRole.USER,
        organization_id=org.id,
    )
    db_session.add(user)
    await db_session.commit()

    service = ToolExecutionService(db_session, org.id)
    ctx = ExecutionContext(organization_id=org.id, user_id=user.id, role="user")

    # 1. Execute read.system.get_metadata
    meta_res = await service.execute_tool("read.system.get_metadata", {"entity_type": "all"}, ctx)
    assert meta_res["operation"] == "read.system.get_metadata"
    data = meta_res["data"]
    assert "catalogs" in data
    assert "documents" in data
    assert "accumulation_registers" in data
    assert data["total_entities"] > 0

    # 2. Execute read.system.get_metadata filtered
    cat_meta = await service.execute_tool("read.system.get_metadata", {"entity_type": "catalogs"}, ctx)
    assert "catalogs" in cat_meta["data"]
    assert "documents" not in cat_meta["data"]

    # 3. Execute read.catalog.query
    cat_query_res = await service.execute_tool(
        "read.catalog.query",
        {"catalog_name": "Контрагенты", "limit": 2, "offset": 0},
        ctx,
    )
    assert isinstance(cat_query_res["data"], list)
    assert len(cat_query_res["data"]) >= 1

    # 4. Input injection protection on catalog_name
    with pytest.raises(ToolValidationError):
        await service.execute_tool(
            "read.catalog.query",
            {"catalog_name": "Контрагенты; DROP TABLE users; --"},
            ctx,
        )


# =============================================================================
# 5. Human-in-the-Loop (HITL) Approval Gate
# =============================================================================

@pytest.mark.asyncio
async def test_human_in_the_loop_approval_flow(db_session: AsyncSession):
    org = Organization(name="HITL Org")
    db_session.add(org)
    await db_session.flush()

    user = User(
        email="operator@hitl.kz",
        hashed_password="fakehash",
        full_name="Operator",
        role=UserRole.USER,
        organization_id=org.id,
    )
    reviewer = User(
        email="manager@hitl.kz",
        hashed_password="fakehash",
        full_name="Manager",
        role=UserRole.ADMIN,
        organization_id=org.id,
    )
    db_session.add_all([user, reviewer])
    await db_session.commit()

    test_registry = ToolRegistry()

    class HighRiskActionInput(BaseModel):
        model_config = ConfigDict(extra="forbid")
        target_account: str = Field(min_length=3)
        transfer_amount: float = Field(gt=0.0)

    sensitive_tool = ToolDefinition(
        name="read.system.sensitive_action",
        description="High risk operational tool requiring human sign-off",
        risk_level=RiskLevel.SAFE_READ,
        input_schema_class=HighRiskActionInput,
        output_summary="Transfer executed",
        requires_approval=True,
    )
    test_registry.register(sensitive_tool, lambda adapter, params: {"status": "executed", "amount": params.transfer_amount})

    service = ToolExecutionService(db_session, org.id, tool_registry=test_registry)
    ctx = ExecutionContext(organization_id=org.id, user_id=user.id, role="user")

    # 1. Execution without prior approval returns REQUIRES_APPROVAL
    initial_res = await service.execute_tool(
        "read.system.sensitive_action",
        {"target_account": "KZ1234567890", "transfer_amount": 500000.0},
        ctx,
    )
    assert initial_res["status"] == "REQUIRES_APPROVAL"
    assert initial_res["review_task_id"] is not None
    review_task_id = initial_res["review_task_id"]

    # 2. Check telemetry status is PENDING_APPROVAL
    tool_repo = ToolCallRepository(db_session, org.id)
    calls, _ = await tool_repo.list(limit=10)
    pending_call = next(c for c in calls if c.tool_name == "read.system.sensitive_action")
    assert pending_call.status == "PENDING_APPROVAL"

    # 3. Attempting execution with unapproved review ID raises PolicyViolationError
    unapproved_ctx = ExecutionContext(
        organization_id=org.id,
        user_id=user.id,
        role="user",
        approval_review_id=review_task_id,
    )
    with pytest.raises(PolicyViolationError) as exc_info:
        await service.execute_tool(
            "read.system.sensitive_action",
            {"target_account": "KZ1234567890", "transfer_amount": 500000.0},
            unapproved_ctx,
        )
    assert "not in an approved state" in str(exc_info.value)

    # 4. Reviewer approves the pending ReviewTask
    review_service = ReviewService(db_session, org.id)
    await review_service.resolve_review(
        review_id=review_task_id,
        user_id=reviewer.id,
        decision=ReviewDecision.APPROVE,
    )
    await db_session.commit()

    # 5. Execution with approved review ID passes the approval gate and executes!
    approved_ctx = ExecutionContext(
        organization_id=org.id,
        user_id=user.id,
        role="user",
        approval_review_id=review_task_id,
    )
    final_res = await service.execute_tool(
        "read.system.sensitive_action",
        {"target_account": "KZ1234567890", "transfer_amount": 500000.0},
        approved_ctx,
    )
    assert final_res["data"]["status"] == "executed"
    assert final_res["data"]["amount"] == 500000.0


# =============================================================================
# 6. MCP Protocol Compliance (Ping, Discovery & Role Filter)
# =============================================================================

@pytest.mark.asyncio
async def test_mcp_ping_and_tools_list_enhancements(db_session: AsyncSession):
    org = Organization(name="MCP Enhancements Org")
    db_session.add(org)
    await db_session.flush()

    user = User(
        email="mcpuser@enh.kz",
        hashed_password="fakehash",
        full_name="MCP User",
        role=UserRole.USER,
        organization_id=org.id,
    )
    db_session.add(user)
    await db_session.commit()

    token = create_access_token(user.id, org.id, user.role.value)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # 1. MCP Ping method
        ping_resp = await ac.post(
            "/mcp",
            headers={"Authorization": f"Bearer {token}"},
            json={"jsonrpc": "2.0", "id": 10, "method": "ping", "params": {}},
        )
        assert ping_resp.status_code == 200
        ping_data = ping_resp.json()
        assert ping_data["jsonrpc"] == "2.0"
        assert ping_data["id"] == 10
        assert ping_data["result"] == {}

        # 2. Unknown method returns standard -32601 Method Not Found
        unknown_resp = await ac.post(
            "/mcp",
            headers={"Authorization": f"Bearer {token}"},
            json={"jsonrpc": "2.0", "id": 11, "method": "unknown_custom_method", "params": {}},
        )
        assert unknown_resp.status_code == 200
        unknown_data = unknown_resp.json()
        assert unknown_data["error"]["code"] == -32601

        # 3. tools/list returns schemaHash for poisoning protection
        list_resp = await ac.post(
            "/mcp",
            headers={"Authorization": f"Bearer {token}"},
            json={"jsonrpc": "2.0", "id": 12, "method": "tools/list", "params": {}},
        )
        assert list_resp.status_code == 200
        tools = list_resp.json()["result"]["tools"]
        assert len(tools) >= 5
        for t in tools:
            assert "schemaHash" in t
            assert len(t["schemaHash"]) == 64
