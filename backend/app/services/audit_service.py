from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import AuditLog
from app.repositories.domain_repos import AuditRepository


class AuditService:
    def __init__(self, session: AsyncSession, organization_id: str):
        self.session = session
        self.organization_id = organization_id
        self.repo = AuditRepository(session, organization_id)

    async def log_event(
        self,
        action: str,
        entity_type: str,
        entity_id: str,
        old_values: Optional[Dict[str, Any]] = None,
        new_values: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> AuditLog:
        """
        Creates an immutable audit log entry.
        """
        entry = AuditLog(
            organization_id=self.organization_id,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            old_values=old_values,
            new_values=new_values,
        )
        return await self.repo.create(entry)

    @asynccontextmanager
    async def audit_context(
        self,
        action: str,
        entity_type: str,
        entity_id: str,
        old_values: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Context manager to capture state change for audit logging.
        Yields a dict that callers can populate with new_values.
        """
        context_data: Dict[str, Any] = {"new_values": None}
        yield context_data
        await self.log_event(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            old_values=old_values,
            new_values=context_data.get("new_values"),
            user_id=user_id,
        )
