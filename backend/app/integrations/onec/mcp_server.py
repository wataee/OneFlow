"""
MCP Protocol Adapter (Model Context Protocol).
Provides a standardized MCP interface to the OneFlow Tool Registry, allowing external
AI agents (Cursor, Claude Desktop, autonomous frameworks) to safely access 1C:Enterprise
via OneFlow as a secure, audited gateway.

Architecture:
- Consumers: Streamable HTTP (JSON-RPC) & Server-Sent Events (SSE) transports.
- Auth: Multi-tenant JWT extraction via Authorization Bearer header or ?token= query parameter.
- Tool Discovery: Dynamic reflection of tool_registry.list() with Pydantic JSON schemas.
- Tool Execution: Delegates to ToolExecutionService with ExecutionContext(source="mcp").
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse
import mcp.types as types

from app.core.database import AsyncSessionLocal
from app.core.dependencies import CurrentUserContext
from app.core.security import decode_token
from app.integrations.onec.policy import PolicyViolationError
from app.integrations.onec.tools import tool_registry
from app.services.tool_service import (
    ExecutionContext,
    InFlightRequestError,
    ToolAdapterError,
    ToolErrorCode,
    ToolExecutionService,
    ToolNotFoundError,
    ToolTimeoutError,
    ToolValidationError,
)

logger = logging.getLogger("app.mcp")

mcp_router = APIRouter()

# Active SSE sessions: session_id -> {"user": CurrentUserContext, "queue": asyncio.Queue, "created_at": float, "last_active": float}
_active_sse_sessions: Dict[str, Dict[str, Any]] = {}
_sse_lock = asyncio.Lock()
MAX_SSE_SESSIONS = 1000
SSE_SESSION_TTL_SECONDS = 1800  # 30 minutes


# =============================================================================
# Multi-Tenant Authentication & Session Extraction
# =============================================================================

def extract_token_from_request(request: Request) -> Optional[str]:
    """Extracts bearer token from Authorization header or ?token= query parameter."""
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.split(" ", 1)[1].strip()

    token = request.query_params.get("token")
    if token:
        return token.strip()

    return None


def authenticate_mcp_request(
    request: Request,
    session_id: Optional[str] = None,
) -> CurrentUserContext:
    """
    Validates token and returns CurrentUserContext.
    Falls back to active SSE session context if session_id is provided.
    Raises 401 Unauthorized if token is missing or invalid.
    """
    token = extract_token_from_request(request)
    if token:
        try:
            payload = decode_token(token)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials or token expired",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type. Access token required.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        user_id = payload.get("sub")
        org_id = payload.get("org_id")
        role = payload.get("role", "user")

        if not user_id or not org_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incomplete token credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return CurrentUserContext(user_id=user_id, organization_id=org_id, role=role)

    # Check existing authenticated SSE session
    if session_id and session_id in _active_sse_sessions:
        session_info = _active_sse_sessions[session_id]
        if time.time() - session_info.get("last_active", session_info.get("created_at", 0)) > SSE_SESSION_TTL_SECONDS:
            _active_sse_sessions.pop(session_id, None)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="MCP SSE session has expired due to inactivity",
                headers={"WWW-Authenticate": "Bearer"},
            )
        session_info["last_active"] = time.time()
        return session_info["user"]

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication token is required for MCP access",
        headers={"WWW-Authenticate": "Bearer"},
    )


# =============================================================================
# MCP Protocol Handlers (JSON-RPC 2.0)
# =============================================================================

async def handle_initialize(req_id: Any, params: Dict[str, Any]) -> Dict[str, Any]:
    """Handles MCP 'initialize' handshake with protocol version echo."""
    client_proto = params.get("protocolVersion") or "2024-11-05"
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "protocolVersion": client_proto,
            "capabilities": {
                "tools": {"listChanged": False},
            },
            "serverInfo": {
                "name": "oneflow-mcp",
                "version": "1.0.0",
            },
        },
    }


async def handle_list_tools(
    req_id: Any,
    params: Dict[str, Any],
    current_user: CurrentUserContext,
) -> Dict[str, Any]:
    """
    Handles MCP 'tools/list' discovery request.
    Dynamically reflects tools matching current tenant's effective risk ceiling
    and caller role permissions.
    """
    async with AsyncSessionLocal() as db:
        service = ToolExecutionService(
            session=db,
            organization_id=current_user.organization_id,
        )
        tools = await service.list_tools_for_tenant(user_role=current_user.role)

    tools_list = []
    for tool_def in tools:
        schema = tool_def.input_schema_class.model_json_schema()
        description = (
            f"{tool_def.description} "
            f"[risk: {tool_def.risk_level.value}, read-only: {tool_def.read_only}, hash: {tool_def.schema_hash[:8]}]"
        )
        tool_obj = types.Tool(
            name=tool_def.name,
            description=description,
            inputSchema=schema,
        )
        dumped = tool_obj.model_dump(by_alias=True, exclude_none=True)
        dumped["schemaHash"] = tool_def.schema_hash
        dumped["requiresApproval"] = tool_def.requires_approval
        if tool_def.allowed_roles:
            dumped["allowedRoles"] = tool_def.allowed_roles
        tools_list.append(dumped)

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "tools": tools_list,
        },
    }


async def handle_call_tool(
    req_id: Any,
    params: Dict[str, Any],
    current_user: CurrentUserContext,
) -> Dict[str, Any]:
    """
    Handles MCP 'tools/call' invocation request.
    Delegates to ToolExecutionService with ExecutionContext(source='mcp').
    Returns CallToolResult with compact JSON error payloads on failure.
    """
    tool_name = params.get("name")
    arguments = params.get("arguments", {})

    meta = params.get("_meta") or {}
    idempotency_key = (
        meta.get("idempotency_key")
        or params.get("idempotency_key")
        or arguments.get("_idempotency_key")
    )
    request_id = meta.get("request_id") or (str(req_id) if req_id is not None else str(uuid.uuid4()))
    approval_review_id = (
        meta.get("approval_review_id")
        or params.get("approval_review_id")
        or arguments.get("_approval_review_id")
    )

    if not tool_name:
        err_body = {
            "error_code": ToolErrorCode.VALIDATION_ERROR.value,
            "message": "Missing required parameter 'name'",
            "request_id": request_id,
            "retryable": False,
        }
        call_res = types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(err_body, ensure_ascii=False))],
            isError=True,
        )
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": call_res.model_dump(by_alias=True),
        }

    ctx = ExecutionContext(
        user_id=current_user.user_id,
        organization_id=current_user.organization_id,
        role=current_user.role,
        source="mcp",
        request_id=request_id,
        idempotency_key=idempotency_key,
        approval_review_id=approval_review_id,
    )

    async with AsyncSessionLocal() as db:
        service = ToolExecutionService(
            session=db,
            organization_id=current_user.organization_id,
        )
        try:
            execution_res = await service.execute_tool(
                tool_name=tool_name,
                params=arguments or {},
                context=ctx,
            )
            await db.commit()
            formatted_text = json.dumps(execution_res, ensure_ascii=False, default=str)
            call_res = types.CallToolResult(
                content=[types.TextContent(type="text", text=formatted_text)],
                isError=False,
            )
        except PolicyViolationError as pve:
            await db.commit()
            err_body = {
                "error_code": ToolErrorCode.POLICY_VIOLATION.value,
                "message": f"Policy violation: {pve}",
                "request_id": ctx.request_id,
                "retryable": False,
            }
            call_res = types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(err_body, ensure_ascii=False))],
                isError=True,
            )
        except ToolValidationError as tve:
            await db.commit()
            err_body = {
                "error_code": ToolErrorCode.VALIDATION_ERROR.value,
                "message": f"Validation error: {tve.message}",
                "request_id": ctx.request_id,
                "retryable": False,
                "errors": tve.errors,
            }
            call_res = types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(err_body, ensure_ascii=False))],
                isError=True,
            )
        except ToolNotFoundError as tnfe:
            await db.commit()
            err_body = {
                "error_code": ToolErrorCode.TOOL_NOT_FOUND.value,
                "message": f"Tool not found: {tnfe.message}",
                "request_id": ctx.request_id,
                "retryable": False,
            }
            call_res = types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(err_body, ensure_ascii=False))],
                isError=True,
            )
        except InFlightRequestError as ifre:
            await db.commit()
            err_body = {
                "error_code": ToolErrorCode.RATE_LIMITED.value,
                "message": f"In-flight request conflict: {ifre.message}",
                "request_id": ctx.request_id,
                "retryable": False,
            }
            call_res = types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(err_body, ensure_ascii=False))],
                isError=True,
            )
        except ToolTimeoutError as tte:
            await db.commit()
            err_body = {
                "error_code": ToolErrorCode.TIMEOUT_ERROR.value,
                "message": f"Timeout error: {tte.message}",
                "request_id": ctx.request_id,
                "retryable": True,
            }
            call_res = types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(err_body, ensure_ascii=False))],
                isError=True,
            )
        except ToolAdapterError as tae:
            await db.commit()
            err_body = {
                "error_code": ToolErrorCode.ADAPTER_ERROR.value,
                "message": f"Adapter error: {tae.message}",
                "request_id": ctx.request_id,
                "retryable": True,
            }
            call_res = types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(err_body, ensure_ascii=False))],
                isError=True,
            )
        except HTTPException as he:
            await db.commit()
            err_body = {
                "error_code": ToolErrorCode.INTERNAL_ERROR.value,
                "message": f"HTTP error: {he.detail}",
                "request_id": ctx.request_id,
                "retryable": False,
            }
            call_res = types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(err_body, ensure_ascii=False))],
                isError=True,
            )
        except Exception as exc:
            await db.commit()
            err_body = {
                "error_code": ToolErrorCode.INTERNAL_ERROR.value,
                "message": f"Execution error: {str(exc)}",
                "request_id": ctx.request_id,
                "retryable": False,
            }
            call_res = types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(err_body, ensure_ascii=False))],
                isError=True,
            )

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": call_res.model_dump(by_alias=True),
    }


async def process_jsonrpc_request(
    data: Dict[str, Any],
    current_user: CurrentUserContext,
) -> Optional[Dict[str, Any]]:
    """Dispatches incoming JSON-RPC 2.0 request."""
    method = data.get("method")
    req_id = data.get("id")
    params = data.get("params") or {}

    if not method:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32600, "message": "Invalid Request: missing method"},
        }

    # Notifications do not return responses
    if method in ("notifications/initialized", "notifications/cancelled"):
        return None

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "initialize":
        return await handle_initialize(req_id, params)

    if method == "tools/list":
        return await handle_list_tools(req_id, params, current_user)

    if method == "tools/call":
        return await handle_call_tool(req_id, params, current_user)

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method '{method}' not found"},
    }


# =============================================================================
# API Endpoints: Streamable HTTP & SSE
# =============================================================================

@mcp_router.get("", summary="MCP Server Metadata", tags=["MCP"])
@mcp_router.get("/", summary="MCP Server Metadata", tags=["MCP"])
async def get_mcp_metadata(request: Request):
    """Returns MCP gateway discovery info."""
    return {
        "status": "online",
        "server": "oneflow-mcp",
        "protocol_version": "2024-11-05",
        "endpoints": {
            "streamable_http": "/mcp",
            "sse": "/mcp/sse",
            "messages": "/mcp/messages",
        },
        "capabilities": {
            "tools": {"listChanged": False},
        },
    }


@mcp_router.post("", summary="Streamable HTTP MCP Endpoint", tags=["MCP"])
@mcp_router.post("/", summary="Streamable HTTP MCP Endpoint", tags=["MCP"])
async def handle_streamable_http(request: Request):
    """
    Standard Streamable HTTP endpoint for MCP.
    Requires Bearer token in Authorization header or ?token= query parameter.
    """
    current_user = authenticate_mcp_request(request)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            },
        )

    response = await process_jsonrpc_request(body, current_user)
    if response is None:
        return Response(status_code=204)

    return JSONResponse(content=response)


@mcp_router.get("/sse", summary="MCP Server-Sent Events Endpoint", tags=["MCP"])
async def handle_sse_endpoint(request: Request, single_event: bool = False):
    """
    Standard MCP SSE connection endpoint.
    Client establishes persistent SSE connection and receives the relative messages POST URI.
    Enforces concurrency cap (1000) and idle TTL (30 min).
    """
    current_user = authenticate_mcp_request(request)

    async with _sse_lock:
        now = time.time()
        # Sweep expired sessions
        expired = [
            sid for sid, s in _active_sse_sessions.items()
            if now - s.get("last_active", s.get("created_at", now)) > SSE_SESSION_TTL_SECONDS
        ]
        for sid in expired:
            _active_sse_sessions.pop(sid, None)

        if len(_active_sse_sessions) >= MAX_SSE_SESSIONS:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Maximum concurrent MCP SSE sessions reached (cap=1000). Please retry later.",
            )

        session_id = uuid.uuid4().hex
        queue: asyncio.Queue = asyncio.Queue()
        _active_sse_sessions[session_id] = {
            "user": current_user,
            "queue": queue,
            "created_at": now,
            "last_active": now,
        }

    async def sse_event_generator():
        # 1. Send endpoint event pointing to /mcp/messages
        endpoint_uri = f"/mcp/messages?session_id={session_id}"
        yield f"event: endpoint\ndata: {endpoint_uri}\n\n"
        if single_event:
            return

        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=1.0)
                    msg_json = json.dumps(msg, ensure_ascii=False)
                    yield f"event: message\ndata: {msg_json}\n\n"
                    queue.task_done()
                except asyncio.TimeoutError:
                    # Keep-alive ping comment
                    yield ": ping\n\n"
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            async with _sse_lock:
                _active_sse_sessions.pop(session_id, None)

    return StreamingResponse(
        sse_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@mcp_router.post("/messages", summary="MCP SSE Post Messages Endpoint", tags=["MCP"])
async def handle_post_messages(request: Request, session_id: Optional[str] = None):
    """
    Receives JSON-RPC messages from clients connected over SSE.
    If session_id corresponds to an active SSE session, responses are streamed via SSE.
    """
    current_user = authenticate_mcp_request(request, session_id=session_id)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            },
        )

    response = await process_jsonrpc_request(body, current_user)

    # If active SSE session, send response via SSE stream
    if session_id:
        target_queue = None
        async with _sse_lock:
            if session_id in _active_sse_sessions:
                _active_sse_sessions[session_id]["last_active"] = time.time()
                target_queue = _active_sse_sessions[session_id]["queue"]

        if target_queue and response is not None:
            await target_queue.put(response)
            return JSONResponse(status_code=202, content={"status": "accepted"})

    if response is None:
        return Response(status_code=204)

    return JSONResponse(content=response)
