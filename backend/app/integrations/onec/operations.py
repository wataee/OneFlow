"""
1C:Enterprise Business Operations Suite.

Architectural attribution:
- Hierarchical operation naming taxonomy (`read.<category>.<action>`)
  referenced from 1c-odata-mcp (https://github.com/evilbruce666/1c-odata-mcp).
- Mandatory pre-execution policy check and output sanitization
  referenced from ashybulakstroy-mcp-1c-bridge (https://github.com/ashybulakstroy/ashybulakstroy-mcp-1c-bridge).
"""

import logging
from typing import Any, Dict, List, Optional
from onec_odata import F

from app.integrations.onec.adapter import MockAdapter, ODataAdapter, OneCAdapter
from app.integrations.onec.client import OneCClientWrapper
from app.integrations.onec.output_filter import OneCOutputFilter
from app.integrations.onec.policy import (
    OneCPolicyEnforcer,
    RiskLevel,
    requires_risk_level,
)
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class OneCOperationsService:
    """
    Executes standard read-only operations against 1C:Enterprise via OneCAdapter.
    Ensures policy compliance, immutable audit logging, output redaction, and dry-run execution.
    """

    def __init__(
        self,
        client: Optional[OneCClientWrapper] = None,
        policy_enforcer: Optional[OneCPolicyEnforcer] = None,
        audit_service: Optional[AuditService] = None,
        output_filter: Optional[OneCOutputFilter] = None,
        is_mock: bool = False,
        adapter: Optional[OneCAdapter] = None,
    ):
        self.policy = policy_enforcer or OneCPolicyEnforcer()
        self.audit = audit_service
        self.filter = output_filter or OneCOutputFilter()
        self.client = client

        # Resolve adapter
        if adapter is not None:
            self.adapter = adapter
        elif client is not None and not is_mock:
            self.adapter = ODataAdapter(client)
        else:
            self.adapter = MockAdapter()

        self.is_mock = self.adapter.is_mock

    async def _execute_with_guards(
        self,
        operation_name: str,
        risk_level: RiskLevel,
        params: Dict[str, Any],
        executor_func,
        user_id: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Core generic execution pipeline:
        1. Security policy check (throws PolicyViolationError if blocked)
        2. Dry-run branch (validates policy without invoking transport/mock data)
        3. Execution via OneCAdapter
        4. Output filtering (IIN/BIN masking & row limits)
        5. Immutable audit logging
        """
        # 1. Enforce policy
        self.policy.verify_or_raise(operation_name, risk_level)

        # 2. Dry run check
        if dry_run:
            if self.audit:
                await self.audit.log_event(
                    action="TOOL_DRY_RUN_REQUESTED",
                    entity_type="OneCOperation",
                    entity_id=operation_name,
                    new_values={
                        "operation": operation_name,
                        "risk_level": risk_level.value,
                        "params": params,
                        "would_execute": True,
                        "is_mock": self.is_mock,
                    },
                    user_id=user_id,
                )
            return {
                "operation": operation_name,
                "risk_level": risk_level.value,
                "data": None,
                "is_truncated": False,
                "is_mock": self.is_mock,
                "dry_run": True,
            }

        status_result = "SUCCESS"
        error_msg = None
        raw_result: Any = None

        try:
            raw_result = await executor_func()
        except Exception as exc:
            status_result = "FAILED"
            error_msg = str(exc)
            logger.error(f"1C operation {operation_name} failed: {exc}")
            raise
        finally:
            # 5. Record event in immutable audit log
            if self.audit:
                await self.audit.log_event(
                    action="ONEC_OPERATION_EXECUTED",
                    entity_type="OneCOperation",
                    entity_id=operation_name,
                    new_values={
                        "operation": operation_name,
                        "risk_level": risk_level.value,
                        "params": params,
                        "status": status_result,
                        "error": error_msg,
                        "is_mock": self.is_mock,
                    },
                    user_id=user_id,
                )

        # 4. Filter and sanitize sensitive fields
        sanitized_data, is_truncated = self.filter.filter_result(raw_result)

        return {
            "operation": operation_name,
            "risk_level": risk_level.value,
            "data": sanitized_data,
            "is_truncated": is_truncated,
            "is_mock": self.is_mock,
            "dry_run": False,
        }

    # =========================================================================
    # 1. Healthcheck / System Status (L0: SAFE_READ)
    # =========================================================================
    @requires_risk_level(RiskLevel.SAFE_READ)
    async def health_check(
        self, user_id: Optional[str] = None, dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Taxonomy: read.system.health_check
        Checks availability of 1C OData service.
        """
        operation_name = "read.system.health_check"

        async def _exec():
            return await self.adapter.health_check()

        return await self._execute_with_guards(
            operation_name=operation_name,
            risk_level=RiskLevel.SAFE_READ,
            params={},
            executor_func=_exec,
            user_id=user_id,
            dry_run=dry_run,
        )

    # =========================================================================
    # 2. Unposted Documents (L0: SAFE_READ)
    # =========================================================================
    @requires_risk_level(RiskLevel.SAFE_READ)
    async def get_unposted_documents(
        self,
        doc_type: str = "ПлатежноеПоручениеИсходящее",
        limit: int = 50,
        user_id: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Taxonomy: read.documents.get_unposted
        Fetches unposted draft documents requiring accountant review.
        """
        operation_name = "read.documents.get_unposted"

        async def _exec():
            filter_expr = F("Posted") == False
            return await self.adapter.list_document(doc_type, top=limit, filter_expr=filter_expr)

        return await self._execute_with_guards(
            operation_name=operation_name,
            risk_level=RiskLevel.SAFE_READ,
            params={"doc_type": doc_type, "limit": limit},
            executor_func=_exec,
            user_id=user_id,
            dry_run=dry_run,
        )

    # =========================================================================
    # 3. Debtors Analysis (L1: ANALYTICS_READ)
    # =========================================================================
    @requires_risk_level(RiskLevel.ANALYTICS_READ)
    async def get_debtors(
        self,
        min_debt: float = 0.0,
        limit: int = 50,
        user_id: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Taxonomy: read.analytics.get_debtors
        Retrieves counterparties with outstanding accounts receivable balances.
        """
        operation_name = "read.analytics.get_debtors"

        async def _exec():
            return await self.adapter.list_accumulation_register(
                "ВзаиморасчетыСКонтрагентами", top=limit
            )

        return await self._execute_with_guards(
            operation_name=operation_name,
            risk_level=RiskLevel.ANALYTICS_READ,
            params={"min_debt": min_debt, "limit": limit},
            executor_func=_exec,
            user_id=user_id,
            dry_run=dry_run,
        )

    # =========================================================================
    # 4. Inventory Balances (L1: ANALYTICS_READ)
    # =========================================================================
    @requires_risk_level(RiskLevel.ANALYTICS_READ)
    async def get_inventory(
        self,
        warehouse: Optional[str] = None,
        limit: int = 50,
        user_id: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Taxonomy: read.warehouse.get_inventory
        Retrieves warehouse stock balances and reserve states.
        """
        operation_name = "read.warehouse.get_inventory"

        async def _exec():
            return await self.adapter.list_accumulation_register(
                "ТоварыНаСкладах", top=limit
            )

        return await self._execute_with_guards(
            operation_name=operation_name,
            risk_level=RiskLevel.ANALYTICS_READ,
            params={"warehouse": warehouse, "limit": limit},
            executor_func=_exec,
            user_id=user_id,
            dry_run=dry_run,
        )
