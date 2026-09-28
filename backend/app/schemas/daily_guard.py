from datetime import datetime
from typing import Any, Dict, Optional
from app.models.entities import BusinessRole, FindingSeverity, FindingStatus, ScanRunStatus, ScanTriggerType
from app.schemas.common import BaseSchema


class FindingResponse(BaseSchema):
    id: str
    rule_code: str
    rule_version: str
    status: FindingStatus
    severity: FindingSeverity
    title: str
    description: Optional[str]
    business_role: BusinessRole
    entity_type: Optional[str]
    entity_id: Optional[str]
    fingerprint: str
    evidence: Optional[Dict[str, Any]]
    metadata_json: Optional[Dict[str, Any]]
    first_seen_at: datetime
    last_seen_at: datetime
    resolved_at: Optional[datetime]
    acknowledged_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class ScanRunResponse(BaseSchema):
    id: str
    status: ScanRunStatus
    trigger_type: ScanTriggerType
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    duration_ms: Optional[int]
    rules_total: int
    rules_completed: int
    findings_created: int
    findings_updated: int
    findings_resolved: int
    error_code: Optional[str]
    error_message: Optional[str]
    created_at: datetime


class DailyGuardSummary(BaseSchema):
    last_scan: Optional[datetime]
    status: Optional[ScanRunStatus]
    errors: int
    warnings: int
    info: int
    resolved_since_last_scan: int
    business_role: Optional[BusinessRole]
