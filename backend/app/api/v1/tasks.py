from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import CurrentUserContext, get_current_user_context
from app.models.entities import TaskStatus, TaskType  # Only enum types from entities for query params
from app.schemas.common import PaginatedResponse
from app.schemas.tasks import TaskCreateRequest, TaskResponse
from app.services.task_service import (
    InvalidStateTransitionError,
    TaskNotFoundError,
    TaskService,
)

router = APIRouter(prefix="/tasks", tags=["Tasks"])


@router.post("/", response_model=TaskResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_task(
    req: TaskCreateRequest,
    current_user: CurrentUserContext = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_db),
):
    service = TaskService(db, current_user.organization_id)
    created = await service.create_task(
        task_type=req.type,
        input_data=req.input_data,
        user_id=current_user.user_id,
    )
    return created


@router.get("/", response_model=PaginatedResponse[TaskResponse])
async def list_tasks(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: Optional[TaskStatus] = Query(None),
    task_type: Optional[TaskType] = Query(None),
    current_user: CurrentUserContext = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_db),
):
    service = TaskService(db, current_user.organization_id)
    items, total = await service.list_tasks(
        limit=limit,
        offset=offset,
        status=status,
        task_type=task_type,
    )
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    current_user: CurrentUserContext = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_db),
):
    service = TaskService(db, current_user.organization_id)
    try:
        return await service.get_task(task_id)
    except TaskNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/{task_id}/retry", response_model=TaskResponse)
async def retry_task(
    task_id: str,
    current_user: CurrentUserContext = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_db),
):
    service = TaskService(db, current_user.organization_id)
    try:
        return await service.retry_task(task_id, user_id=current_user.user_id)
    except (TaskNotFoundError, InvalidStateTransitionError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{task_id}/execute-sync", response_model=TaskResponse)
async def execute_task_synchronously(
    task_id: str,
    current_user: CurrentUserContext = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_db),
):
    """
    Test/Verification endpoint: runs the task processing pipeline synchronously
    without relying on an external Celery worker process.
    """
    service = TaskService(db, current_user.organization_id)
    task = await service.execute_task_pipeline(task_id)
    if not task:
        # If already claimed or processed, retrieve current state
        task = await service.get_task(task_id)
    return task
