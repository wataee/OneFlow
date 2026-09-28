"""
Domain contracts and abstractions for the Daily Guard diagnostic engine.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any, Dict, List, Optional

from app.models.entities import BusinessRole, FindingSeverity, utcnow


@dataclass
class FindingCandidate:
    """
    Diagnostic candidate returned by a DiagnosticRule execution.
    Contains authoritative factual observations without hallucinated AI explanations.
    """
    rule_code: str
    severity: FindingSeverity
    business_role: BusinessRole
    title: str
    description: Optional[str] = None
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    evidence: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None
    fingerprint_seed: Optional[str] = None
    rule_version: str = "1.0"


class ScanContext:
    """
    Contextual execution envelope provided to rules during a Daily Guard scan run.
    Wraps existing OneFlow tool and 1C adapter infrastructure.
    """

    def __init__(
        self,
        organization_id: str,
        run_id: str,
        session: Any,
        onec_service: Any = None,
        tool_service: Any = None,
        user_id: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
        timestamp: Optional[datetime] = None,
    ):
        self.organization_id = organization_id
        self.run_id = run_id
        self.session = session
        self.onec_service = onec_service
        self.tool_service = tool_service
        self.user_id = user_id
        self.logger = logger or logging.getLogger("app.daily_guard")
        self.timestamp = timestamp or utcnow()

    async def execute_tool(self, tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Forwards an allow-listed read operation through the existing OneCService and its
        GuardedExecutionPipeline, preserving policy checks, tenant isolation, filtering, and telemetry.
        """
        # Route through the existing OneCService and its guarded, policy checked operations.
        if not self.onec_service:
            raise RuntimeError("Daily Guard requires the tenant OneCService")
        if tool_name == "read.documents.get_unposted":
            return await self.onec_service.get_unposted_documents(user_id=self.user_id, **params)
        if tool_name == "read.analytics.get_debtors":
            return await self.onec_service.get_debtors(user_id=self.user_id, **params)
        if tool_name == "read.warehouse.get_inventory":
            return await self.onec_service.get_inventory(user_id=self.user_id, **params)
        raise ValueError(f"Unsupported read-only Daily Guard tool: {tool_name}")


class DiagnosticRule(ABC):
    """
    Abstract contract for a Daily Guard diagnostic check.
    Encapsulates specific business/accounting problem detection.
    """
    code: str
    version: str = "1.0"
    title: str
    description: str
    business_role: BusinessRole
    severity: FindingSeverity

    @abstractmethod
    async def check(self, context: ScanContext) -> List[FindingCandidate]:
        """
        Executes diagnostic evaluation against tenant 1C state and returns detected finding candidates.
        """
        pass
