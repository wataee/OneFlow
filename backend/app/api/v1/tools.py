from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
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
    ToolExecutionService,
    ToolNotFoundError,
    ToolValidationError,
)

router = APIRouter(prefix="/tools", tags=["Tools Registry & Execution"])


@router.get("", response_model=List[ToolDefinitionResponse])
async def list_available_tools(
    current_user: CurrentUserContext = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns list of all available tools in the registry with their risk classification
    and JSON Schema parameter contracts.
    """
    service = ToolExecutionService(db, current_user.organization_id)
    tools = service.list_tools()
    return [
        ToolDefinitionResponse(
            name=t.name,
            description=t.description,
            risk_level=t.risk_level.value,
            is_mutating=t.is_mutating,
            output_summary=t.output_summary,
            input_schema=t.get_json_schema(),
        )
        for t in tools
    ]


@router.post("/execute", response_model=ToolExecuteResponse)
async def execute_tool(
    req: ToolExecuteRequest,
    current_user: CurrentUserContext = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_db),
):
    """
    Executes a registered tool through the unified execution pipeline:
    Tool -> Policy/Permission -> Execution -> Redaction -> Audit.
    Supports dry-run simulation mode without external side effects.
    """
    service = ToolExecutionService(db, current_user.organization_id)
    context = ExecutionContext.from_user_context(current_user, dry_run=req.dry_run)

    try:
        result = await service.execute_tool(
            tool_name=req.tool_name,
            params=req.params,
            context=context,
        )
        return ToolExecuteResponse(**result)
    except ToolNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PolicyViolationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ToolValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": str(e), "errors": e.errors},
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"1C tool execution failed: {str(e)}",
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
            created_at=c.created_at,
        )
        for c in calls
    ]
