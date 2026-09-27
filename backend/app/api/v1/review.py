from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import CurrentUserContext, get_current_user_context
from app.models.entities import ReviewStatus
from app.schemas.common import PaginatedResponse
from app.schemas.review import ReviewDecisionRequest, ReviewTaskResponse
from app.services.review_service import (
    ReviewAlreadyResolvedError,
    ReviewNotFoundError,
    ReviewService,
)

router = APIRouter(prefix="/reviews", tags=["Human Review"])


@router.get("/", response_model=PaginatedResponse[ReviewTaskResponse])
async def list_reviews(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    status: Optional[ReviewStatus] = Query(None),
    current_user: CurrentUserContext = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_db),
):
    service = ReviewService(db, current_user.organization_id)
    items, total = await service.list_reviews(limit=limit, offset=offset, status=status)
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{review_id}", response_model=ReviewTaskResponse)
async def get_review(
    review_id: str,
    current_user: CurrentUserContext = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_db),
):
    service = ReviewService(db, current_user.organization_id)
    try:
        return await service.get_review(review_id)
    except ReviewNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/{review_id}/decision", response_model=ReviewTaskResponse)
async def submit_decision(
    review_id: str,
    req: ReviewDecisionRequest,
    current_user: CurrentUserContext = Depends(get_current_user_context),
    db: AsyncSession = Depends(get_db),
):
    service = ReviewService(db, current_user.organization_id)
    try:
        return await service.resolve_review(
            review_id=review_id,
            user_id=current_user.user_id,
            decision=req.decision,
            rejection_reason=req.rejection_reason,
            edited_value=req.edited_value,
        )
    except (ReviewNotFoundError, ReviewAlreadyResolvedError, ValueError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
