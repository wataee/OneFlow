from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import ReviewDecision, ReviewStatus, ReviewTask, TaskStatus
from app.repositories.domain_repos import ReviewRepository, TaskRepository
from app.services.audit_service import AuditService
from app.services.task_service import validate_transition


class ReviewNotFoundError(Exception):
    pass


class ReviewAlreadyResolvedError(Exception):
    pass


def compute_dict_diff(old_dict: Dict[str, Any], new_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Computes key-level diff between AI result and human edited value
    for retraining and audit analytics.
    """
    diff: Dict[str, Any] = {}
    all_keys = set(old_dict.keys()) | set(new_dict.keys())

    for k in all_keys:
        old_val = old_dict.get(k)
        new_val = new_dict.get(k)
        if k not in old_dict:
            diff[k] = {"action": "added", "new": new_val}
        elif k not in new_dict:
            diff[k] = {"action": "removed", "old": old_val}
        elif old_val != new_val:
            diff[k] = {"action": "modified", "old": old_val, "new": new_val}

    return diff


class ReviewService:
    def __init__(self, session: AsyncSession, organization_id: str):
        self.session = session
        self.organization_id = organization_id
        self.review_repo = ReviewRepository(session, organization_id)
        self.task_repo = TaskRepository(session, organization_id)
        self.audit = AuditService(session, organization_id)

    async def list_reviews(
        self,
        limit: int = 50,
        offset: int = 0,
        status: Optional[ReviewStatus] = None
    ) -> Tuple[List[ReviewTask], int]:
        filters = {}
        if status is not None:
            filters["status"] = status
        return await self.review_repo.list(limit=limit, offset=offset, filters=filters)

    async def get_review(self, review_id: str) -> ReviewTask:
        review = await self.review_repo.get_by_id(review_id)
        if not review:
            raise ReviewNotFoundError(f"Review {review_id} not found.")
        return review

    async def resolve_review(
        self,
        review_id: str,
        user_id: str,
        decision: ReviewDecision,
        rejection_reason: Optional[str] = None,
        edited_value: Optional[Dict[str, Any]] = None,
    ) -> ReviewTask:
        review = await self.get_review(review_id)
        if review.status == ReviewStatus.RESOLVED:
            raise ReviewAlreadyResolvedError(f"Review {review_id} has already been resolved.")

        task = await self.task_repo.get_by_id(review.task_id)
        if not task:
            raise ReviewNotFoundError(f"Underlying task {review.task_id} not found.")

        now = datetime.now(timezone.utc)
        review.decided_by = user_id
        review.resolved_at = now
        review.user_decision = decision
        review.status = ReviewStatus.RESOLVED

        if decision == ReviewDecision.APPROVE:
            validate_transition(task.status, TaskStatus.COMPLETED)
            task.output_data = review.ai_result
            task.status = TaskStatus.COMPLETED

            await self.audit.log_event(
                action="REVIEW_APPROVED",
                entity_type="ReviewTask",
                entity_id=review.id,
                old_values={"task_status": TaskStatus.REVIEW.value},
                new_values={
                    "task_status": TaskStatus.COMPLETED.value,
                    "decision": decision.value,
                    "output_data": task.output_data,
                },
                user_id=user_id,
            )

        elif decision == ReviewDecision.REJECT:
            validate_transition(task.status, TaskStatus.FAILED)
            task.status = TaskStatus.FAILED
            task.error = rejection_reason or "Rejected by human reviewer"
            review.rejection_reason = task.error

            await self.audit.log_event(
                action="REVIEW_REJECTED",
                entity_type="ReviewTask",
                entity_id=review.id,
                old_values={"task_status": TaskStatus.REVIEW.value},
                new_values={
                    "task_status": TaskStatus.FAILED.value,
                    "decision": decision.value,
                    "reason": task.error,
                },
                user_id=user_id,
            )

        elif decision == ReviewDecision.EDIT:
            if edited_value is None:
                raise ValueError("edited_value must be provided when decision is EDIT.")

            validate_transition(task.status, TaskStatus.COMPLETED)
            diff = compute_dict_diff(review.ai_result, edited_value)
            review.proposed_changes = edited_value
            task.output_data = edited_value
            task.status = TaskStatus.COMPLETED

            await self.audit.log_event(
                action="REVIEW_EDITED",
                entity_type="ReviewTask",
                entity_id=review.id,
                old_values={
                    "task_status": TaskStatus.REVIEW.value,
                    "ai_result": review.ai_result,
                },
                new_values={
                    "task_status": TaskStatus.COMPLETED.value,
                    "decision": decision.value,
                    "edited_value": edited_value,
                    "diff": diff,
                },
                user_id=user_id,
            )

        await self.session.commit()
        await self.session.refresh(review)
        await self.session.refresh(task)
        return review
