"""
Generic Tool Execution Pipeline and Discovery Service.
Enforces Tool -> Policy -> Execution -> Filter -> Audit pipeline
via the canonical GuardedExecutionPipeline.
"""

import logging
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ValidationError

from app.core.dependencies import CurrentUserContext
from app.integrations.onec.execution import GuardedExecutionPipeline
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
    dry-run state, call source tagging (http_api vs mcp), and unique request tracing ID.
    """
    organization_id: str
    user_id: Optional[str] = None
    role: str = "user"
    dry_run: bool = False
    source: str = "http_api"
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    @classmethod
    def from_user_context(
        cls,
        user_ctx: CurrentUserContext,
        dry_run: bool = False,
        source: str = "http_api",
    ) -> "ExecutionContext":
        return cls(
            organization_id=user_ctx.organization_id,
            user_id=user_ctx.user_id,
            role=user_ctx.role,
            dry_run=dry_run,
            source=source,
        )


class ToolExecutionService:
    """
    Tool discovery and invocation service.
    Validates input parameters according to ToolRegistry schemas and delegates
    guarded execution to the canonical GuardedExecutionPipeline.
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
        """
        Executes a registered tool:
        1. Checks forbidden operations denylist
        2. Resolves tool from ToolRegistry
        3. Validates parameters against typed Pydantic input schema
        4. Delegates to GuardedExecutionPipeline for policy check, dry-run,
           protected execution, redaction, telemetry, and safe adapter closure.
        """
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

        # 3. Delegate to canonical GuardedExecutionPipeline
        pipeline = GuardedExecutionPipeline(
            policy_enforcer=policy_enforcer,
            adapter=adapter,
            audit_service=self.audit_service,
            output_filter=self.output_filter,
            tool_repo=self.tool_repo,
        )

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
        )
