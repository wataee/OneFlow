from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import (
    CurrentUserContext,
    get_current_user_context,
    require_admin,
)
from app.integrations.onec.ssrf import SSRFValidationError
from app.schemas.onec_connection import (
    OneCConnectionStatus,
    OneCConnectionUpdate,
    OneCTestConnectionRequest,
)
from app.services.onec_connection_service import OneCConnectionService

router = APIRouter(prefix="/onec-connection", tags=["1C Connection Management"])


@router.get("", response_model=OneCConnectionStatus)
async def get_connection_status(
    current_user: CurrentUserContext = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns current organization 1C connection status without revealing sensitive secrets.
    Accessible to any authenticated user in the tenant organization.
    """
    service = OneCConnectionService(db, current_user.organization_id)
    return await service.get_connection_status()


@router.put("", response_model=OneCConnectionStatus)
async def update_connection(
    data: OneCConnectionUpdate,
    current_user: CurrentUserContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Updates organization 1C connection configuration.
    Encrypts password and validates URL against SSRF threats.
    Restricted strictly to organization administrators (require_admin).
    """
    service = OneCConnectionService(db, current_user.organization_id)
    try:
        return await service.update_connection(data, user_id=current_user.user_id)
    except SSRFValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/test-connection")
async def test_connection(
    req: OneCTestConnectionRequest,
    current_user: CurrentUserContext = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """
    Tests 1C OData connectivity with provided or saved configuration.
    Restricted to organization administrators.
    """
    service = OneCConnectionService(db, current_user.organization_id)
    try:
        return await service.test_connection(req)
    except SSRFValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"1C connection test failed: {str(e)}",
        )
