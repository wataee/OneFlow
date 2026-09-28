import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.daily_guard.registry import rule_registry
from app.daily_guard.rules import register_demo_rules
from app.daily_guard.models import ScanContext
from app.models.entities import Finding, FindingStatus, ScanRun, ScanRunStatus, ScanTriggerType
from app.repositories.domain_repos import FindingRepository, ScanRepository
from app.services.audit_service import AuditService
from app.services.onec_service import OneCService

logger = logging.getLogger("app.daily_guard")
register_demo_rules(rule_registry)


class ActiveScanError(Exception):
    pass


class DailyGuardService:
    def __init__(self, session, organization_id: str):
        self.session, self.organization_id = session, str(organization_id)
        self.findings = FindingRepository(session, organization_id)
        self.scans = ScanRepository(session, organization_id)
        self.audit = AuditService(session, organization_id)

    async def start_scan(self, trigger_type=ScanTriggerType.MANUAL, user_id: Optional[str] = None):
        if await self.scans.get_active():
            raise ActiveScanError("A Daily Guard scan is already pending or running for this organization")
        run = ScanRun(organization_id=self.organization_id, trigger_type=trigger_type, triggered_by=user_id)
        try:
            await self.scans.create(run)
        except IntegrityError as exc:
            await self.session.rollback()
            raise ActiveScanError("A Daily Guard scan is already pending or running for this organization") from exc
        await self.audit.log_event("DAILY_GUARD_SCAN_QUEUED", "ScanRun", run.id,
                                   new_values={"trigger_type": trigger_type.value}, user_id=user_id)
        await self.session.flush()
        return run

    async def execute_scan(self, run_id: str):
        claim = await self.session.execute(update(ScanRun).where(
            ScanRun.id == run_id, ScanRun.organization_id == self.organization_id,
            ScanRun.status == ScanRunStatus.PENDING).values(
                status=ScanRunStatus.RUNNING, started_at=datetime.now(timezone.utc)).returning(ScanRun.id))
        if claim.scalar_one_or_none() is None:
            return await self.scans.get_by_id(run_id)
        await self.session.flush()
        run = await self.scans.get_by_id(run_id)
        start = time.monotonic()
        await self.audit.log_event("DAILY_GUARD_SCAN_STARTED", "ScanRun", run.id,
                                   new_values={"worker_claimed": True}, user_id=run.triggered_by)
        rules = rule_registry.list()
        run.rules_total = len(rules)
        onec = OneCService(self.session, self.organization_id)
        context = ScanContext(self.organization_id, run.id, self.session, onec_service=onec,
                              user_id=run.triggered_by, logger=logger)
        try:
            candidates = []
            completed_codes = set()
            for rule in rules:
                results = await rule.check(context)
                completed_codes.add(rule.code)
                candidates.extend((rule, candidate) for candidate in results)
                run.rules_completed += 1

            seen = set()
            for rule, candidate in candidates:
                identity = {"organization_id": self.organization_id, "rule_code": candidate.rule_code,
                            "entity_type": candidate.entity_type, "entity_id": candidate.entity_id,
                            "attributes": candidate.fingerprint_seed}
                fingerprint = hashlib.sha256(json.dumps(identity, sort_keys=True, default=str,
                    separators=(",", ":")).encode()).hexdigest()
                seen.add(fingerprint)
                now = datetime.now(timezone.utc)
                item, created, reopened = await self.findings.upsert_by_fingerprint(candidate, fingerprint, now)
                if not created:
                    run.findings_updated += 1
                    if reopened:
                        await self.audit.log_event("DAILY_GUARD_FINDING_REOPENED", "Finding", item.id,
                                                   new_values={"status": "OPEN"})
                else:
                    run.findings_created += 1
                    await self.audit.log_event("DAILY_GUARD_FINDING_CREATED", "Finding", item.id,
                        new_values={"rule_code": item.rule_code, "severity": item.severity.value})

            existing, _ = await self.findings.list_for_organization(limit=10000)
            for item in existing:
                if item.rule_code in completed_codes and item.status != FindingStatus.RESOLVED and item.fingerprint not in seen:
                    await self.findings.resolve(item.id, datetime.now(timezone.utc))
                    run.findings_resolved += 1
                    await self.audit.log_event("DAILY_GUARD_FINDING_RESOLVED", "Finding", item.id,
                        new_values={"status": "RESOLVED", "scan_run_id": run.id})

            run.status = ScanRunStatus.COMPLETED
            run.finished_at = datetime.now(timezone.utc)
            run.duration_ms = int((time.monotonic() - start) * 1000)
            await self.session.flush()
            await self.audit.log_event("DAILY_GUARD_SCAN_COMPLETED", "ScanRun", run.id,
                new_values={"rules_completed": run.rules_completed, "findings_created": run.findings_created,
                            "findings_updated": run.findings_updated, "findings_resolved": run.findings_resolved},
                user_id=run.triggered_by)
            return run
        except Exception as exc:
            logger.exception("Daily Guard scan failed: %s", exc)
            await self.session.rollback()
            run = await self.scans.get_by_id(run_id)
            if run:
                run.status, run.finished_at = ScanRunStatus.FAILED, datetime.now(timezone.utc)
                run.duration_ms = int((time.monotonic() - start) * 1000)
                run.error_code = "SCAN_EXECUTION_FAILED"
                run.error_message = "Daily Guard scan failed. Check server logs for details."
                await self.audit.log_event("DAILY_GUARD_SCAN_FAILED", "ScanRun", run.id,
                    new_values={"error_code": run.error_code, "error_message": run.error_message}, user_id=run.triggered_by)
                await self.session.flush()
            return run
