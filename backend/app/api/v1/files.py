from typing import Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import CurrentUserContext, get_current_user_context
from app.integrations.storage.validator import FileValidationError
from app.schemas.common import PaginatedResponse
from app.schemas.files import FileMetadataResponse
from app.services.file_service import FileNotFoundError as ServiceFileNotFoundError, FileService

router = APIRouter(prefix="/files", tags=["Files"])


@router.post("/upload", response_model=FileMetadataResponse, status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile = File(...),
    task_id: Optional[str] = Form(None),
    current_user: CurrentUserContext = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_db),
):
    service = FileService(db, current_user.organization_id)
    try:
        content = await file.read()
        saved = await service.upload_file(
            filename=file.filename or "uploaded_file",
            file_bytes=content,
            task_id=task_id,
            user_id=current_user.user_id,
        )
        return saved
    except FileValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/", response_model=PaginatedResponse[FileMetadataResponse])
async def list_files(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    task_id: Optional[str] = Query(None),
    include_deleted: bool = Query(False),
    current_user: CurrentUserContext = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_db),
):
    service = FileService(db, current_user.organization_id)
    items, total = await service.list_files(
        limit=limit,
        offset=offset,
        task_id=task_id,
        include_deleted=include_deleted,
    )
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{file_id}/download")
async def download_file(
    file_id: str,
    current_user: CurrentUserContext = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_db),
):
    service = FileService(db, current_user.organization_id)
    try:
        meta, content = await service.get_file_content(file_id)
        return Response(
            content=content,
            media_type=meta.mime_type,
            headers={
                "Content-Disposition": f'attachment; filename="{meta.filename}"'
            },
        )
    except ServiceFileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.delete("/{file_id}", response_model=FileMetadataResponse)
async def delete_file(
    file_id: str,
    current_user: CurrentUserContext = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_db),
):
    service = FileService(db, current_user.organization_id)
    try:
        return await service.soft_delete_file(file_id, user_id=current_user.user_id)
    except ServiceFileNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
