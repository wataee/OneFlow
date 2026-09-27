from typing import Any, Dict, Generic, List, Optional, Tuple, Type, TypeVar
from sqlalchemy import func, select, update as sa_update, delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import Base

ModelT = TypeVar("ModelT", bound=Base)


class MultiTenantViolationError(Exception):
    """Raised when an operation attempts to bypass multi-tenancy isolation."""
    pass


class BaseRepository(Generic[ModelT]):
    """
    Strict multi-tenant base repository.
    Enforces that every database operation has a non-nullable organization_id filter.
    """
    model_cls: Type[ModelT]

    def __init__(self, session: AsyncSession, organization_id: str):
        if not organization_id or not str(organization_id).strip():
            raise MultiTenantViolationError(
                "Multi-tenancy violation: organization_id is strictly mandatory for all repository operations."
            )
        self.session = session
        self.organization_id = str(organization_id)

    def _apply_tenant_filter(self, query):
        """Ensures the query is unconditionally scoped to this organization."""
        if not hasattr(self.model_cls, "organization_id"):
            raise MultiTenantViolationError(
                f"Model {self.model_cls.__name__} does not have an organization_id attribute."
            )
        return query.where(self.model_cls.organization_id == self.organization_id)

    async def get_by_id(self, entity_id: str) -> Optional[ModelT]:
        stmt = self._apply_tenant_filter(
            select(self.model_cls).where(self.model_cls.id == str(entity_id))
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list(
        self,
        limit: int = 50,
        offset: int = 0,
        filters: Optional[Dict[str, Any]] = None,
        order_by=None
    ) -> Tuple[List[ModelT], int]:
        stmt = select(self.model_cls)
        stmt = self._apply_tenant_filter(stmt)

        if filters:
            for field_name, value in filters.items():
                if value is not None and hasattr(self.model_cls, field_name):
                    stmt = stmt.where(getattr(self.model_cls, field_name) == value)

        # Count total items for this tenant
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar_one()

        if order_by is not None:
            stmt = stmt.order_by(order_by)
        elif hasattr(self.model_cls, "created_at"):
            stmt = stmt.order_by(getattr(self.model_cls, "created_at").desc())

        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def create(self, entity: ModelT) -> ModelT:
        if not hasattr(entity, "organization_id"):
            raise MultiTenantViolationError(
                f"Cannot persist entity {self.model_cls.__name__} without organization_id."
            )
        # Force organization_id to repository's bound tenant
        entity.organization_id = self.organization_id
        self.session.add(entity)
        await self.session.flush()
        await self.session.refresh(entity)
        return entity

    async def update(self, entity_id: str, **kwargs) -> Optional[ModelT]:
        # Disallow updating organization_id across tenants
        kwargs.pop("organization_id", None)

        stmt = (
            sa_update(self.model_cls)
            .where(
                self.model_cls.id == str(entity_id),
                self.model_cls.organization_id == self.organization_id
            )
            .values(**kwargs)
            .returning(self.model_cls)
        )
        result = await self.session.execute(stmt)
        updated = result.scalars().first()
        if updated:
            await self.session.flush()
        return updated

    async def delete(self, entity_id: str) -> bool:
        stmt = (
            sa_delete(self.model_cls)
            .where(
                self.model_cls.id == str(entity_id),
                self.model_cls.organization_id == self.organization_id
            )
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount > 0
