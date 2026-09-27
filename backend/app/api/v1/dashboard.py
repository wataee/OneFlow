from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import CurrentUserContext, get_current_user_context
from app.schemas.dashboard import DashboardMetricsResponse
from app.services.task_service import TaskService

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/metrics", response_model=DashboardMetricsResponse)
async def get_metrics(
    current_user: CurrentUserContext = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns aggregated real database metrics for the tenant.
    COUNT ... GROUP BY status executed in SQL, not python loops.
    """
    service = TaskService(db, current_user.organization_id)
    metrics = await service.get_dashboard_metrics()
    return metrics
