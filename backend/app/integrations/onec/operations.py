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
from app.integrations.onec.execution import GuardedExecutionPipeline
from app.integrations.onec.output_filter import OneCOutputFilter
from app.integrations.onec.policy import (
    OneCPolicyEnforcer,
    RiskLevel,
    requires_risk_level,
)
from app.repositories.domain_repos import ToolCallRepository
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class OneCOperationsService:
    """
    Executes standard read-only operations against 1C:Enterprise via OneCAdapter.
    Delegates all guard checks, dry-run simulation, execution, output filtering,
    and telemetry logging to the canonical GuardedExecutionPipeline.
    """

    def __init__(
        self,
        client: Optional[OneCClientWrapper] = None,
        policy_enforcer: Optional[OneCPolicyEnforcer] = None,
        audit_service: Optional[AuditService] = None,
        output_filter: Optional[OneCOutputFilter] = None,
        is_mock: bool = False,
        adapter: Optional[OneCAdapter] = None,
        tool_repo: Optional[ToolCallRepository] = None,
    ):
        self.policy = policy_enforcer or OneCPolicyEnforcer()
        self.audit = audit_service
        self.filter = output_filter or OneCOutputFilter()
        self.client = client
        self.tool_repo = tool_repo

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
        Executes operation through the canonical GuardedExecutionPipeline.
        Preserves legacy audit action names ('ONEC_OPERATION_EXECUTED') for backward compatibility.
        """
        pipeline = GuardedExecutionPipeline(
            policy_enforcer=self.policy,
            adapter=self.adapter,
            audit_service=self.audit,
            output_filter=self.filter,
            tool_repo=self.tool_repo,
        )
        return await pipeline.execute(
            operation_name=operation_name,
            risk_level=risk_level,
            params=params,
            executor_func=executor_func,
            user_id=user_id,
            dry_run=dry_run,
            audit_action="ONEC_OPERATION_EXECUTED",
            audit_entity_type="OneCOperation",
            source="http_api",
            close_adapter=True,
        )

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
