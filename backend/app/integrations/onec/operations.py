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
    Executes standard read-only operations against 1C:Enterprise.
    Ensures policy compliance, immutable audit logging, and output redaction.
    """

    def __init__(
        self,
        client: Optional[OneCClientWrapper],
        policy_enforcer: OneCPolicyEnforcer,
        audit_service: AuditService,
        output_filter: Optional[OneCOutputFilter] = None,
        is_mock: bool = False,
    ):
        self.client = client
        self.policy = policy_enforcer
        self.audit = audit_service
        self.filter = output_filter or OneCOutputFilter()
        self.is_mock = is_mock or (client is None)

    async def _execute_with_guards(
        self,
        operation_name: str,
        risk_level: RiskLevel,
        params: Dict[str, Any],
        executor_func,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Core template method ensuring:
        1. Security policy check (throws PolicyViolationError if blocked)
        2. Execution (real 1C or mock fallback)
        3. Output filtering (IIN/BIN masking & row limit)
        4. Immutable audit logging
        """
        # 1. Enforce policy
        self.policy.verify_or_raise(operation_name, risk_level)

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
            # 4. Record event in immutable audit log
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

        # 3. Filter and sanitize sensitive fields
        sanitized_data, is_truncated = self.filter.filter_result(raw_result)

        return {
            "operation": operation_name,
            "risk_level": risk_level.value,
            "data": sanitized_data,
            "is_truncated": is_truncated,
            "is_mock": self.is_mock,
        }

    # =========================================================================
    # 1. Healthcheck / System Status (L0: SAFE_READ)
    # =========================================================================
    @requires_risk_level(RiskLevel.SAFE_READ)
    async def health_check(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Taxonomy: read.system.health_check
        Checks availability of 1C OData service.
        """
        operation_name = "read.system.health_check"

        async def _exec():
            if self.is_mock or not self.client:
                return {
                    "status": "connected",
                    "infobase_version": "8.3.24.1548",
                    "configuration": "Бухгалтерия для Казахстана, ред. 3.0",
                    "latency_ms": 14.2,
                }
            meta = await self.client.get_metadata()
            return {"status": "connected", "metadata_received": bool(meta)}

        return await self._execute_with_guards(
            operation_name=operation_name,
            risk_level=RiskLevel.SAFE_READ,
            params={},
            executor_func=_exec,
            user_id=user_id,
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
    ) -> Dict[str, Any]:
        """
        Taxonomy: read.documents.get_unposted
        Fetches unposted draft documents requiring accountant review.
        """
        operation_name = "read.documents.get_unposted"

        async def _exec():
            if self.is_mock or not self.client:
                # Deterministic mock reflecting typical KZ accounting unposted drafts
                return [
                    {
                        "Ref_Key": "00000000-0000-0000-0001-000000000001",
                        "Number": "KZ-000142",
                        "Date": "2026-09-25T14:30:00",
                        "Posted": False,
                        "СуммаДокумента": 1250000,
                        "Контрагент": "ТОО Сарыарка Энерджи",
                        "Контрагент_БИН": "080140012345",  # Will be masked by output_filter
                        "НазначениеПлатежа": "Оплата по счету №441/26 за электроэнергию",
                    },
                    {
                        "Ref_Key": "00000000-0000-0000-0001-000000000002",
                        "Number": "KZ-000143",
                        "Date": "2026-09-26T10:15:00",
                        "Posted": False,
                        "СуммаДокумента": 480000,
                        "Контрагент": "ИП Касымов Д.А.",
                        "Контрагент_ИИН": "850412350789",  # Will be masked by output_filter
                        "НазначениеПлатежа": "Транспортные услуги согласно акту",
                    },
                ]

            # In real 1C: filter where Posted eq false
            filter_expr = F("Posted") == False
            return await self.client.list_document(doc_type, top=limit, filter_expr=filter_expr)

        return await self._execute_with_guards(
            operation_name=operation_name,
            risk_level=RiskLevel.SAFE_READ,
            params={"doc_type": doc_type, "limit": limit},
            executor_func=_exec,
            user_id=user_id,
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
    ) -> Dict[str, Any]:
        """
        Taxonomy: read.analytics.get_debtors
        Retrieves counterparties with outstanding accounts receivable balances.
        """
        operation_name = "read.analytics.get_debtors"

        async def _exec():
            if self.is_mock or not self.client:
                return [
                    {
                        "counterparty": "ТОО Базис Металл",
                        "bin": "981240001122",  # Will be masked
                        "debt_amount_kzt": 3450000.0,
                        "overdue_days": 18,
                        "contract": "Договор поставки № 12/25",
                        "iban": "KZ449988112233445566",  # Will be masked
                    },
                    {
                        "counterparty": "АО Астана Финанс Групп",
                        "bin": "050340008899",  # Will be masked
                        "debt_amount_kzt": 890000.50,
                        "overdue_days": 4,
                        "contract": "Договор лизинга № 88-Л",
                        "iban": "KZ120011223344556677",  # Will be masked
                    },
                ]

            # In real 1C: query accumulation register "ВзаиморасчетыСКонтрагентами_Balance"
            return await self.client.list_accumulation_register(
                "ВзаиморасчетыСКонтрагентами", top=limit
            )

        return await self._execute_with_guards(
            operation_name=operation_name,
            risk_level=RiskLevel.ANALYTICS_READ,
            params={"min_debt": min_debt, "limit": limit},
            executor_func=_exec,
            user_id=user_id,
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
    ) -> Dict[str, Any]:
        """
        Taxonomy: read.warehouse.get_inventory
        Retrieves warehouse stock balances and reserve states.
        """
        operation_name = "read.warehouse.get_inventory"

        async def _exec():
            if self.is_mock or not self.client:
                return [
                    {
                        "sku": "ITEM-KZ-001",
                        "name": "Кабель силовой ВВГнг 3x2.5",
                        "warehouse": warehouse or "Центральный склад Алматы",
                        "quantity": 1450.0,
                        "unit": "м",
                        "reserved": 200.0,
                        "available": 1250.0,
                    },
                    {
                        "sku": "ITEM-KZ-002",
                        "name": "Автоматический выключатель 16A",
                        "warehouse": warehouse or "Центральный склад Алматы",
                        "quantity": 84.0,
                        "unit": "шт",
                        "reserved": 0.0,
                        "available": 84.0,
                    },
                ]

            return await self.client.list_accumulation_register(
                "ТоварыНаСкладах", top=limit
            )

        return await self._execute_with_guards(
            operation_name=operation_name,
            risk_level=RiskLevel.ANALYTICS_READ,
            params={"warehouse": warehouse, "limit": limit},
            executor_func=_exec,
            user_id=user_id,
        )
