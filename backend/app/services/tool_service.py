"""
Generic Tool Execution Pipeline and Discovery Service.
Enforces Tool -> Policy -> Execution -> Filter -> Audit pipeline
via the canonical GuardedExecutionPipeline with idempotency, timeout protection,
bounded retries, per-tool RBAC authorization, and Human-in-the-Loop approval gates.

Architectural attribution:
- Per-tool RBAC role policies inspired by PanosSalt/MCP-Gateway (MIT).
- Human-in-the-Loop (HITL) approval pause gate inspired by openai/openai-agents-python (Apache 2.0).
- Tool Poisoning Protection fingerprints inspired by Niraven/mcp-gateway (MIT).
"""

import asyncio
import enum
import json
import logging
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ValidationError

from app.core.config import settings
from app.core.dependencies import CurrentUserContext
from app.integrations.onec.output_filter import OneCOutputFilter
from app.integrations.onec.policy import FORBIDDEN_OPERATIONS, PolicyViolationError, RiskLevel
from app.integrations.onec.tools import ToolDefinition, registry as default_registry
from app.models.entities import ReviewDecision, ReviewStatus, ReviewTask, Task, TaskStatus, TaskType, ToolCall
from app.repositories.domain_repos import ReviewRepository, TaskRepository, ToolCallRepository
from app.services.audit_service import AuditService
from app.services.onec_service import OneCService

logger = logging.getLogger(__name__)


# =============================================================================
# Structured Error Taxonomy & Custom Exceptions
# =============================================================================

class ToolErrorCode(str, enum.Enum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    ADAPTER_ERROR = "ADAPTER_ERROR"
    TIMEOUT_ERROR = "TIMEOUT_ERROR"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class ToolNotFoundError(Exception):
    """Raised when an operation/tool is not registered in the ToolRegistry."""
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message
        self.error_code = ToolErrorCode.TOOL_NOT_FOUND
        self.retryable = False


class ToolValidationError(Exception):
    """Raised when input parameters fail Pydantic schema validation."""
    def __init__(self, message: str, errors: Optional[List[Dict[str, Any]]] = None):
        super().__init__(message)
        self.message = message
        self.errors = errors or []
        self.error_code = ToolErrorCode.VALIDATION_ERROR
        self.retryable = False


class ToolTimeoutError(Exception):
    """Raised when tool execution exceeds configured timeout."""
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message
        self.error_code = ToolErrorCode.TIMEOUT_ERROR
        self.retryable = True


class ToolAdapterError(Exception):
    """Raised when 1C OData communication or adapter fails."""
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message
        self.error_code = ToolErrorCode.ADAPTER_ERROR
        self.retryable = True


class InFlightRequestError(Exception):
    """Raised when duplicate request with same idempotency key is already in-flight."""
    def __init__(self, message: str = "Duplicate in-flight request"):
        super().__init__(message)
        self.message = message
        self.error_code = ToolErrorCode.RATE_LIMITED
        self.retryable = False


class ToolInternalError(Exception):
    """Raised on unhandled internal execution failures."""
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message
        self.error_code = ToolErrorCode.INTERNAL_ERROR
        self.retryable = False


# =============================================================================
# Execution Context
# =============================================================================

class ExecutionContext(BaseModel):
    """
    Contextual execution envelope providing tenant isolation, caller identity,
    dry-run state, call source tagging (http_api vs mcp), unique request tracing ID,
    and optional Human-in-the-Loop approval review ID.
    """
    organization_id: str
    user_id: Optional[str] = None
    role: str = "user"
    dry_run: bool = False
    source: str = "http_api"
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    idempotency_key: Optional[str] = None
    approval_review_id: Optional[str] = None

    @classmethod
    def from_user_context(
        cls,
        user_ctx: CurrentUserContext,
        dry_run: bool = False,
        source: str = "http_api",
        request_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        approval_review_id: Optional[str] = None,
    ) -> "ExecutionContext":
        return cls(
            organization_id=user_ctx.organization_id,
            user_id=user_ctx.user_id,
            role=user_ctx.role,
            dry_run=dry_run,
            source=source,
            request_id=request_id or str(uuid.uuid4()),
            idempotency_key=idempotency_key,
            approval_review_id=approval_review_id,
        )


# =============================================================================
# Tool Execution Service
# =============================================================================

class ToolExecutionService:
    """
    Tool discovery and invocation service.
    Validates input parameters according to ToolRegistry schemas, checks role-based
    access control (RBAC), routes through Human-in-the-Loop gates where required,
    and delegates execution to the canonical GuardedExecutionPipeline.
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
        self.task_repo = TaskRepository(session, organization_id)
        self.review_repo = ReviewRepository(session, organization_id)
        self.onec_service = OneCService(session, organization_id)
        self.output_filter = OneCOutputFilter(default_max_rows=settings.ONEC_OUTPUT_MAX_ROWS)

    def list_tools(self, user_role: Optional[str] = None) -> List[ToolDefinition]:
        """Lists registered tools optionally filtered by caller role."""
        return self.registry.list(user_role=user_role)

    async def list_tools_for_tenant(self, user_role: Optional[str] = None) -> List[ToolDefinition]:
        """
        Lists registered tools allowed by the tenant's effective risk ceiling
        and optional caller role. Resolves min(global_ceiling, org_ceiling).
        """
        op_service = await self.onec_service.get_operations_service()
        effective_ceiling = op_service.policy.max_allowed_risk
        return self.registry.list(max_risk_level=effective_ceiling, user_role=user_role)

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Gets a tool definition by name."""
        return self.registry.get(name)

    async def execute_tool(
        self,
        tool_name: str,
        params: Dict[str, Any],
        context: ExecutionContext,
    ) -> Dict[str, Any]:
        """
        Executes a registered tool:
        1. Checks idempotency (claims in-flight or returns stored SUCCESS result)
        2. Resolves tool, checks per-tool RBAC role permissions
        3. Validates parameters against typed Pydantic schema
        4. Evaluates Human-in-the-Loop approval gate (creates ReviewTask if approval needed)
        5. Executes with GuardedExecutionPipeline and bounded retries on retryable errors.
        """
        # 1. Idempotency Check & In-flight claim
        claim_record: Optional[ToolCall] = None
        if context.idempotency_key:
            existing = await self.tool_repo.get_by_idempotency_key(context.idempotency_key)
            if existing:
                if existing.status == "RUNNING":
                    raise InFlightRequestError("Duplicate in-flight request")
                if existing.status == "SUCCESS":
                    logger.info(
                        f"Idempotency hit for key '{context.idempotency_key}', returning cached result "
                        f"(request_id={context.request_id})"
                    )
                    cached = existing.result_payload or {}
                    return {
                        **cached,
                        "request_id": context.request_id,
                        "idempotency_key": context.idempotency_key,
                    }
                # If existing is FAILED or BLOCKED, claim and re-execute
                existing.status = "RUNNING"
                existing.request_id = context.request_id
                existing.user_id = context.user_id
                await self.session.flush()
                claim_record = existing
            else:
                claim_record = await self.tool_repo.claim_in_flight(
                    tool_name=tool_name,
                    risk_level=RiskLevel.SAFE_READ.value,
                    params=params or {},
                    idempotency_key=context.idempotency_key,
                    request_id=context.request_id,
                    user_id=context.user_id,
                )
                await self.session.flush()

        # 2. Resolve tool by name
        if tool_name in FORBIDDEN_OPERATIONS:
            if claim_record:
                claim_record.status = "BLOCKED"
                claim_record.error = f"Operation '{tool_name}' is on the FORBIDDEN_OPERATIONS denylist."
                claim_record.error_code = ToolErrorCode.POLICY_VIOLATION.value
                await self.session.flush()
            raise PolicyViolationError(
                f"Operation '{tool_name}' is on the FORBIDDEN_OPERATIONS denylist and cannot be executed."
            )

        tool = self.registry.get(tool_name)
        if not tool:
            if claim_record:
                claim_record.status = "FAILED"
                claim_record.error = f"Tool '{tool_name}' is not recognized in the Tool Registry."
                claim_record.error_code = ToolErrorCode.TOOL_NOT_FOUND.value
                await self.session.flush()
            raise ToolNotFoundError(f"Tool '{tool_name}' is not recognized in the Tool Registry.")

        executor = self.registry.get_executor(tool_name)
        if not executor:
            if claim_record:
                claim_record.status = "FAILED"
                claim_record.error = f"No executable handler registered for tool '{tool_name}'."
                claim_record.error_code = ToolErrorCode.TOOL_NOT_FOUND.value
                await self.session.flush()
            raise ToolNotFoundError(f"No executable handler registered for tool '{tool_name}'.")

        # 3. Per-Tool RBAC: Role-based authorization check
        if tool.allowed_roles is not None and context.role not in tool.allowed_roles:
            role_err = (
                f"User role '{context.role}' is not authorized to execute tool '{tool_name}'. "
                f"Permitted roles: {tool.allowed_roles}."
            )
            if claim_record:
                claim_record.status = "BLOCKED"
                claim_record.error = role_err
                claim_record.error_code = ToolErrorCode.POLICY_VIOLATION.value
                await self.session.flush()
            raise PolicyViolationError(role_err)

        # 4. Input validation according to tool's typed Pydantic schema
        try:
            validated_input = tool.input_schema_class.model_validate(params or {})
        except ValidationError as val_err:
            if claim_record:
                claim_record.status = "FAILED"
                claim_record.error = f"Parameter validation failed for tool '{tool_name}'"
                claim_record.error_code = ToolErrorCode.VALIDATION_ERROR.value
                await self.session.flush()
            raise ToolValidationError(
                message=f"Parameter validation failed for tool '{tool_name}'",
                errors=val_err.errors(),
            )

        # 5. Human-in-the-Loop (HITL) Approval Gate
        if tool.requires_approval and not context.dry_run:
            approval_valid = False
            if context.approval_review_id:
                review = await self.review_repo.get_by_id(context.approval_review_id)
                if (
                    review
                    and review.organization_id == self.organization_id
                    and review.status == ReviewStatus.RESOLVED
                    and review.user_decision == ReviewDecision.APPROVE
                ):
                    approval_valid = True
                else:
                    unapproved_err = (
                        f"Approval review '{context.approval_review_id}' is not in an approved state."
                    )
                    if claim_record:
                        claim_record.status = "BLOCKED"
                        claim_record.error = unapproved_err
                        claim_record.error_code = ToolErrorCode.POLICY_VIOLATION.value
                        await self.session.flush()
                    raise PolicyViolationError(unapproved_err)

            if not approval_valid:
                task = Task(
                    organization_id=self.organization_id,
                    type=TaskType.TOOL_APPROVAL,
                    status=TaskStatus.REVIEW,
                    input_data={
                        "tool_name": tool_name,
                        "params": params,
                        "source": context.source,
                        "request_id": context.request_id,
                    },
                )
                await self.task_repo.create(task)

                review = ReviewTask(
                    organization_id=self.organization_id,
                    task_id=task.id,
                    status=ReviewStatus.PENDING,
                    ai_result={"tool_name": tool_name, "params": params, "request_id": context.request_id},
                    proposed_changes={
                        "action": "EXECUTE_TOOL",
                        "tool_name": tool_name,
                        "risk_level": tool.risk_level.value,
                    },
                )
                await self.review_repo.create(review)

                approval_payload = {
                    "tool": tool_name,
                    "risk_level": tool.risk_level.value,
                    "status": "REQUIRES_APPROVAL",
                    "review_task_id": review.id,
                    "task_id": task.id,
                    "message": f"Execution of tool '{tool_name}' requires human approval before proceeding.",
                    "dry_run": False,
                    "request_id": context.request_id,
                    "idempotency_key": context.idempotency_key,
                }

                if claim_record:
                    claim_record.status = "PENDING_APPROVAL"
                    claim_record.risk_level = tool.risk_level.value
                    claim_record.result_payload = approval_payload
                    await self.session.flush()
                else:
                    await self.tool_repo.log_call(
                        tool_name=tool_name,
                        risk_level=tool.risk_level.value,
                        params={**params, "_source": context.source},
                        status="PENDING_APPROVAL",
                        is_dry_run=False,
                        user_id=context.user_id,
                        request_id=context.request_id,
                        idempotency_key=context.idempotency_key,
                        result_payload=approval_payload,
                    )

                await self.audit_service.log_event(
                    action="TOOL_APPROVAL_REQUESTED",
                    entity_type="ReviewTask",
                    entity_id=review.id,
                    new_values={
                        "tool_name": tool_name,
                        "risk_level": tool.risk_level.value,
                        "task_id": task.id,
                        "review_task_id": review.id,
                        "params": params,
                        "request_id": context.request_id,
                        "source": context.source,
                    },
                    user_id=context.user_id,
                )

                return approval_payload

        # 6. Guarded execution with bounded retries on retryable errors
        from app.integrations.onec.execution import GuardedExecutionPipeline

        max_retries = settings.ONEC_TOOL_RETRIES
        attempts = 0
        last_error = None

        while attempts <= max_retries:
            attempts += 1
            op_service = await self.onec_service.get_operations_service()
            policy_enforcer = op_service.policy
            adapter = op_service.adapter

            pipeline = GuardedExecutionPipeline(
                policy_enforcer=policy_enforcer,
                adapter=adapter,
                audit_service=self.audit_service,
                output_filter=self.output_filter,
                tool_repo=self.tool_repo,
                timeout_seconds=settings.ONEC_TOOL_TIMEOUT_SECONDS,
            )

            try:
                return await pipeline.execute(
                    operation_name=tool.name,
                    risk_level=tool.risk_level,
                    params=params,
                    executor_func=lambda: executor(adapter, validated_input),
                    user_id=context.user_id,
                    dry_run=context.dry_run,
                    request_id=context.request_id,
                    audit_action="TOOL_EXECUTED",
                    audit_entity_type="ToolCall",
                    source=context.source,
                    close_adapter=True,
                    idempotency_key=context.idempotency_key,
                    existing_call=claim_record if attempts == 1 else None,
                )
            except (ToolAdapterError, ToolTimeoutError) as retryable_err:
                last_error = retryable_err
                if attempts <= max_retries:
                    logger.warning(
                        f"Retrying tool execution '{tool_name}' after {retryable_err.__class__.__name__} "
                        f"(attempt {attempts}/{max_retries + 1}, request_id={context.request_id})"
                    )
                    await asyncio.sleep(0.5)
                    continue
                raise
            except Exception:
                raise

        if last_error:
            raise last_error
