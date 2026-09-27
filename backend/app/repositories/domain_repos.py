from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy import func, select, update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import (
    AuditLog,
    FileMetadata,
    Organization,
    ReviewStatus,
    ReviewTask,
    Task,
    TaskStatus,
    ToolCall,
    User,
)
from app.repositories.base import BaseRepository, MultiTenantViolationError


class TaskRepository(BaseRepository[Task]):
    model_cls = Task

    async def claim_for_processing(self, task_id: str) -> Optional[Task]:
        """
        Idempotent atomic state transition PENDING -> PROCESSING.
        Ensures AI task is never dispatched/processed twice if another worker already claimed it.
        """
        now = datetime.now(timezone.utc)
        stmt = (
            sa_update(Task)
            .where(
                Task.id == str(task_id),
                Task.organization_id == self.organization_id,
                Task.status == TaskStatus.PENDING,
            )
            .values(status=TaskStatus.PROCESSING, updated_at=now)
            .returning(Task)
        )
        result = await self.session.execute(stmt)
        task = result.scalars().first()
        if task:
            await self.session.flush()
        return task

    async def get_dashboard_metrics(self) -> Dict[str, int]:
        """
        Database aggregation query:
        Uses SQL COUNT(*) GROUP BY status for the tenant.
        No row-by-row fetching in Python!
        """
        stmt = (
            select(Task.status, func.count(Task.id))
            .where(Task.organization_id == self.organization_id)
            .group_by(Task.status)
        )
        result = await self.session.execute(stmt)
        status_counts = dict(result.all())

        # Count tasks automated without human intervention:
        # COMPLETED tasks that never had a ReviewTask
        auto_stmt = (
            select(func.count(Task.id))
            .where(
                Task.organization_id == self.organization_id,
                Task.status == TaskStatus.COMPLETED,
                ~select(ReviewTask.id)
                .where(
                    ReviewTask.task_id == Task.id,
                    ReviewTask.organization_id == self.organization_id
                )
                .exists()
            )
        )
        auto_result = await self.session.execute(auto_stmt)
        automated_count = auto_result.scalar_one() or 0

        pending = status_counts.get(TaskStatus.PENDING, 0)
        processing = status_counts.get(TaskStatus.PROCESSING, 0)
        in_review = status_counts.get(TaskStatus.REVIEW, 0)
        completed = status_counts.get(TaskStatus.COMPLETED, 0)
        failed = status_counts.get(TaskStatus.FAILED, 0)
        total = pending + processing + in_review + completed + failed

        return {
            "total_tasks": total,
            "pending": pending,
            "processing": processing,
            "in_review": in_review,
            "completed": completed,
            "failed": failed,
            "automated_without_human": automated_count,
        }


class ReviewRepository(BaseRepository[ReviewTask]):
    model_cls = ReviewTask

    async def get_by_task_id(self, task_id: str) -> Optional[ReviewTask]:
        stmt = self._apply_tenant_filter(
            select(ReviewTask).where(ReviewTask.task_id == str(task_id))
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_pending_review_by_task_id(self, task_id: str) -> Optional[ReviewTask]:
        stmt = self._apply_tenant_filter(
            select(ReviewTask).where(
                ReviewTask.task_id == str(task_id),
                ReviewTask.status == ReviewStatus.PENDING
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()


class AuditRepository(BaseRepository[AuditLog]):
    model_cls = AuditLog

    async def update(self, entity_id: str, **kwargs) -> Optional[AuditLog]:
        raise NotImplementedError("Audit logs are strictly append-only and immutable. Updates are forbidden.")

    async def delete(self, entity_id: str) -> bool:
        raise NotImplementedError("Audit logs are strictly append-only and immutable. Deletions are forbidden.")


class FileRepository(BaseRepository[FileMetadata]):
    model_cls = FileMetadata

    async def list(
        self,
        limit: int = 50,
        offset: int = 0,
        filters: Optional[Dict[str, Any]] = None,
        include_deleted: bool = False,
        order_by=None
    ) -> Tuple[List[FileMetadata], int]:
        stmt = select(FileMetadata)
        stmt = self._apply_tenant_filter(stmt)

        if not include_deleted:
            stmt = stmt.where(FileMetadata.deleted_at.is_(None))

        if filters:
            for field_name, value in filters.items():
                if value is not None and hasattr(FileMetadata, field_name):
                    stmt = stmt.where(getattr(FileMetadata, field_name) == value)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar_one()

        if order_by is not None:
            stmt = stmt.order_by(order_by)
        else:
            stmt = stmt.order_by(FileMetadata.created_at.desc())

        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def soft_delete(self, file_id: str) -> Optional[FileMetadata]:
        now = datetime.now(timezone.utc)
        stmt = (
            sa_update(FileMetadata)
            .where(
                FileMetadata.id == str(file_id),
                FileMetadata.organization_id == self.organization_id,
                FileMetadata.deleted_at.is_(None)
            )
            .values(deleted_at=now)
            .returning(FileMetadata)
        )
        result = await self.session.execute(stmt)
        updated = result.scalars().first()
        if updated:
            await self.session.flush()
        return updated

    async def delete(self, entity_id: str) -> bool:
        # Default delete is routed to soft_delete
        result = await self.soft_delete(entity_id)
        return result is not None


class UserRepository(BaseRepository[User]):
    model_cls = User

    async def get_by_email(self, email: str) -> Optional[User]:
        stmt = self._apply_tenant_filter(
            select(User).where(User.email == email.lower())
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()


class AuthGlobalRepository:
    """
    Unscoped repository used ONLY during initial authentication/registration
    prior to tenant identification.
    """
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_user_by_email(self, email: str) -> Optional[User]:
        stmt = select(User).where(User.email == email.lower())
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def create_organization(self, name: str) -> Organization:
        org = Organization(name=name)
        self.session.add(org)
        await self.session.flush()
        await self.session.refresh(org)
        return org

    async def create_user(
        self,
        organization_id: str,
        email: str,
        hashed_password: str,
        full_name: str,
        role: str = "admin",
    ) -> User:
        user = User(
            organization_id=organization_id,
            email=email.lower(),
            hashed_password=hashed_password,
            full_name=full_name,
            role=role,
        )
        self.session.add(user)
        await self.session.flush()
        await self.session.refresh(user)
        return user


class ToolCallRepository(BaseRepository[ToolCall]):
    """
    Tenant-scoped repository for tool execution logs and history.
    """
    model_cls = ToolCall

    async def log_call(
        self,
        tool_name: str,
        risk_level: str,
        params: Dict[str, Any],
        status: str,
        is_dry_run: bool = False,
        latency_ms: Optional[int] = None,
        error: Optional[str] = None,
        error_code: Optional[str] = None,
        user_id: Optional[str] = None,
        request_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        result_payload: Optional[Dict[str, Any]] = None,
    ) -> ToolCall:
        record = ToolCall(
            organization_id=self.organization_id,
            user_id=user_id,
            tool_name=tool_name,
            risk_level=risk_level,
            is_dry_run=is_dry_run,
            params=params,
            status=status,
            error=error,
            error_code=error_code,
            latency_ms=latency_ms,
            request_id=request_id,
            idempotency_key=idempotency_key,
            result_payload=result_payload,
        )
        return await self.create(record)

    async def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> Optional[ToolCall]:
        stmt = (
            select(ToolCall)
            .where(
                ToolCall.organization_id == self.organization_id,
                ToolCall.idempotency_key == idempotency_key,
            )
            .order_by(ToolCall.created_at.desc())
        )
        res = await self.session.execute(stmt)
        return res.scalars().first()

    async def claim_in_flight(
        self,
        tool_name: str,
        risk_level: str,
        params: Dict[str, Any],
        idempotency_key: str,
        request_id: str,
        user_id: Optional[str] = None,
    ) -> ToolCall:
        record = ToolCall(
            organization_id=self.organization_id,
            user_id=user_id,
            tool_name=tool_name,
            risk_level=risk_level,
            is_dry_run=False,
            params=params,
            status="RUNNING",
            request_id=request_id,
            idempotency_key=idempotency_key,
        )
        self.session.add(record)
        await self.session.flush()
        return record

    async def list_recent_calls(
        self,
        limit: int = 50,
        tool_name: Optional[str] = None,
        is_dry_run: Optional[bool] = None,
    ) -> List[ToolCall]:
        stmt = (
            select(ToolCall)
            .where(ToolCall.organization_id == self.organization_id)
            .order_by(ToolCall.created_at.desc())
            .limit(limit)
        )
        if tool_name:
            stmt = stmt.where(ToolCall.tool_name == tool_name)
        if is_dry_run is not None:
            stmt = stmt.where(ToolCall.is_dry_run == is_dry_run)
        res = await self.session.execute(stmt)
        return list(res.scalars().all())

