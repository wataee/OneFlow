import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Index,
    JSON,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# Universal JSON type: PostgreSQL JSONB if available, otherwise standard JSON
JSONType = JSON().with_variant(JSONB, "postgresql")
UUIDType = String(36).with_variant(PG_UUID(as_uuid=True), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    USER = "user"


class BusinessRole(str, enum.Enum):
    ACCOUNTANT = "ACCOUNTANT"
    WAREHOUSE = "WAREHOUSE"
    PROCUREMENT = "PROCUREMENT"
    MANAGER = "MANAGER"
    OWNER = "OWNER"


class FindingStatus(str, enum.Enum):
    NEW = "NEW"
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class FindingSeverity(str, enum.Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class ScanRunStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ScanTriggerType(str, enum.Enum):
    MANUAL = "MANUAL"
    SCHEDULED = "SCHEDULED"


class TaskType(str, enum.Enum):
    DOCUMENT_PROCESSING = "DOCUMENT_PROCESSING"
    NOMENCLATURE_MATCHING = "NOMENCLATURE_MATCHING"
    BANK_OPERATION = "BANK_OPERATION"
    WAREHOUSE_RECONCILIATION = "WAREHOUSE_RECONCILIATION"
    TOOL_APPROVAL = "TOOL_APPROVAL"



class TaskStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    REVIEW = "REVIEW"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ReviewStatus(str, enum.Enum):
    PENDING = "PENDING"
    RESOLVED = "RESOLVED"


class ReviewDecision(str, enum.Enum):
    APPROVE = "approve"
    REJECT = "reject"
    EDIT = "edit"


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(
        UUIDType, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Per-tenant 1C OData configuration (base_url, credentials, is_writable, etc.)
    onec_config: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONType, nullable=True)
    # Organization-level maximum allowed risk ceiling (overrides global if stricter)
    max_onec_risk_level: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    users: Mapped[List["User"]] = relationship(
        "User", back_populates="organization", cascade="all, delete-orphan"
    )
    tasks: Mapped[List["Task"]] = relationship(
        "Task", back_populates="organization", cascade="all, delete-orphan"
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        UUIDType, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    organization_id: Mapped[str] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False), default=UserRole.USER, nullable=False
    )
    business_role: Mapped[Optional[BusinessRole]] = mapped_column(
        Enum(BusinessRole, native_enum=False), default=None, nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    organization: Mapped["Organization"] = relationship("Organization", back_populates="users")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(
        UUIDType, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    organization_id: Mapped[str] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[TaskType] = mapped_column(
        Enum(TaskType, native_enum=False), nullable=False, index=True
    )
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, native_enum=False), default=TaskStatus.PENDING, nullable=False, index=True
    )
    input_data: Mapped[Dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    output_data: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONType, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Documented range: float 0.0 - 1.0 representing model/heuristic prediction confidence
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    organization: Mapped["Organization"] = relationship("Organization", back_populates="tasks")
    review_tasks: Mapped[List["ReviewTask"]] = relationship(
        "ReviewTask", back_populates="task", cascade="all, delete-orphan"
    )
    files: Mapped[List["FileMetadata"]] = relationship(
        "FileMetadata", back_populates="task"
    )

    __table_args__ = (
        Index("ix_tasks_org_status", "organization_id", "status"),
        Index("ix_tasks_org_type", "organization_id", "type"),
    )


class ReviewTask(Base):
    __tablename__ = "review_tasks"

    id: Mapped[str] = mapped_column(
        UUIDType, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    organization_id: Mapped[str] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[str] = mapped_column(
        UUIDType, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[ReviewStatus] = mapped_column(
        Enum(ReviewStatus, native_enum=False), default=ReviewStatus.PENDING, nullable=False, index=True
    )
    ai_result: Mapped[Dict[str, Any]] = mapped_column(JSONType, nullable=False)
    proposed_changes: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONType, nullable=True)
    user_decision: Mapped[Optional[ReviewDecision]] = mapped_column(
        Enum(ReviewDecision, native_enum=False), nullable=True
    )
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decided_by: Mapped[Optional[str]] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped["Task"] = relationship("Task", back_populates="review_tasks")
    reviewer: Mapped[Optional["User"]] = relationship("User")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(
        UUIDType, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    organization_id: Mapped[str] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[str] = mapped_column(UUIDType, nullable=False, index=True)
    old_values: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONType, nullable=True)
    new_values: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )

    __table_args__ = (
        Index("ix_audit_org_entity", "organization_id", "entity_type", "entity_id"),
    )


class FileMetadata(Base):
    __tablename__ = "files_metadata"

    id: Mapped[str] = mapped_column(
        UUIDType, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    organization_id: Mapped[str] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_id: Mapped[Optional[str]] = mapped_column(
        UUIDType, ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    stored_path: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    task: Mapped[Optional["Task"]] = relationship("Task", back_populates="files")


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id: Mapped[str] = mapped_column(
        UUIDType, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    organization_id: Mapped[str] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    risk_level: Mapped[str] = mapped_column(String(50), nullable=False)
    is_dry_run: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    params: Mapped[Dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)  # SUCCESS, FAILED, BLOCKED, RUNNING
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    request_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    result_payload: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )

    organization: Mapped["Organization"] = relationship("Organization")
    user: Mapped[Optional["User"]] = relationship("User")

    __table_args__ = (
        Index("ix_tool_calls_org_tool", "organization_id", "tool_name"),
        Index("ix_tool_calls_org_created", "organization_id", "created_at"),
        Index("ix_tool_calls_org_idempotency", "organization_id", "idempotency_key"),
    )


class Finding(Base):
    """
    Persistent finding domain entity representing an identified accounting / business anomaly.
    Uses SHA-256 fingerprinting for idempotent deduplication across recurring daily scans.
    """
    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(
        UUIDType, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    organization_id: Mapped[str] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    rule_version: Mapped[str] = mapped_column(String(20), default="1.0", nullable=False)
    status: Mapped[FindingStatus] = mapped_column(
        Enum(FindingStatus, native_enum=False), default=FindingStatus.OPEN, nullable=False, index=True
    )
    severity: Mapped[FindingSeverity] = mapped_column(
        Enum(FindingSeverity, native_enum=False), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    business_role: Mapped[BusinessRole] = mapped_column(
        Enum(BusinessRole, native_enum=False), nullable=False, index=True
    )
    entity_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    entity_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    evidence: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONType, nullable=True)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONType, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[Optional[str]] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )

    organization: Mapped["Organization"] = relationship("Organization")
    acknowledged_by_user: Mapped[Optional["User"]] = relationship("User")

    __table_args__ = (
        Index("ix_findings_org_fingerprint", "organization_id", "fingerprint", unique=True),
        Index("ix_findings_org_status", "organization_id", "status"),
        Index("ix_findings_org_role", "organization_id", "business_role"),
        Index("ix_findings_org_severity", "organization_id", "severity"),
    )


class ScanRun(Base):
    """
    ScanRun domain entity representing one complete diagnostic pass over a tenant infobase.
    Tracks rule execution counts, newly created, updated, and resolved findings.
    """
    __tablename__ = "scan_runs"

    id: Mapped[str] = mapped_column(
        UUIDType, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    organization_id: Mapped[str] = mapped_column(
        UUIDType, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[ScanRunStatus] = mapped_column(
        Enum(ScanRunStatus, native_enum=False), default=ScanRunStatus.PENDING, nullable=False, index=True
    )
    trigger_type: Mapped[ScanTriggerType] = mapped_column(
        Enum(ScanTriggerType, native_enum=False), default=ScanTriggerType.MANUAL, nullable=False, index=True
    )
    triggered_by: Mapped[Optional[str]] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rules_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rules_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    findings_created: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    findings_updated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    findings_resolved: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_code: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )

    organization: Mapped["Organization"] = relationship("Organization")
    triggered_by_user: Mapped[Optional["User"]] = relationship("User")

    __table_args__ = (
        Index("ix_scan_runs_org_status", "organization_id", "status"),
        Index("ix_scan_runs_org_created", "organization_id", "created_at"),
        Index("uq_scan_runs_active_org", "organization_id", unique=True,
              postgresql_where=(status.in_([ScanRunStatus.PENDING, ScanRunStatus.RUNNING])),
              sqlite_where=(status.in_([ScanRunStatus.PENDING, ScanRunStatus.RUNNING]))),
    )

