from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.integrations.storage.factory import get_storage_backend
from app.integrations.storage.validator import validate_file_content
from app.models.entities import FileMetadata
from app.repositories.domain_repos import FileRepository, TaskRepository
from app.services.audit_service import AuditService


class FileNotFoundError(Exception):
    pass


class FileService:
    def __init__(self, session: AsyncSession, organization_id: str):
        self.session = session
        self.organization_id = organization_id
        self.repo = FileRepository(session, organization_id)
        self.task_repo = TaskRepository(session, organization_id)
        self.storage = get_storage_backend()
        self.audit = AuditService(session, organization_id)

    async def list_files(
        self,
        limit: int = 50,
        offset: int = 0,
        task_id: Optional[str] = None,
        include_deleted: bool = False,
    ) -> Tuple[List[FileMetadata], int]:
        filters: Dict[str, Any] = {}
        if task_id is not None:
            filters["task_id"] = task_id
        return await self.repo.list(
            limit=limit, offset=offset, filters=filters, include_deleted=include_deleted
        )

    async def upload_file(
        self,
        filename: str,
        file_bytes: bytes,
        task_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> FileMetadata:
        # Validate task belongs to this organization if provided
        if task_id:
            task = await self.task_repo.get_by_id(task_id)
            if not task:
                raise ValueError(f"Target task {task_id} does not exist in this organization.")

        # 1. Content validation by magic bytes (not just extension!)
        _, detected_mime = validate_file_content(
            file_bytes=file_bytes,
            filename=filename,
            max_size_bytes=settings.MAX_UPLOAD_SIZE_BYTES,
        )

        # 2. Persist to storage backend
        stored_path = await self.storage.save(
            file_bytes=file_bytes,
            filename=filename,
            organization_id=self.organization_id,
        )

        # 3. Create metadata entry
        meta = FileMetadata(
            organization_id=self.organization_id,
            task_id=task_id,
            filename=filename,
            stored_path=stored_path,
            mime_type=detected_mime,
            size_bytes=len(file_bytes),
        )
        saved_meta = await self.repo.create(meta)

        # 4. Audit
        await self.audit.log_event(
            action="FILE_UPLOADED",
            entity_type="FileMetadata",
            entity_id=saved_meta.id,
            new_values={
                "filename": filename,
                "mime_type": detected_mime,
                "size_bytes": len(file_bytes),
                "task_id": task_id,
            },
            user_id=user_id,
        )

        return saved_meta

    async def get_file_content(self, file_id: str) -> Tuple[FileMetadata, bytes]:
        meta = await self.repo.get_by_id(file_id)
        if not meta or meta.deleted_at is not None:
            raise FileNotFoundError(f"File {file_id} not found.")

        content = await self.storage.get(meta.stored_path)
        return meta, content

    async def soft_delete_file(self, file_id: str, user_id: Optional[str] = None) -> FileMetadata:
        meta = await self.repo.get_by_id(file_id)
        if not meta or meta.deleted_at is not None:
            raise FileNotFoundError(f"File {file_id} not found.")

        updated = await self.repo.soft_delete(file_id)
        await self.audit.log_event(
            action="FILE_SOFT_DELETED",
            entity_type="FileMetadata",
            entity_id=file_id,
            old_values={"deleted_at": None},
            new_values={"deleted_at": str(updated.deleted_at)},
            user_id=user_id,
        )
        return updated
