from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import CurrentUserContext, get_current_user_context
from app.models.entities import BusinessRole, Finding, FindingSeverity, FindingStatus, ScanRun, ScanRunStatus, ScanTriggerType
from app.repositories.domain_repos import FindingRepository, ScanRepository
from app.schemas.common import PaginatedResponse
from app.schemas.daily_guard import DailyGuardSummary, FindingResponse, ScanRunResponse
from app.services.audit_service import AuditService
from app.services.daily_guard_service import ActiveScanError, DailyGuardService

router = APIRouter(tags=["Daily Guard"])


@router.get("/findings", response_model=PaginatedResponse[FindingResponse])
async def list_findings(status_filter: Optional[FindingStatus] = Query(None, alias="status"),
    severity: Optional[FindingSeverity] = None, business_role: Optional[BusinessRole] = None,
    rule_code: Optional[str] = None, date_from: Optional[datetime] = None, date_to: Optional[datetime] = None,
    limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
    current_user: CurrentUserContext = Depends(get_current_user_context), db: AsyncSession = Depends(get_db)):
    repo = FindingRepository(db, current_user.organization_id)
    effective_role = business_role or (BusinessRole(current_user.business_role) if current_user.business_role else None)
    items, total = await repo.list_for_organization(limit, offset, status=status_filter, severity=severity,
        business_role=effective_role, rule_code=rule_code, since=date_from, until=date_to)
    return PaginatedResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/findings/summary", response_model=DailyGuardSummary)
async def findings_summary(business_role: Optional[BusinessRole] = None,
    current_user: CurrentUserContext = Depends(get_current_user_context), db: AsyncSession = Depends(get_db)):
    role = business_role or (BusinessRole(current_user.business_role) if current_user.business_role else None)
    filters = [Finding.organization_id == current_user.organization_id,
               Finding.status.in_([FindingStatus.NEW, FindingStatus.OPEN, FindingStatus.ACKNOWLEDGED])]
    if role:
        filters.append(Finding.business_role == role)
    rows = await db.execute(select(Finding.severity, func.count(Finding.id)).where(*filters).group_by(Finding.severity))
    counts = {getattr(sev, "value", sev): n for sev, n in rows.all()}
    runs = ScanRepository(db, current_user.organization_id)
    last, _ = await runs.list(limit=1, order_by=ScanRun.created_at.desc())
    resolved = 0
    if last and last.finished_at:
        stmt = select(func.count(Finding.id)).where(Finding.organization_id == current_user.organization_id,
            Finding.status == FindingStatus.RESOLVED, Finding.resolved_at >= last.finished_at)
        if role:
            stmt = stmt.where(Finding.business_role == role)
        resolved = await db.scalar(stmt) or 0
    return DailyGuardSummary(last_scan=last.finished_at if last else None, status=last.status if last else None,
        errors=counts.get("ERROR", 0) + counts.get("CRITICAL", 0), warnings=counts.get("WARNING", 0),
        info=counts.get("INFO", 0), resolved_since_last_scan=resolved, business_role=role)


@router.get("/findings/{finding_id}", response_model=FindingResponse)
async def get_finding(finding_id: str, current_user: CurrentUserContext = Depends(get_current_user_context),
                      db: AsyncSession = Depends(get_db)):
    item = await FindingRepository(db, current_user.organization_id).get_by_id(finding_id)
    if not item:
        raise HTTPException(404, "Finding not found")
    return item


@router.post("/findings/{finding_id}/acknowledge", response_model=FindingResponse)
async def acknowledge_finding(finding_id: str, current_user: CurrentUserContext = Depends(get_current_user_context),
                              db: AsyncSession = Depends(get_db)):
    repo = FindingRepository(db, current_user.organization_id)
    item = await repo.acknowledge(finding_id, current_user.user_id)
    if not item:
        raise HTTPException(404, "Finding not found")
    if item.status == FindingStatus.RESOLVED:
        raise HTTPException(409, "Resolved findings cannot be acknowledged")
    await AuditService(db, current_user.organization_id).log_event("DAILY_GUARD_FINDING_ACKNOWLEDGED",
        "Finding", item.id, new_values={"status": item.status.value}, user_id=current_user.user_id)
    return item


@router.get("/scans", response_model=PaginatedResponse[ScanRunResponse])
async def list_scans(status_filter: Optional[ScanRunStatus] = Query(None, alias="status"),
    trigger_type: Optional[ScanTriggerType] = None, date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
    current_user: CurrentUserContext = Depends(get_current_user_context), db: AsyncSession = Depends(get_db)):
    stmt = select(ScanRun).where(ScanRun.organization_id == current_user.organization_id)
    if status_filter: stmt = stmt.where(ScanRun.status == status_filter)
    if trigger_type: stmt = stmt.where(ScanRun.trigger_type == trigger_type)
    if date_from: stmt = stmt.where(ScanRun.created_at >= date_from)
    if date_to: stmt = stmt.where(ScanRun.created_at <= date_to)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    result = await db.execute(stmt.order_by(ScanRun.created_at.desc()).limit(limit).offset(offset))
    return PaginatedResponse(items=list(result.scalars().all()), total=total, limit=limit, offset=offset)


@router.get("/scans/{run_id}", response_model=ScanRunResponse)
async def get_scan(run_id: str, current_user: CurrentUserContext = Depends(get_current_user_context),
                   db: AsyncSession = Depends(get_db)):
    run = await ScanRepository(db, current_user.organization_id).get_by_id(run_id)
    if not run: raise HTTPException(404, "Scan not found")
    return run


@router.post("/scans", response_model=ScanRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_scan(current_user: CurrentUserContext = Depends(get_current_user_context),
                      db: AsyncSession = Depends(get_db)):
    if current_user.role.lower() != "admin":
        raise HTTPException(status_code=403, detail="Administrator access is required to start a scan")
    try:
        run = await DailyGuardService(db, current_user.organization_id).start_scan(user_id=current_user.user_id)
        await db.commit()
    except ActiveScanError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    try:
        from app.workers.celery_app import run_daily_guard_scan
        run_daily_guard_scan.delay(run.id, current_user.organization_id)
    except Exception as exc:
        from datetime import timezone
        run.status, run.error_code = ScanRunStatus.FAILED, "QUEUE_UNAVAILABLE"
        run.error_message = "Could not enqueue Daily Guard scan."
        run.finished_at = datetime.now(timezone.utc)
        await AuditService(db, current_user.organization_id).log_event("DAILY_GUARD_SCAN_FAILED", "ScanRun", run.id,
            new_values={"error_code": run.error_code}, user_id=current_user.user_id)
        await db.commit()
        raise HTTPException(status_code=503, detail="Could not enqueue Daily Guard scan")
    return run
