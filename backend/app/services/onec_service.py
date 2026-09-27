from typing import Any, Dict, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decrypt_onec_credential
from app.integrations.onec.adapter import MockAdapter, ODataAdapter
from app.integrations.onec.client import OneCClientWrapper, OneCConfigurationError
from app.integrations.onec.operations import OneCOperationsService
from app.integrations.onec.output_filter import OneCOutputFilter
from app.integrations.onec.policy import OneCPolicyEnforcer, RiskLevel
from app.services.audit_service import AuditService


class OneCService:
    """
    Application service managing 1C operations for a specific organization tenant.
    Loads tenant 1C configuration, decrypts credentials, constructs policy enforcers,
    and executes guarded operations.
    """

    def __init__(self, session: AsyncSession, organization_id: str):
        self.session = session
        self.organization_id = organization_id
        self.audit_service = AuditService(session, organization_id)

    async def _get_tenant_record(self) -> Tuple[Dict[str, Any], Optional[str]]:
        from app.models.entities import Organization
        from sqlalchemy import select
        stmt = select(Organization).where(Organization.id == self.organization_id)
        result = await self.session.execute(stmt)
        org = result.scalars().first()
        if not org:
            return {}, None
        cfg = dict(org.onec_config or {})
        # Decrypt password if stored encrypted
        if "password" in cfg and cfg["password"]:
            cfg["password"] = decrypt_onec_credential(cfg["password"])
        max_risk = getattr(org, "max_onec_risk_level", None)
        return cfg, max_risk

    async def get_operations_service(self) -> OneCOperationsService:
        tenant_cfg, max_risk_str = await self._get_tenant_record()

        client: Optional[OneCClientWrapper] = None
        adapter = None

        try:
            client = OneCClientWrapper.from_tenant_config(tenant_cfg)
            adapter = ODataAdapter(client)
        except OneCConfigurationError:
            adapter = MockAdapter()

        org_max_risk = RiskLevel(max_risk_str) if max_risk_str else None

        policy_enforcer = OneCPolicyEnforcer(
            global_read_only=settings.ONEC_READ_ONLY_MODE,
            max_allowed_risk=RiskLevel(settings.ONEC_MAX_RISK_LEVEL),
            is_tenant_writable=tenant_cfg.get("is_writable", False),
            org_max_risk_level=org_max_risk,
        )

        return OneCOperationsService(
            client=client,
            policy_enforcer=policy_enforcer,
            audit_service=self.audit_service,
            output_filter=OneCOutputFilter(default_max_rows=settings.ONEC_OUTPUT_MAX_ROWS),
            adapter=adapter,
        )

    async def check_health(self, user_id: Optional[str] = None, dry_run: bool = False) -> Dict[str, Any]:
        op_service = await self.get_operations_service()
        try:
            return await op_service.health_check(user_id=user_id, dry_run=dry_run)
        finally:
            if op_service.adapter:
                await op_service.adapter.close()

    async def get_unposted_documents(
        self,
        doc_type: str = "ПлатежноеПоручениеИсходящее",
        limit: int = 50,
        user_id: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        op_service = await self.get_operations_service()
        try:
            return await op_service.get_unposted_documents(
                doc_type=doc_type, limit=limit, user_id=user_id, dry_run=dry_run
            )
        finally:
            if op_service.adapter:
                await op_service.adapter.close()

    async def get_debtors(
        self,
        min_debt: float = 0.0,
        limit: int = 50,
        user_id: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        op_service = await self.get_operations_service()
        try:
            return await op_service.get_debtors(
                min_debt=min_debt, limit=limit, user_id=user_id, dry_run=dry_run
            )
        finally:
            if op_service.adapter:
                await op_service.adapter.close()

    async def get_inventory(
        self,
        warehouse: Optional[str] = None,
        limit: int = 50,
        user_id: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        op_service = await self.get_operations_service()
        try:
            return await op_service.get_inventory(
                warehouse=warehouse, limit=limit, user_id=user_id, dry_run=dry_run
            )
        finally:
            if op_service.adapter:
                await op_service.adapter.close()
