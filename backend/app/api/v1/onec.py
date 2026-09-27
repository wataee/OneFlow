from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import CurrentUserContext, get_current_user_context
from app.integrations.onec.policy import PolicyViolationError
from app.services.onec_service import OneCService

router = APIRouter(prefix="/onec", tags=["1C:Enterprise Integration"])


@router.get("/health")
async def onec_health_check(
    current_user: CurrentUserContext = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_db),
):
    service = OneCService(db, current_user.organization_id)
    try:
        return await service.check_health(user_id=current_user.user_id)
    except PolicyViolationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))


@router.get("/unposted")
async def get_unposted_documents(
    doc_type: str = Query("ПлатежноеПоручениеИсходящее"),
    limit: int = Query(50, ge=1, le=100),
    current_user: CurrentUserContext = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_db),
):
    service = OneCService(db, current_user.organization_id)
    try:
        return await service.get_unposted_documents(doc_type=doc_type, limit=limit, user_id=current_user.user_id)
    except PolicyViolationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))


@router.get("/debtors")
async def get_debtors(
    min_debt: float = Query(0.0, ge=0.0),
    limit: int = Query(50, ge=1, le=100),
    current_user: CurrentUserContext = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_db),
):
    service = OneCService(db, current_user.organization_id)
    try:
        return await service.get_debtors(min_debt=min_debt, limit=limit, user_id=current_user.user_id)
    except PolicyViolationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))


@router.get("/inventory")
async def get_inventory(
    warehouse: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    current_user: CurrentUserContext = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_db),
):
    service = OneCService(db, current_user.organization_id)
    try:
        return await service.get_inventory(warehouse=warehouse, limit=limit, user_id=current_user.user_id)
    except PolicyViolationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e))
