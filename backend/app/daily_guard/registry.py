"""
Rule Registry for Daily Guard diagnostic checks.
"""

from typing import Dict, List, Optional
from app.daily_guard.models import DiagnosticRule
from app.models.entities import BusinessRole


class RuleRegistry:
    """
    In-memory registry of diagnostic rules for Daily Guard.
    """

    def __init__(self):
        self._rules: Dict[str, DiagnosticRule] = {}

    def register(self, rule: DiagnosticRule) -> None:
        if rule.code in self._rules:
            raise ValueError(f"Diagnostic rule with code '{rule.code}' is already registered.")
        self._rules[rule.code] = rule

    def get(self, code: str) -> Optional[DiagnosticRule]:
        return self._rules.get(code)

    def list(self, business_role: Optional[BusinessRole] = None) -> List[DiagnosticRule]:
        rules = list(self._rules.values())
        if business_role is not None:
            rules = [r for r in rules if r.business_role == business_role]
        return rules

    def clear(self) -> None:
        self._rules.clear()


rule_registry = RuleRegistry()
