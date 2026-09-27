"""
Tenant 1C Connection Management Application Service.
Provides CRUD and validation for per-tenant 1C OData connection credentials,
safely encrypting passwords and preventing SSRF attacks.
"""

import logging
from typing import Any, Dict, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import encrypt_onec_credential
from app.integrations.onec.adapter import MockAdapter, ODataAdapter
from app.integrations.onec.client import OneCClientWrapper, OneCConfigurationError
from app.integrations.onec.policy import RiskLevel
from app.integrations.onec.ssrf import SSRFValidationError, validate_onec_base_url
from app.models.entities import Organization
from app.schemas.onec_connection import (
    OneCConnectionStatus,
    OneCConnectionUpdate,
    OneCTestConnectionRequest,
)
from app.services.audit_service import AuditService
from app.services.onec_service import OneCService

logger = logging.getLogger(__name__)


class OneCConnectionService:
    def __init__(self, session: AsyncSession, organization_id: str):
        self.session = session
        self.organization_id = organization_id
        self.audit_service = AuditService(session, organization_id)

    async def _get_org(self) -> Organization:
        stmt = select(Organization).where(Organization.id == self.organization_id)
        res = await self.session.execute(stmt)
        org = res.scalars().first()
        if not org:
            raise ValueError(f"Organization '{self.organization_id}' not found.")
        return org

    async def get_connection_status(self) -> OneCConnectionStatus:
        org = await self._get_org()
        cfg = org.onec_config or {}

        base_url = cfg.get("base_url") or settings.ONEC_ODATA_URL
        username = cfg.get("username") or settings.ONEC_USERNAME
        is_writable = cfg.get("is_writable", False)
        is_configured = bool(base_url)
        is_mock = not is_configured

        return OneCConnectionStatus(
            base_url=base_url,
            username=username,
            is_writable=is_writable,
            is_configured=is_configured,
            is_mock=is_mock,
            max_onec_risk_level=org.max_onec_risk_level,
        )

    async def update_connection(
        self, data: OneCConnectionUpdate, user_id: Optional[str] = None
    ) -> OneCConnectionStatus:
        # 1. SSRF URL validation
        sanitized_url = validate_onec_base_url(data.base_url)

        # 2. Risk ceiling validation
        if data.max_onec_risk_level:
            try:
                RiskLevel(data.max_onec_risk_level)
            except ValueError:
                raise ValueError(
                    f"Invalid max_onec_risk_level '{data.max_onec_risk_level}'. "
                    f"Must be one of: {[r.value for r in RiskLevel]}"
                )

        org = await self._get_org()
        existing_cfg = org.onec_config or {}

        # 3. Encrypt password or preserve existing
        encrypted_password: Optional[str] = None
        if data.password:
            encrypted_password = encrypt_onec_credential(data.password)
        elif "password" in existing_cfg:
            encrypted_password = existing_cfg["password"]

        new_cfg: Dict[str, Any] = {
            "base_url": sanitized_url,
            "username": data.username,
            "password": encrypted_password,
            "is_writable": data.is_writable,
        }

        old_values = {
            "base_url": existing_cfg.get("base_url"),
            "username": existing_cfg.get("username"),
            "is_writable": existing_cfg.get("is_writable"),
            "max_onec_risk_level": org.max_onec_risk_level,
        }

        org.onec_config = new_cfg
        org.max_onec_risk_level = data.max_onec_risk_level

        self.session.add(org)
        await self.session.flush()

        # 4. Record audit event (password is strictly masked/omitted)
        audit_new_values = {
            "base_url": sanitized_url,
            "username": data.username,
            "is_writable": data.is_writable,
            "has_password": bool(encrypted_password),
            "max_onec_risk_level": data.max_onec_risk_level,
        }
        await self.audit_service.log_event(
            action="ONEC_CONNECTION_UPDATED",
            entity_type="Organization",
            entity_id=org.id,
            old_values=old_values,
            new_values=audit_new_values,
            user_id=user_id,
        )

        return OneCConnectionStatus(
            base_url=sanitized_url,
            username=data.username,
            is_writable=data.is_writable,
            is_configured=True,
            is_mock=False,
            max_onec_risk_level=data.max_onec_risk_level,
        )

    async def test_connection(self, req: OneCTestConnectionRequest) -> Dict[str, Any]:
        """
        Executes a health check test against provided or saved 1C credentials.
        Does not persist configuration.
        """
        if req.base_url:
            # Validate URL against SSRF
            sanitized_url = validate_onec_base_url(req.base_url)
            client = OneCClientWrapper(
                base_url=sanitized_url,
                username=req.username,
                password=req.password,
                timeout=10.0,
            )
            adapter = ODataAdapter(client)
            try:
                return await adapter.health_check()
            finally:
                await adapter.close()
        else:
            onec_svc = OneCService(self.session, self.organization_id)
            return await onec_svc.check_health()
