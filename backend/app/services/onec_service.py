from typing import Any, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.onec.client import OneCClientWrapper, OneCConfigurationError
from app.integrations.onec.operations import OneCOperationsService
from app.integrations.onec.output_filter import OneCOutputFilter
from app.integrations.onec.policy import OneCPolicyEnforcer, RiskLevel
from app.repositories.domain_repos import UserRepository
from app.services.audit_service import AuditService


class OneCService:
    """
    Application service managing 1C operations for a specific organization tenant.
    Loads tenant 1C configuration, builds policy enforcers, and executes guarded operations.
    """

    def __init__(self, session: AsyncSession, organization_id: str):
        self.session = session
        self.organization_id = organization_id
        self.audit_service = AuditService(session, organization_id)

    async def _get_tenant_config(self) -> Dict[str, Any]:
        from app.models.entities import Organization
        from sqlalchemy import select
        stmt = select(Organization).where(Organization.id == self.organization_id)
        result = await self.session.execute(stmt)
        org = result.scalars().first()
        return (org.onec_config if org else {}) or {}

    async def get_operations_service(self) -> OneCOperationsService:
        tenant_cfg = await self._get_tenant_config()
        
        # Check if real 1C client can be configured
        client: Optional[OneCClientWrapper] = None
        is_mock = False

        try:
            client = OneCClientWrapper.from_tenant_config(tenant_cfg)
        except OneCConfigurationError:
            # When URL is not set in tenant or env, gracefully run in mock/demo mode
            is_mock = True

        policy_enforcer = OneCPolicyEnforcer(
            global_read_only=settings.ONEC_READ_ONLY_MODE,
            max_allowed_risk=RiskLevel(settings.ONEC_MAX_RISK_LEVEL),
            is_tenant_writable=tenant_cfg.get("is_writable", False),
        )

        return OneCOperationsService(
            client=client,
            policy_enforcer=policy_enforcer,
            audit_service=self.audit_service,
            output_filter=OneCOutputFilter(default_max_rows=settings.ONEC_OUTPUT_MAX_ROWS),
            is_mock=is_mock,
        )

    async def check_health(self, user_id: Optional[str] = None) -> Dict[str, Any]:
        op_service = await self.get_operations_service()
        return await op_service.health_check(user_id=user_id)

    async def get_unposted_documents(
        self, doc_type: str = "ПлатежноеПоручениеИсходящее", limit: int = 50, user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        op_service = await self.get_operations_service()
        return await op_service.get_unposted_documents(doc_type=doc_type, limit=limit, user_id=user_id)

    async def get_debtors(
        self, min_debt: float = 0.0, limit: int = 50, user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        op_service = await self.get_operations_service()
        return await op_service.get_debtors(min_debt=min_debt, limit=limit, user_id=user_id)

    async def get_inventory(
        self, warehouse: Optional[str] = None, limit: int = 50, user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        op_service = await self.get_operations_service()
        return await op_service.get_inventory(warehouse=warehouse, limit=limit, user_id=user_id)
