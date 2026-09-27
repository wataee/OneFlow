from typing import List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import CurrentUserContext, get_current_user_context
from app.integrations.onec.policy import PolicyViolationError
from app.repositories.domain_repos import ToolCallRepository
from app.schemas.tools import (
    ToolCallHistoryItem,
    ToolDefinitionResponse,
    ToolExecuteRequest,
    ToolExecuteResponse,
)
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

router = APIRouter(prefix="/tools", tags=["Tools Registry & Execution"])


@router.get("", response_model=List[ToolDefinitionResponse])
async def list_available_tools(
    current_user: CurrentUserContext = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns list of available tools matching the tenant's effective risk ceiling,
    caller role permissions, and JSON Schema parameter contracts.
    """
    service = ToolExecutionService(db, current_user.organization_id)
    tools = await service.list_tools_for_tenant(user_role=current_user.role)
    return [
        ToolDefinitionResponse(
            name=t.name,
            description=t.description,
            risk_level=t.risk_level.value,
            is_mutating=t.is_mutating,
            output_summary=t.output_summary,
            input_schema=t.get_json_schema(),
            schema_hash=t.schema_hash,
            allowed_roles=t.allowed_roles,
            requires_approval=t.requires_approval,
        )
        for t in tools
    ]


@router.post("/execute", response_model=ToolExecuteResponse)
async def execute_tool(
    req: ToolExecuteRequest,
    response: Response,
    x_idempotency_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
    x_request_id: Optional[str] = Header(None, alias="X-Request-ID"),
    current_user: CurrentUserContext = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_db),
):
    """
    Executes a registered tool through the unified execution pipeline:
    Tool -> Policy/Permission -> Execution -> Redaction -> Audit.
    Supports dry-run simulation mode without external side effects.
    Supports idempotency caching, in-flight deduplication, and request correlation.
    Supports Human-in-the-Loop authorization gates.
    """
    effective_idempotency_key = x_idempotency_key or req.idempotency_key
    effective_request_id = x_request_id or req.request_id

    service = ToolExecutionService(db, current_user.organization_id)
    context = ExecutionContext.from_user_context(
        current_user,
        dry_run=req.dry_run,
        request_id=effective_request_id,
        idempotency_key=effective_idempotency_key,
        approval_review_id=req.approval_review_id,
    )
    response.headers["X-Request-ID"] = context.request_id

    try:
        result = await service.execute_tool(
            tool_name=req.tool_name,
            params=req.params,
            context=context,
        )
        await db.commit()
        return ToolExecuteResponse(**result)
    except ToolNotFoundError as e:
        await db.commit()
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "detail": e.message,
                "error_code": ToolErrorCode.TOOL_NOT_FOUND.value,
                "message": e.message,
                "request_id": context.request_id,
                "retryable": False,
            },
            headers={"X-Request-ID": context.request_id},
        )
    except PolicyViolationError as e:
        await db.commit()
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={
                "detail": str(e),
                "error_code": ToolErrorCode.POLICY_VIOLATION.value,
                "message": str(e),
                "request_id": context.request_id,
                "retryable": False,
            },
            headers={"X-Request-ID": context.request_id},
        )
    except ToolValidationError as e:
        await db.commit()
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "detail": e.message,
                "error_code": ToolErrorCode.VALIDATION_ERROR.value,
                "message": e.message,
                "request_id": context.request_id,
                "retryable": False,
                "errors": e.errors,
            },
            headers={"X-Request-ID": context.request_id},
        )
    except InFlightRequestError as e:
        await db.commit()
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": e.message,
                "error_code": ToolErrorCode.RATE_LIMITED.value,
                "message": e.message,
                "request_id": context.request_id,
                "retryable": False,
            },
            headers={"X-Request-ID": context.request_id},
        )
    except ToolTimeoutError as e:
        await db.commit()
        return JSONResponse(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            content={
                "detail": e.message,
                "error_code": ToolErrorCode.TIMEOUT_ERROR.value,
                "message": e.message,
                "request_id": context.request_id,
                "retryable": True,
            },
            headers={"X-Request-ID": context.request_id},
        )
    except ToolAdapterError as e:
        await db.commit()
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={
                "detail": e.message,
                "error_code": ToolErrorCode.ADAPTER_ERROR.value,
                "message": e.message,
                "request_id": context.request_id,
                "retryable": True,
            },
            headers={"X-Request-ID": context.request_id},
        )
    except Exception as e:
        await db.commit()
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={
                "detail": f"1C tool execution failed: {str(e)}",
                "error_code": ToolErrorCode.INTERNAL_ERROR.value,
                "message": f"1C tool execution failed: {str(e)}",
                "request_id": context.request_id,
                "retryable": False,
            },
            headers={"X-Request-ID": context.request_id},
        )


@router.get("/history", response_model=List[ToolCallHistoryItem])
async def get_tool_execution_history(
    limit: int = Query(50, ge=1, le=100),
    tool_name: Optional[str] = Query(None),
    is_dry_run: Optional[bool] = Query(None),
    current_user: CurrentUserContext = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns recent tool call logs and telemetry for the current tenant.
    """
    repo = ToolCallRepository(db, current_user.organization_id)
    calls = await repo.list_recent_calls(limit=limit, tool_name=tool_name, is_dry_run=is_dry_run)
    return [
        ToolCallHistoryItem(
            id=c.id,
            tool_name=c.tool_name,
            risk_level=c.risk_level,
            status=c.status,
            is_dry_run=c.is_dry_run,
            latency_ms=c.latency_ms,
            params=c.params or {},
            error=c.error,
            error_code=c.error_code,
            request_id=c.request_id,
            idempotency_key=c.idempotency_key,
            created_at=c.created_at,
        )
        for c in calls
    ]
