"""
Unified Guarded Execution Pipeline for 1C:Enterprise Operations & Tools.
Single canonical pipeline:
Policy Check -> Dry-Run -> Execution -> Redaction -> Dual Audit & Telemetry -> Safe Closure.
Provides timeout protection, safe error translation, payload capping, and correlation tracking.
"""

import asyncio
import inspect
import json
import logging
import time
from typing import Any, Callable, Dict, Optional

import httpx

from app.core.config import settings
from app.integrations.onec.adapter import OneCAdapter
from app.integrations.onec.output_filter import OneCOutputFilter
from app.integrations.onec.policy import (
    OneCPolicyEnforcer,
    PolicyViolationError,
    RiskLevel,
)
from app.models.entities import ToolCall
from app.repositories.domain_repos import ToolCallRepository
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


def cap_result_payload(payload: Dict[str, Any], max_bytes: int = 65536) -> Dict[str, Any]:
    """Capped serialization helper to prevent unbounded DB JSON growth."""
    try:
        encoded = json.dumps(payload, default=str).encode("utf-8")
        if len(encoded) <= max_bytes:
            return payload
        capped = dict(payload)
        capped["data"] = "[TRUNCATED: payload exceeded 64KB]"
        capped["is_truncated"] = True
        return capped
    except Exception:
        return payload


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
        timeout_seconds: Optional[int] = None,
    ):
        self.policy = policy_enforcer
        self.adapter = adapter
        self.audit = audit_service
        self.filter = output_filter or OneCOutputFilter()
        self.tool_repo = tool_repo
        self.timeout_seconds = timeout_seconds or settings.ONEC_TOOL_TIMEOUT_SECONDS

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
        idempotency_key: Optional[str] = None,
        existing_call: Optional[ToolCall] = None,
    ) -> Dict[str, Any]:
        from app.services.tool_service import (
            ToolAdapterError,
            ToolErrorCode,
            ToolInternalError,
            ToolTimeoutError,
        )

        start_time = time.perf_counter()

        # 1. Security policy check
        try:
            self.policy.verify_or_raise(operation_name, risk_level)
        except PolicyViolationError as pve:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            if existing_call:
                existing_call.status = "BLOCKED"
                existing_call.latency_ms = latency_ms
                existing_call.error = str(pve)
                existing_call.error_code = ToolErrorCode.POLICY_VIOLATION.value
                existing_call.risk_level = risk_level.value
                await self.tool_repo.session.flush()
            elif self.tool_repo:
                await self.tool_repo.log_call(
                    tool_name=operation_name,
                    risk_level=risk_level.value,
                    params={**params, "_source": source},
                    status="BLOCKED",
                    is_dry_run=dry_run,
                    latency_ms=latency_ms,
                    error=str(pve),
                    error_code=ToolErrorCode.POLICY_VIOLATION.value,
                    user_id=user_id,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
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
                        "error_code": ToolErrorCode.POLICY_VIOLATION.value,
                        "request_id": request_id,
                        "source": source,
                        "idempotency_key": idempotency_key,
                    },
                    user_id=user_id,
                )
            if close_adapter and self.adapter:
                await self.adapter.close()
            raise

        # 2. Dry-run simulation branch
        if dry_run:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            dry_run_dict = {
                "operation": operation_name,
                "tool": operation_name,
                "risk_level": risk_level.value,
                "data": None,
                "is_truncated": False,
                "is_mock": getattr(self.adapter, "is_mock", False),
                "dry_run": True,
                "request_id": request_id,
                "idempotency_key": idempotency_key,
            }
            capped_dry_run = cap_result_payload(dry_run_dict)

            if existing_call:
                existing_call.status = "SUCCESS"
                existing_call.is_dry_run = True
                existing_call.latency_ms = latency_ms
                existing_call.risk_level = risk_level.value
                existing_call.result_payload = capped_dry_run
                await self.tool_repo.session.flush()
            elif self.tool_repo:
                await self.tool_repo.log_call(
                    tool_name=operation_name,
                    risk_level=risk_level.value,
                    params={**params, "_source": source},
                    status="SUCCESS",
                    is_dry_run=True,
                    latency_ms=latency_ms,
                    user_id=user_id,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    result_payload=capped_dry_run,
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
                        "is_mock": getattr(self.adapter, "is_mock", False),
                        "source": source,
                        "idempotency_key": idempotency_key,
                    },
                    user_id=user_id,
                )
            if close_adapter and self.adapter:
                await self.adapter.close()
            return dry_run_dict

        # 3. Guarded execution with timeout protection and safe error translation
        status_result = "SUCCESS"
        error_msg: Optional[str] = None
        error_code: Optional[str] = None
        raw_result: Any = None
        raised_exc: Optional[Exception] = None

        try:
            call_res = executor_func()
            if inspect.isawaitable(call_res):
                raw_result = await asyncio.wait_for(
                    call_res,
                    timeout=float(self.timeout_seconds),
                )
            else:
                raw_result = call_res
        except asyncio.TimeoutError:
            status_result = "FAILED"
            error_code = ToolErrorCode.TIMEOUT_ERROR.value
            error_msg = f"Operation '{operation_name}' timed out after {self.timeout_seconds}s"
            logger.error(f"Timeout executing '{operation_name}' (request_id={request_id})")
            raised_exc = ToolTimeoutError(error_msg)
        except ToolAdapterError as exc:
            status_result = "FAILED"
            error_code = ToolErrorCode.ADAPTER_ERROR.value
            error_msg = exc.message
            logger.exception(f"Adapter error executing '{operation_name}' (request_id={request_id}): {exc}")
            raised_exc = exc
        except (ConnectionError, OSError, httpx.HTTPError) as exc:
            status_result = "FAILED"
            error_code = ToolErrorCode.ADAPTER_ERROR.value
            error_msg = f"Communication with 1C OData service failed for '{operation_name}'"
            logger.exception(f"Adapter connection failure for '{operation_name}' (request_id={request_id}): {exc}")
            raised_exc = ToolAdapterError(error_msg)
        except Exception as exc:
            status_result = "FAILED"
            error_code = ToolErrorCode.INTERNAL_ERROR.value
            error_msg = f"Internal execution failure for '{operation_name}'"
            logger.exception(f"Unexpected error executing '{operation_name}' (request_id={request_id}): {exc}")
            raised_exc = ToolInternalError(error_msg)
        finally:
            latency_ms = int((time.perf_counter() - start_time) * 1000)

            # Close adapter safely on every path
            if close_adapter and self.adapter:
                await self.adapter.close()

            # Sanitize result payload for storage
            sanitized_payload = None
            final_dict = None
            if status_result == "SUCCESS":
                sanitized_data, is_truncated = self.filter.filter_result(raw_result)
                final_dict = {
                    "operation": operation_name,
                    "tool": operation_name,
                    "risk_level": risk_level.value,
                    "data": sanitized_data,
                    "is_truncated": is_truncated,
                    "is_mock": getattr(self.adapter, "is_mock", False),
                    "dry_run": False,
                    "request_id": request_id,
                    "idempotency_key": idempotency_key,
                }
                sanitized_payload = cap_result_payload(final_dict)

            # Record telemetry in tool_calls table
            if existing_call:
                existing_call.status = status_result
                existing_call.latency_ms = latency_ms
                existing_call.error = error_msg
                existing_call.error_code = error_code
                existing_call.risk_level = risk_level.value
                existing_call.result_payload = sanitized_payload
                await self.tool_repo.session.flush()
            elif self.tool_repo:
                await self.tool_repo.log_call(
                    tool_name=operation_name,
                    risk_level=risk_level.value,
                    params={**params, "_source": source},
                    status=status_result,
                    is_dry_run=False,
                    latency_ms=latency_ms,
                    error=error_msg,
                    error_code=error_code,
                    user_id=user_id,
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                    result_payload=sanitized_payload,
                )

            # Record in immutable audit log
            if self.audit:
                event_action = "TOOL_EXECUTION_TIMEOUT" if error_code == ToolErrorCode.TIMEOUT_ERROR.value else audit_action
                await self.audit.log_event(
                    action=event_action,
                    entity_type=audit_entity_type,
                    entity_id=operation_name,
                    new_values={
                        "operation": operation_name,
                        "tool": operation_name,
                        "risk_level": risk_level.value,
                        "params": params,
                        "status": status_result,
                        "error": error_msg,
                        "error_code": error_code,
                        "latency_ms": latency_ms,
                        "request_id": request_id,
                        "is_mock": getattr(self.adapter, "is_mock", False),
                        "source": source,
                        "idempotency_key": idempotency_key,
                    },
                    user_id=user_id,
                )

            if self.tool_repo and self.tool_repo.session:
                await self.tool_repo.session.commit()

        if raised_exc:
            raise raised_exc

        return final_dict
