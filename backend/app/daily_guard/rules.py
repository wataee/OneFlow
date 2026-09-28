from typing import List

from app.daily_guard.models import DiagnosticRule, FindingCandidate, ScanContext
from app.models.entities import BusinessRole, FindingSeverity


class UnpostedDocumentsRule(DiagnosticRule):
    code, version = "documents.unposted", "1.0"
    title = "Unposted document"
    description = "A draft document was returned by the existing 1C read operation."
    business_role, severity = BusinessRole.ACCOUNTANT, FindingSeverity.WARNING

    async def check(self, context: ScanContext) -> List[FindingCandidate]:
        result = await context.execute_tool("read.documents.get_unposted", {"limit": 100})
        return [FindingCandidate(self.code, self.severity, self.business_role,
            f"Unposted document {row.get('Number') or row.get('Ref_Key', 'unknown')}",
            self.description, "Document", str(row.get("Ref_Key") or row.get("Number") or ""),
            {k: row[k] for k in ("Number", "Date", "Posted", "СуммаДокумента", "Контрагент") if k in row},
            rule_version=self.version) for row in result.get("data", []) if isinstance(row, dict)]


class WarehouseInventoryRule(DiagnosticRule):
    code, version = "warehouse.inventory_check", "1.0"
    title = "Inventory balance check"
    description = "Available quantity is negative or reserved quantity exceeds the stock balance."
    business_role, severity = BusinessRole.WAREHOUSE, FindingSeverity.ERROR

    async def check(self, context: ScanContext) -> List[FindingCandidate]:
        result = await context.execute_tool("read.warehouse.get_inventory", {"limit": 100})
        findings = []
        for row in result.get("data", []):
            if not isinstance(row, dict):
                continue
            quantity, reserved = float(row.get("quantity", 0) or 0), float(row.get("reserved", 0) or 0)
            if float(row.get("available", quantity - reserved) or 0) < 0 or reserved > quantity:
                identity = str(row.get("sku") or row.get("Ref_Key") or "unknown")
                findings.append(FindingCandidate(self.code, self.severity, self.business_role,
                    f"Inventory balance requires review: {identity}", self.description, "Inventory", identity,
                    {k: row.get(k) for k in ("sku", "name", "warehouse", "quantity", "reserved", "available")}))
        return findings


class OverdueDebtorsRule(DiagnosticRule):
    code, version = "debtors.overdue", "1.0"
    title = "Overdue debtor balance"
    description = "The existing 1C debtor query reports a positive overdue age."
    business_role, severity = BusinessRole.MANAGER, FindingSeverity.WARNING

    async def check(self, context: ScanContext) -> List[FindingCandidate]:
        result = await context.execute_tool("read.analytics.get_debtors", {"limit": 100})
        findings = []
        for row in result.get("data", []):
            if isinstance(row, dict) and float(row.get("overdue_days", 0) or 0) > 0:
                identity = str(row.get("counterparty") or row.get("Ref_Key") or "unknown")
                findings.append(FindingCandidate(self.code, self.severity, self.business_role,
                    f"Overdue balance: {identity}", self.description, "Counterparty", identity,
                    {k: row.get(k) for k in ("counterparty", "debt_amount_kzt", "overdue_days", "contract")}))
        return findings


def register_demo_rules(registry):
    for rule in (UnpostedDocumentsRule(), WarehouseInventoryRule(), OverdueDebtorsRule()):
        if registry.get(rule.code) is None:
            registry.register(rule)
    return registry
