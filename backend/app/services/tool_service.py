"""
Generic Tool Execution Pipeline and Discovery Service.
Enforces Tool -> Policy -> Execution -> Filter -> Audit pipeline.
"""

import time
import uuid
import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ValidationError

from app.core.dependencies import CurrentUserContext
from app.integrations.onec.output_filter import OneCOutputFilter
from app.integrations.onec.policy import FORBIDDEN_OPERATIONS, PolicyViolationError
from app.integrations.onec.tools import ToolDefinition, registry as default_registry
from app.repositories.domain_repos import ToolCallRepository
from app.services.audit_service import AuditService
from app.services.onec_service import OneCService

logger = logging.getLogger(__name__)


class ToolNotFoundError(Exception):
    """Raised when an operation/tool is not registered in the ToolRegistry."""
    pass


class ToolValidationError(Exception):
    """Raised when input parameters fail Pydantic schema validation."""
    def __init__(self, message: str, errors: Optional[List[Dict[str, Any]]] = None):
        super().__init__(message)
        self.errors = errors or []


class ExecutionContext(BaseModel):
    """
    Contextual execution envelope providing tenant isolation, caller identity,
    dry-run state, and unique request tracing ID.
    """
    organization_id: str
    user_id: Optional[str] = None
    role: str = "user"
    dry_run: bool = False
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    @classmethod
    def from_user_context(cls, user_ctx: CurrentUserContext, dry_run: bool = False) -> "ExecutionContext":
        return cls(
            organization_id=user_ctx.organization_id,
            user_id=user_ctx.user_id,
            role=user_ctx.role,
            dry_run=dry_run,
        )


class ToolExecutionService:
    """
    Unified execution pipeline:
    1. Tool discovery and resolution
    2. Input schema validation (Pydantic)
    3. Security policy check (OneCPolicyEnforcer)
    4. Dry-run branch
    5. Execution via OneCAdapter
    6. Output sanitization & masking (OneCOutputFilter)
    7. Dual telemetry recording (AuditLog + ToolCall)
    """

    def __init__(
        self,
        session,
        organization_id: str,
        tool_registry=None,
    ):
        self.session = session
        self.organization_id = organization_id
        self.registry = tool_registry or default_registry
        self.audit_service = AuditService(session, organization_id)
        self.tool_repo = ToolCallRepository(session, organization_id)
        self.onec_service = OneCService(session, organization_id)
        self.output_filter = OneCOutputFilter()

    def list_tools(self) -> List[ToolDefinition]:
        """Lists all registered tools."""
        return self.registry.list()

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Gets a tool definition by name."""
        return self.registry.get(name)

    async def execute_tool(
        self,
        tool_name: str,
        params: Dict[str, Any],
        context: ExecutionContext,
    ) -> Dict[str, Any]:
        start_time = time.perf_counter()

        # 1. Resolve tool by name
        if tool_name in FORBIDDEN_OPERATIONS:
            raise PolicyViolationError(
                f"Operation '{tool_name}' is on the FORBIDDEN_OPERATIONS denylist and cannot be executed."
            )

        tool = self.registry.get(tool_name)
        if not tool:
            raise ToolNotFoundError(f"Tool '{tool_name}' is not recognized in the Tool Registry.")

        executor = self.registry.get_executor(tool_name)
        if not executor:
            raise ToolNotFoundError(f"No executable handler registered for tool '{tool_name}'.")

        # 2. Input validation according to tool's typed Pydantic schema
        try:
            validated_input = tool.input_schema_class.model_validate(params or {})
        except ValidationError as val_err:
            raise ToolValidationError(
                message=f"Parameter validation failed for tool '{tool_name}'",
                errors=val_err.errors(),
            )

        # Build tenant-specific operations service, policy enforcer and adapter
        op_service = await self.onec_service.get_operations_service()
        policy_enforcer = op_service.policy
        adapter = op_service.adapter

        # 3. Security Policy check
        try:
            policy_enforcer.verify_or_raise(tool.name, tool.risk_level)
        except PolicyViolationError as pve:
            # Log blocked attempt
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            await self.tool_repo.log_call(
                tool_name=tool.name,
                risk_level=tool.risk_level.value,
                params=params,
                status="BLOCKED",
                is_dry_run=context.dry_run,
                latency_ms=latency_ms,
                error=str(pve),
                user_id=context.user_id,
            )
            await self.audit_service.log_event(
                action="TOOL_EXECUTION_BLOCKED",
                entity_type="ToolCall",
                entity_id=tool.name,
                new_values={
                    "tool": tool.name,
                    "risk_level": tool.risk_level.value,
                    "reason": str(pve),
                    "request_id": context.request_id,
                },
                user_id=context.user_id,
            )
            raise

        # 4. Dry-run branch: return pre-flight validation without invoking 1C or mock transport
        if context.dry_run:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            await self.tool_repo.log_call(
                tool_name=tool.name,
                risk_level=tool.risk_level.value,
                params=params,
                status="SUCCESS",
                is_dry_run=True,
                latency_ms=latency_ms,
                user_id=context.user_id,
            )
            await self.audit_service.log_event(
                action="TOOL_DRY_RUN_REQUESTED",
                entity_type="ToolCall",
                entity_id=tool.name,
                new_values={
                    "tool": tool.name,
                    "risk_level": tool.risk_level.value,
                    "params": params,
                    "would_execute": True,
                    "request_id": context.request_id,
                    "is_mock": adapter.is_mock,
                },
                user_id=context.user_id,
            )
            return {
                "tool": tool.name,
                "risk_level": tool.risk_level.value,
                "data": None,
                "is_truncated": False,
                "is_mock": adapter.is_mock,
                "dry_run": True,
            }

        # 5. Execution via OneCAdapter
        raw_result: Any = None
        status_result = "SUCCESS"
        error_msg: Optional[str] = None

        try:
            raw_result = await executor(adapter, validated_input)
        except Exception as exc:
            status_result = "FAILED"
            error_msg = str(exc)
            logger.error(f"Execution of tool '{tool_name}' failed: {exc}")
            raise
        finally:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            if adapter:
                await adapter.close()

            # Record telemetry in tool_calls
            await self.tool_repo.log_call(
                tool_name=tool.name,
                risk_level=tool.risk_level.value,
                params=params,
                status=status_result,
                is_dry_run=False,
                latency_ms=latency_ms,
                error=error_msg,
                user_id=context.user_id,
            )

            # Record event in immutable audit log
            await self.audit_service.log_event(
                action="TOOL_EXECUTED",
                entity_type="ToolCall",
                entity_id=tool.name,
                new_values={
                    "tool": tool.name,
                    "risk_level": tool.risk_level.value,
                    "params": params,
                    "status": status_result,
                    "error": error_msg,
                    "latency_ms": latency_ms,
                    "request_id": context.request_id,
                    "is_mock": adapter.is_mock,
                },
                user_id=context.user_id,
            )

        # 6. Filter and sanitize sensitive fields
        sanitized_data, is_truncated = self.output_filter.filter_result(raw_result)

        return {
            "tool": tool.name,
            "risk_level": tool.risk_level.value,
            "data": sanitized_data,
            "is_truncated": is_truncated,
            "is_mock": adapter.is_mock,
            "dry_run": False,
        }
