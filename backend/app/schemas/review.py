from datetime import datetime
from typing import Any, Dict, Optional
from app.models.entities import ReviewDecision, ReviewStatus
from app.schemas.common import BaseSchema


class ReviewDecisionRequest(BaseSchema):
    decision: ReviewDecision
    rejection_reason: Optional[str] = None
    edited_value: Optional[Dict[str, Any]] = None


class ReviewTaskResponse(BaseSchema):
    id: str
    organization_id: str
    task_id: str
    status: ReviewStatus
    ai_result: Dict[str, Any]
    proposed_changes: Optional[Dict[str, Any]] = None
    user_decision: Optional[ReviewDecision] = None
    rejection_reason: Optional[str] = None
    decided_by: Optional[str] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None
