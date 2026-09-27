import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.factory import get_ai_provider
from app.ai.schemas import AIProcessInput
from app.core.config import settings
from app.models.entities import ReviewStatus, ReviewTask, Task, TaskStatus, TaskType
from app.repositories.domain_repos import ReviewRepository, TaskRepository
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)


class InvalidStateTransitionError(Exception):
    pass


class TaskNotFoundError(Exception):
    pass


ALLOWED_TRANSITIONS: Dict[TaskStatus, Set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.PROCESSING},
    TaskStatus.PROCESSING: {TaskStatus.REVIEW, TaskStatus.COMPLETED, TaskStatus.FAILED},
    TaskStatus.REVIEW: {TaskStatus.COMPLETED, TaskStatus.FAILED},
    TaskStatus.FAILED: {TaskStatus.PENDING},  # Retry path
    TaskStatus.COMPLETED: set(),  # Terminal state
}


def validate_transition(current_status: TaskStatus, target_status: TaskStatus, retry_count: int = 0) -> None:
    if target_status not in ALLOWED_TRANSITIONS.get(current_status, set()):
        raise InvalidStateTransitionError(
            f"Invalid transition from {current_status.value} to {target_status.value}. "
            f"Allowed next states: {[s.value for s in ALLOWED_TRANSITIONS.get(current_status, set())]}"
        )
    if current_status == TaskStatus.FAILED and target_status == TaskStatus.PENDING:
        if retry_count >= settings.MAX_TASK_RETRIES:
            raise InvalidStateTransitionError(
                f"Maximum retry limit ({settings.MAX_TASK_RETRIES}) reached. Cannot transition back to PENDING."
            )


class TaskService:
    def __init__(self, session: AsyncSession, organization_id: str):
        self.session = session
        self.organization_id = organization_id
        self.repo = TaskRepository(session, organization_id)
        self.review_repo = ReviewRepository(session, organization_id)
        self.audit = AuditService(session, organization_id)

    async def get_task(self, task_id: str) -> Task:
        task = await self.repo.get_by_id(task_id)
        if not task:
            raise TaskNotFoundError(f"Task {task_id} not found in current organization.")
        return task

    async def list_tasks(
        self,
        limit: int = 50,
        offset: int = 0,
        status: Optional[TaskStatus] = None,
        task_type: Optional[TaskType] = None,
    ) -> Tuple[List[Task], int]:
        filters: Dict[str, Any] = {}
        if status is not None:
            filters["status"] = status
        if task_type is not None:
            filters["type"] = task_type
        return await self.repo.list(limit=limit, offset=offset, filters=filters)

    async def get_dashboard_metrics(self) -> Dict[str, int]:
        return await self.repo.get_dashboard_metrics()

    async def create_task(
        self,
        task_type: TaskType,
        input_data: Dict[str, Any],
        user_id: Optional[str] = None,
    ) -> Task:
        task = Task(
            organization_id=self.organization_id,
            type=task_type,
            status=TaskStatus.PENDING,
            input_data=input_data,
            retry_count=0,
        )
        created_task = await self.repo.create(task)

        # Audit creation
        await self.audit.log_event(
            action="TASK_CREATED",
            entity_type="Task",
            entity_id=created_task.id,
            new_values={
                "type": created_task.type.value,
                "status": created_task.status.value,
                "input_data": input_data,
            },
            user_id=user_id,
        )

        # Dispatch async Celery worker non-blockingly
        import threading
        from app.workers.celery_app import process_task_job

        def _dispatch():
            try:
                process_task_job.delay(created_task.id, self.organization_id)
            except Exception as e:
                logger.warning(
                    f"Celery dispatch failed (broker might be offline in local dev): {e}. "
                    "Task remains PENDING and can be processed via worker or eager executor."
                )

        threading.Thread(target=_dispatch, daemon=True).start()

        return created_task

    async def execute_task_pipeline(self, task_id: str) -> Optional[Task]:
        """
        Idempotent worker execution logic:
        1. Atomically claims task if PENDING (no duplicate AI calls!).
        2. Executes AIProvider.process().
        3. Evaluates confidence against settings.REVIEW_CONFIDENCE_THRESHOLD.
        4. Transitions to REVIEW (if low confidence) or COMPLETED.
        5. Handles errors and retries gracefully.
        """
        # 1. Atomic claim: ensures only one worker executes the AI call
        task = await self.repo.claim_for_processing(task_id)
        if not task:
            logger.info(
                f"Task {task_id} could not be claimed (already processing or not in PENDING status). Skipping."
            )
            return None

        old_status = TaskStatus.PENDING
        await self.audit.log_event(
            action="TASK_STARTED_PROCESSING",
            entity_type="Task",
            entity_id=task.id,
            old_values={"status": old_status.value},
            new_values={"status": TaskStatus.PROCESSING.value},
        )

        try:
            # 2. Invoke AI Provider
            ai_provider = get_ai_provider()
            ai_input = AIProcessInput(
                task_type=task.type.value,
                payload=task.input_data or {},
            )
            ai_result = await ai_provider.process(ai_input)

            # 3. Confidence threshold evaluation (Configurable via env REVIEW_CONFIDENCE_THRESHOLD)
            task.confidence = ai_result.confidence

            if ai_result.confidence < settings.REVIEW_CONFIDENCE_THRESHOLD:
                # Transition to REVIEW and create ReviewTask
                validate_transition(TaskStatus.PROCESSING, TaskStatus.REVIEW)
                task.status = TaskStatus.REVIEW
                task.output_data = None  # Pending human review approval

                review_task = ReviewTask(
                    organization_id=self.organization_id,
                    task_id=task.id,
                    status=ReviewStatus.PENDING,
                    ai_result=ai_result.data,
                )
                await self.review_repo.create(review_task)

                await self.audit.log_event(
                    action="TASK_SENT_TO_REVIEW",
                    entity_type="Task",
                    entity_id=task.id,
                    old_values={"status": TaskStatus.PROCESSING.value},
                    new_values={
                        "status": TaskStatus.REVIEW.value,
                        "confidence": ai_result.confidence,
                        "threshold": settings.REVIEW_CONFIDENCE_THRESHOLD,
                        "review_task_id": review_task.id,
                    },
                )
            else:
                # Direct automated completion
                validate_transition(TaskStatus.PROCESSING, TaskStatus.COMPLETED)
                task.status = TaskStatus.COMPLETED
                task.output_data = ai_result.data

                await self.audit.log_event(
                    action="TASK_COMPLETED_AUTOMATICALLY",
                    entity_type="Task",
                    entity_id=task.id,
                    old_values={"status": TaskStatus.PROCESSING.value},
                    new_values={
                        "status": TaskStatus.COMPLETED.value,
                        "confidence": ai_result.confidence,
                        "output_data": ai_result.data,
                    },
                )

            await self.session.commit()
            return task

        except Exception as exc:
            logger.exception(f"Error processing task {task_id}: {exc}")
            task.error = str(exc)
            validate_transition(TaskStatus.PROCESSING, TaskStatus.FAILED)
            task.status = TaskStatus.FAILED
            await self.session.commit()

            await self.audit.log_event(
                action="TASK_FAILED",
                entity_type="Task",
                entity_id=task.id,
                old_values={"status": TaskStatus.PROCESSING.value},
                new_values={"status": TaskStatus.FAILED.value, "error": str(exc)},
            )
            return task

    async def retry_task(self, task_id: str, user_id: Optional[str] = None) -> Task:
        """Retries a failed task if retry limit is not exceeded."""
        task = await self.get_task(task_id)
        validate_transition(task.status, TaskStatus.PENDING, task.retry_count)

        task.status = TaskStatus.PENDING
        task.retry_count += 1
        task.error = None
        task.output_data = None
        task.updated_at = datetime.now(timezone.utc)

        await self.session.commit()

        await self.audit.log_event(
            action="TASK_RETRIED",
            entity_type="Task",
            entity_id=task.id,
            new_values={"status": TaskStatus.PENDING.value, "retry_count": task.retry_count},
            user_id=user_id,
        )

        from app.workers.celery_app import process_task_job
        try:
            process_task_job.delay(task.id, self.organization_id)
        except Exception as e:
            logger.warning(f"Celery dispatch failed on retry: {e}")

        return task
