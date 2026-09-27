"""
Unified Guarded Execution Pipeline for 1C:Enterprise Operations & Tools.
Single canonical pipeline:
Policy Check -> Dry-Run -> Execution -> Redaction -> Dual Audit & Telemetry -> Safe Closure.
"""

import logging
import time
from typing import Any, Callable, Dict, Optional

from app.integrations.onec.adapter import OneCAdapter
from app.integrations.onec.output_filter import OneCOutputFilter
from app.integrations.onec.policy import (
    OneCPolicyEnforcer,
    PolicyViolationError,
    RiskLevel,
)
from app.repositories.domain_repos import ToolCallRepository
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class GuardedExecutionPipeline:
    """
    Canonical execution pipeline shared by both legacy OneCOperationsService
    and modern ToolExecutionService.
    Ensures policy enforcement, output sanitization, dual telemetry, and safe connection lifecycle.
    """

    def __init__(
        self,
        policy_enforcer: OneCPolicyEnforcer,
        adapter: OneCAdapter,
        audit_service: Optional[AuditService] = None,
        output_filter: Optional[OneCOutputFilter] = None,
        tool_repo: Optional[ToolCallRepository] = None,
    ):
        self.policy = policy_enforcer
        self.adapter = adapter
        self.audit = audit_service
        self.filter = output_filter or OneCOutputFilter()
        self.tool_repo = tool_repo

    async def execute(
        self,
        operation_name: str,
        risk_level: RiskLevel,
        params: Dict[str, Any],
        executor_func: Callable[[], Any],
        user_id: Optional[str] = None,
        dry_run: bool = False,
        request_id: Optional[str] = None,
        audit_action: str = "TOOL_EXECUTED",
        audit_entity_type: str = "ToolCall",
        source: str = "http_api",
        close_adapter: bool = True,
    ) -> Dict[str, Any]:
        start_time = time.perf_counter()

        # 1. Security policy check
        try:
            self.policy.verify_or_raise(operation_name, risk_level)
        except PolicyViolationError as pve:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            if self.tool_repo:
                await self.tool_repo.log_call(
                    tool_name=operation_name,
                    risk_level=risk_level.value,
                    params={**params, "_source": source},
                    status="BLOCKED",
                    is_dry_run=dry_run,
                    latency_ms=latency_ms,
                    error=str(pve),
                    user_id=user_id,
                )
            if self.audit:
                await self.audit.log_event(
                    action="TOOL_EXECUTION_BLOCKED",
                    entity_type=audit_entity_type,
                    entity_id=operation_name,
                    new_values={
                        "operation": operation_name,
                        "tool": operation_name,
                        "risk_level": risk_level.value,
                        "reason": str(pve),
                        "request_id": request_id,
                        "source": source,
                    },
                    user_id=user_id,
                )
            if close_adapter and self.adapter:
                await self.adapter.close()
            raise

        # 2. Dry-run simulation branch
        if dry_run:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            if self.tool_repo:
                await self.tool_repo.log_call(
                    tool_name=operation_name,
                    risk_level=risk_level.value,
                    params={**params, "_source": source},
                    status="SUCCESS",
                    is_dry_run=True,
                    latency_ms=latency_ms,
                    user_id=user_id,
                )
            if self.audit:
                await self.audit.log_event(
                    action="TOOL_DRY_RUN_REQUESTED",
                    entity_type=audit_entity_type,
                    entity_id=operation_name,
                    new_values={
                        "operation": operation_name,
                        "tool": operation_name,
                        "risk_level": risk_level.value,
                        "params": params,
                        "would_execute": True,
                        "request_id": request_id,
                        "is_mock": self.adapter.is_mock,
                        "source": source,
                    },
                    user_id=user_id,
                )
            if close_adapter and self.adapter:
                await self.adapter.close()
            return {
                "operation": operation_name,
                "tool": operation_name,
                "risk_level": risk_level.value,
                "data": None,
                "is_truncated": False,
                "is_mock": self.adapter.is_mock,
                "dry_run": True,
            }

        # 3. Guarded execution
        status_result = "SUCCESS"
        error_msg: Optional[str] = None
        raw_result: Any = None

        try:
            raw_result = await executor_func()
        except Exception as exc:
            status_result = "FAILED"
            error_msg = str(exc)
            logger.error(f"Execution of operation '{operation_name}' failed: {exc}")
            raise
        finally:
            latency_ms = int((time.perf_counter() - start_time) * 1000)

            # Close adapter safely in single canonical place
            if close_adapter and self.adapter:
                await self.adapter.close()

            # Record telemetry in tool_calls table
            if self.tool_repo:
                await self.tool_repo.log_call(
                    tool_name=operation_name,
                    risk_level=risk_level.value,
                    params={**params, "_source": source},
                    status=status_result,
                    is_dry_run=False,
                    latency_ms=latency_ms,
                    error=error_msg,
                    user_id=user_id,
                )

            # Record in immutable audit log
            if self.audit:
                await self.audit.log_event(
                    action=audit_action,
                    entity_type=audit_entity_type,
                    entity_id=operation_name,
                    new_values={
                        "operation": operation_name,
                        "tool": operation_name,
                        "risk_level": risk_level.value,
                        "params": params,
                        "status": status_result,
                        "error": error_msg,
                        "latency_ms": latency_ms,
                        "request_id": request_id,
                        "is_mock": self.adapter.is_mock,
                        "source": source,
                    },
                    user_id=user_id,
                )

        # 4. Filter and sanitize sensitive fields
        sanitized_data, is_truncated = self.filter.filter_result(raw_result)

        return {
            "operation": operation_name,
            "tool": operation_name,
            "risk_level": risk_level.value,
            "data": sanitized_data,
            "is_truncated": is_truncated,
            "is_mock": self.adapter.is_mock,
            "dry_run": False,
        }
