from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import CurrentUserContext, get_current_user_context
from app.schemas.audit import AuditLogResponse
from app.schemas.common import PaginatedResponse
from app.services.audit_service import AuditService

router = APIRouter(prefix="/audit", tags=["Audit Log"])


@router.get("/", response_model=PaginatedResponse[AuditLogResponse])
async def list_audit_logs(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    entity_type: Optional[str] = Query(None),
    current_user: CurrentUserContext = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_db),
):
    service = AuditService(db, current_user.organization_id)
    filters = {}
    if entity_type:
        filters["entity_type"] = entity_type
    items, total = await service.repo.list(limit=limit, offset=offset, filters=filters)
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)
