import asyncio
import logging
from celery import Celery
from app.core.config import settings

logger = logging.getLogger(__name__)

celery_app = Celery(
    "saas_foundation",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_always_eager=settings.CELERY_TASK_ALWAYS_EAGER,
    task_track_started=True,
    task_time_limit=settings.TASK_PROCESSING_TIMEOUT_SECONDS,
    broker_connection_retry_on_startup=False,
    broker_connection_max_retries=1,
    broker_transport_options={
        "socket_timeout": 1.0,
        "socket_connect_timeout": 1.0,
    },
)


@celery_app.task(name="process_task_job", bind=True, max_retries=settings.MAX_TASK_RETRIES)
def process_task_job(self, task_id: str, organization_id: str):
    """
    Celery background worker job to process a task through the AI pipeline.
    Invokes TaskService.execute_task_pipeline with multi-tenancy enforcement.
    """
    logger.info(f"[Celery] Received task execution request for task_id={task_id}, org_id={organization_id}")

    async def _run():
        from app.core.database import AsyncSessionLocal
        from app.services.task_service import TaskService

        async with AsyncSessionLocal() as session:
            try:
                service = TaskService(session, organization_id)
                res = await service.execute_task_pipeline(task_id)
                await session.commit()
                return {"task_id": task_id, "status": res.status.value if res else "SKIPPED"}
            except Exception as e:
                await session.rollback()
                logger.exception(f"[Celery] Task pipeline execution failure for {task_id}: {e}")
                raise

    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, _run()).result()
        else:
            return asyncio.run(_run())
    except Exception as exc:
        logger.error(f"[Celery] Worker job crashed: {exc}")
        raise self.retry(exc=exc, countdown=10)
