"""
1C:Enterprise OData Operation Access Policy & Risk Assessment.

Architectural attribution:
- Risk-level graduated hierarchy inspired by concepts in ashybulakstroy-mcp-1c-bridge
  (https://github.com/ashybulakstroy/ashybulakstroy-mcp-1c-bridge). Reimplemented
  independently to fit our core service architecture.
- Dual-safety latch (global read-only mode + per-tenant database writability check)
  inspired by concepts in 1c-odata-mcp (https://github.com/evilbruce666/1c-odata-mcp).
"""

import enum
from functools import wraps
from typing import Any, Callable, Dict, Optional, Set
from pydantic import BaseModel

from app.core.config import settings


class RiskLevel(str, enum.Enum):
    """
    Graduated risk classification for 1C operations.
    L0 -> L5 with strictly monotonically increasing hazard levels.
    """
    SAFE_READ = "SAFE_READ"              # L0: Metadata, status, non-sensitive directories (Currencies, Units)
    ANALYTICS_READ = "ANALYTICS_READ"    # L1: Balances, turnovers, mutual settlements, stock reports
    SENSITIVE_READ = "SENSITIVE_READ"    # L2: Payroll, personal tax numbers, bank accounts, confidential agreements
    WRITE_DRAFT = "WRITE_DRAFT"          # L3: Creating unposted draft documents
    WRITE_POST = "WRITE_POST"            # L4: Posting documents, modifying accounting registers
    DESTRUCTIVE = "DESTRUCTIVE"          # L5: Unposting, deletions, direct script execution (always blocked)


RISK_RANK: Dict[RiskLevel, int] = {
    RiskLevel.SAFE_READ: 0,
    RiskLevel.ANALYTICS_READ: 1,
    RiskLevel.SENSITIVE_READ: 2,
    RiskLevel.WRITE_DRAFT: 3,
    RiskLevel.WRITE_POST: 4,
    RiskLevel.DESTRUCTIVE: 5,
}

# Operations that are fundamentally prohibited regardless of user role or permissions
FORBIDDEN_OPERATIONS: Set[str] = {
    "raw_odata_query",
    "execute_arbitrary_code",
    "direct_sql_query",
    "clear_infobase",
    "delete_catalog_item",
    "truncate_table",
}


class PolicyViolationError(Exception):
    """Raised when an operation is blocked by the 1C security policy."""
    pass


class PolicyDecision(BaseModel):
    allowed: bool
    risk_level: RiskLevel
    operation_name: str
    reason: Optional[str] = None


class OneCPolicyEnforcer:
    """
    Enforces security policies, risk constraints, and write guards
    prior to executing any request against 1C:Enterprise OData.
    """

    def __init__(
        self,
        global_read_only: bool = settings.ONEC_READ_ONLY_MODE,
        max_allowed_risk: RiskLevel = RiskLevel.ANALYTICS_READ,
        is_tenant_writable: bool = False,
        org_max_risk_level: Optional[RiskLevel] = None,
    ):
        self.global_read_only = global_read_only
        self.is_tenant_writable = is_tenant_writable

        # Effective risk ceiling: min(global_ceiling, org_ceiling)
        # Stricter ceiling has lower rank (SAFE_READ=0 < ANALYTICS_READ=1)
        if org_max_risk_level is not None:
            if RISK_RANK[org_max_risk_level] < RISK_RANK[max_allowed_risk]:
                self.max_allowed_risk = org_max_risk_level
            else:
                self.max_allowed_risk = max_allowed_risk
        else:
            self.max_allowed_risk = max_allowed_risk

    def evaluate(self, operation_name: str, risk_level: RiskLevel) -> PolicyDecision:
        # 1. Check unconditionally forbidden operations
        if operation_name in FORBIDDEN_OPERATIONS:
            return PolicyDecision(
                allowed=False,
                risk_level=risk_level,
                operation_name=operation_name,
                reason=f"Operation '{operation_name}' is on the forbidden operations denylist and cannot be executed.",
            )

        # 2. Dual-safety latch: Write operations check
        is_write = RISK_RANK[risk_level] >= RISK_RANK[RiskLevel.WRITE_DRAFT]
        if is_write:
            if self.global_read_only:
                return PolicyDecision(
                    allowed=False,
                    risk_level=risk_level,
                    operation_name=operation_name,
                    reason="1C write operation blocked by global READ_ONLY_MODE=true.",
                )
            if not self.is_tenant_writable:
                return PolicyDecision(
                    allowed=False,
                    risk_level=risk_level,
                    operation_name=operation_name,
                    reason="1C write operation blocked: target organization's database is configured as read-only.",
                )

        # 3. Risk level ceiling check
        current_rank = RISK_RANK[risk_level]
        max_rank = RISK_RANK[self.max_allowed_risk]
        if current_rank > max_rank:
            return PolicyDecision(
                allowed=False,
                risk_level=risk_level,
                operation_name=operation_name,
                reason=(
                    f"Operation risk level {risk_level.value} (rank {current_rank}) exceeds "
                    f"maximum allowed risk level {self.max_allowed_risk.value} (rank {max_rank})."
                ),
            )

        return PolicyDecision(
            allowed=True,
            risk_level=risk_level,
            operation_name=operation_name,
            reason=None,
        )

    def verify_or_raise(self, operation_name: str, risk_level: RiskLevel) -> None:
        decision = self.evaluate(operation_name, risk_level)
        if not decision.allowed:
            raise PolicyViolationError(decision.reason)


def requires_risk_level(risk_level: RiskLevel):
    """
    Decorator to annotate 1C adapter operations with their explicit risk classification.
    """
    def decorator(fn: Callable[..., Any]):
        fn.__onec_risk_level__ = risk_level
        return fn
    return decorator
