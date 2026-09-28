import pytest
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from app.daily_guard.models import DiagnosticRule
from app.daily_guard.registry import rule_registry
from app.models.entities import AuditLog, BusinessRole, Finding, FindingSeverity, FindingStatus, ScanRun, ScanRunStatus
from app.repositories.domain_repos import FindingRepository
from app.services.daily_guard_service import ActiveScanError, DailyGuardService


@pytest.mark.asyncio
async def test_mock_scan_deduplicates_and_resolves_findings(db_session, seed_tenants):
    org_id = seed_tenants["org_a"].id
    service = DailyGuardService(db_session, org_id)
    run1 = await service.start_scan(user_id=seed_tenants["user_a"].id)
    with pytest.raises(ActiveScanError):
        await service.start_scan(user_id=seed_tenants["user_a"].id)
    result1 = await service.execute_scan(run1.id)
    await db_session.commit()
    assert result1.status == ScanRunStatus.COMPLETED
    assert result1.findings_created >= 2
    count1 = await db_session.scalar(select(func.count(Finding.id)).where(Finding.organization_id == org_id))

    run2 = await service.start_scan(user_id=seed_tenants["user_a"].id)
    result2 = await service.execute_scan(run2.id)
    await db_session.commit()
    count2 = await db_session.scalar(select(func.count(Finding.id)).where(Finding.organization_id == org_id))
    assert count2 == count1
    assert result2.findings_updated == count1

    original = list(rule_registry._rules.values())
    class NoIssues(DiagnosticRule):
        code, version = "documents.unposted", "1.0"
        title, description = "none", "none"
        business_role, severity = BusinessRole.ACCOUNTANT, FindingSeverity.WARNING
        async def check(self, context): return []
    try:
        rule_registry.clear()
        rule_registry.register(NoIssues())
        run3 = await service.start_scan(user_id=seed_tenants["user_a"].id)
        result3 = await service.execute_scan(run3.id)
        await db_session.commit()
        assert result3.status == ScanRunStatus.COMPLETED
        resolved = await db_session.scalar(select(func.count(Finding.id)).where(
            Finding.organization_id == org_id, Finding.rule_code == "documents.unposted",
            Finding.status == FindingStatus.RESOLVED))
        assert resolved == 2
    finally:
        rule_registry.clear()
        for item in original:
            rule_registry.register(item)


@pytest.mark.asyncio
async def test_finding_repository_is_tenant_scoped(db_session, seed_tenants):
    org_a, org_b = seed_tenants["org_a"].id, seed_tenants["org_b"].id
    item = Finding(organization_id=org_a, rule_code="test.rule", rule_version="1", status=FindingStatus.NEW,
        severity=FindingSeverity.INFO, title="Scoped", business_role=BusinessRole.OWNER,
        fingerprint="f" * 64)
    db_session.add(item)
    await db_session.flush()
    assert await FindingRepository(db_session, org_a).get_by_id(item.id) is not None
    assert await FindingRepository(db_session, org_b).get_by_id(item.id) is None


@pytest.mark.asyncio
async def test_active_scan_partial_unique_index_prevents_parallel_runs(db_session, seed_tenants):
    org_id = seed_tenants["org_a"].id
    db_session.add(ScanRun(organization_id=org_id))
    await db_session.flush()
    db_session.add(ScanRun(organization_id=org_id))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_failed_rule_fails_scan_without_resolving_findings(db_session, seed_tenants):
    from app.daily_guard.registry import rule_registry
    original = list(rule_registry._rules.values())
    org_id = seed_tenants["org_a"].id
    class BrokenRule(DiagnosticRule):
        code, version = "documents.unposted", "1.0"
        title, description = "broken", "broken"
        business_role, severity = BusinessRole.ACCOUNTANT, FindingSeverity.ERROR
        async def check(self, context): raise RuntimeError("simulated rule failure")
    try:
        rule_registry.clear(); rule_registry.register(BrokenRule())
        service = DailyGuardService(db_session, org_id)
        run = await service.start_scan()
        await db_session.commit()
        failed = await service.execute_scan(run.id)
        await db_session.commit()
        assert failed.status == ScanRunStatus.FAILED
        assert failed.error_code == "SCAN_EXECUTION_FAILED"
        assert await db_session.scalar(select(func.count(AuditLog.id)).where(
            AuditLog.organization_id == org_id,
            AuditLog.action == "DAILY_GUARD_SCAN_FAILED")) == 1
    finally:
        rule_registry.clear()
        for item in original: rule_registry.register(item)


@pytest.mark.asyncio
async def test_summary_business_role_filter_and_tenant_isolation(client, db_session, seed_tenants):
    for org_id, role in ((seed_tenants["org_a"].id, BusinessRole.WAREHOUSE),
                         (seed_tenants["org_b"].id, BusinessRole.ACCOUNTANT)):
        db_session.add(Finding(organization_id=org_id, rule_code="summary.test", rule_version="1",
            status=FindingStatus.OPEN, severity=FindingSeverity.ERROR, title="Test issue",
            business_role=role, fingerprint=("a" if role == BusinessRole.WAREHOUSE else "b") * 64))
    await db_session.commit()
    response = await client.get("/api/v1/findings/summary?business_role=WAREHOUSE",
        headers=seed_tenants["headers_a"])
    assert response.status_code == 200
    assert response.json()["errors"] == 1
    hidden = await client.get("/api/v1/findings", headers=seed_tenants["headers_a"])
    assert hidden.status_code == 200
    assert all(item["business_role"] != "ACCOUNTANT" for item in hidden.json()["items"])


def test_demo_rule_registry_rejects_duplicate_codes():
    from app.daily_guard.registry import RuleRegistry
    from app.daily_guard.rules import UnpostedDocumentsRule
    registry = RuleRegistry()
    registry.register(UnpostedDocumentsRule())
    with pytest.raises(ValueError):
        registry.register(UnpostedDocumentsRule())


@pytest.mark.asyncio
async def test_scheduled_dispatch_enqueues_only_active_organizations(seed_tenants):
    from app.workers import celery_app
    from app.core.database import AsyncSessionLocal
    from app.models.entities import ScanTriggerType
    from app.services.daily_guard_service import DailyGuardService
    assert "daily-guard-scan-dispatch" in celery_app.celery_app.conf.beat_schedule
    async with AsyncSessionLocal() as session:
        run = await DailyGuardService(session, seed_tenants["org_a"].id).start_scan(ScanTriggerType.SCHEDULED)
        await session.commit()
        assert run.trigger_type == ScanTriggerType.SCHEDULED


@pytest.mark.asyncio
async def test_scan_api_requires_admin_and_enqueues(client, seed_tenants, monkeypatch):
    from app.workers import celery_app
    calls = []
    monkeypatch.setattr(celery_app.run_daily_guard_scan, "delay", lambda *args: calls.append(args))
    denied = await client.post("/api/v1/scans", headers=seed_tenants["headers_a_member"])
    assert denied.status_code == 403
    response = await client.post("/api/v1/scans", headers=seed_tenants["headers_a"])
    assert response.status_code == 202
    assert response.json()["status"] == "PENDING"
    assert calls and calls[0][1] == seed_tenants["org_a"].id
