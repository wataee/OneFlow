import asyncio
import logging
from celery import Celery
from celery.schedules import crontab
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

try:
    _hour, _minute = (int(part) for part in settings.DAILY_GUARD_SCAN_TIME.split(":"))
except (TypeError, ValueError):
    raise ValueError("DAILY_GUARD_SCAN_TIME must use UTC HH:MM format")
if not (0 <= _hour <= 23 and 0 <= _minute <= 59):
    raise ValueError("DAILY_GUARD_SCAN_TIME must use UTC HH:MM format")
celery_app.conf.beat_schedule = {
    "daily-guard-scan-dispatch": {
        "task": "dispatch_daily_guard_scans",
        "schedule": crontab(hour=_hour, minute=_minute),
    }
}


@celery_app.task(name="run_daily_guard_scan")
def run_daily_guard_scan(run_id: str, organization_id: str):
    async def _run():
        from app.core.database import AsyncSessionLocal
        from app.services.daily_guard_service import DailyGuardService
        async with AsyncSessionLocal() as session:
            service = DailyGuardService(session, organization_id)
            run = await service.execute_scan(run_id)
            await session.commit()
            return {"scan_id": run_id, "status": run.status.value if run else "MISSING"}
    return asyncio.run(_run())


@celery_app.task(name="dispatch_daily_guard_scans")
def dispatch_daily_guard_scans():
    async def _dispatch():
        from sqlalchemy import select
        from app.core.database import AsyncSessionLocal
        from app.core.config import settings as app_settings
        from app.models.entities import Organization, User
        from app.services.daily_guard_service import ActiveScanError, DailyGuardService
        scheduled = []
        async with AsyncSessionLocal() as session:
            organizations = (await session.execute(select(Organization).where(
                select(User.id).where(User.organization_id == Organization.id, User.is_active.is_(True)).exists()
            ))).scalars().all()
            for org in organizations:
                cfg = org.onec_config or {}
                if not app_settings.DEMO_MODE and not (cfg.get("base_url") or app_settings.ONEC_ODATA_URL):
                    continue
                try:
                    run = await DailyGuardService(session, org.id).start_scan(ScanTriggerType.SCHEDULED)
                    await session.commit()
                    scheduled.append((run.id, org.id))
                except ActiveScanError:
                    await session.rollback()
        for run_id, org_id in scheduled:
            try:
                run_daily_guard_scan.delay(run_id, org_id)
            except Exception:
                logger.exception("Unable to enqueue scheduled Daily Guard scan %s", run_id)
                async with AsyncSessionLocal() as session:
                    from datetime import datetime, timezone
                    from app.models.entities import ScanRun, ScanRunStatus
                    from app.services.audit_service import AuditService
                    run = await session.scalar(select(ScanRun).where(
                        ScanRun.id == run_id, ScanRun.organization_id == org_id))
                    if run:
                        run.status, run.error_code = ScanRunStatus.FAILED, "QUEUE_UNAVAILABLE"
                        run.error_message = "Could not enqueue scheduled Daily Guard scan."
                        run.finished_at = datetime.now(timezone.utc)
                        await AuditService(session, org_id).log_event("DAILY_GUARD_SCAN_FAILED", "ScanRun", run.id,
                            new_values={"error_code": run.error_code})
                        await session.commit()
        return {"scheduled": len(scheduled)}
    from app.models.entities import ScanTriggerType
    return asyncio.run(_dispatch())


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
