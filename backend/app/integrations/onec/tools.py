"""
Typed Tool Registry and Definition for 1C:Enterprise Operations.
Enforces static input schema validation, graduated risk tiers, and operation naming taxonomy.
"""

from typing import Any, Callable, Dict, List, Optional, Type
from pydantic import BaseModel, ConfigDict, Field
from onec_odata import F

from app.integrations.onec.adapter import OneCAdapter
from app.integrations.onec.policy import FORBIDDEN_OPERATIONS, RISK_RANK, RiskLevel


# =============================================================================
# Strictly Typed Pydantic Input Schemas
# =============================================================================

class HealthCheckInput(BaseModel):
    """Input parameters for 1C OData system health check."""
    model_config = ConfigDict(extra="forbid")


class UnpostedDocsInput(BaseModel):
    """Input parameters for retrieving unposted accounting drafts."""
    model_config = ConfigDict(extra="forbid")
    doc_type: str = Field(
        default="ПлатежноеПоручениеИсходящее",
        description="Name of the 1C Document entity (e.g. ПлатежноеПоручениеИсходящее, РеализацияТоваровУслуг)",
    )
    limit: int = Field(
        default=50,
        ge=1,
        le=100,
        description="Maximum number of documents to retrieve (1-100)",
    )


class DebtorsInput(BaseModel):
    """Input parameters for accounts receivable / debtors analysis."""
    model_config = ConfigDict(extra="forbid")
    min_debt: float = Field(
        default=0.0,
        ge=0.0,
        description="Minimum outstanding debt balance threshold in KZT",
    )
    limit: int = Field(
        default=50,
        ge=1,
        le=100,
        description="Maximum counterparties to retrieve (1-100)",
    )


class InventoryInput(BaseModel):
    """Input parameters for warehouse stock balance inspection."""
    model_config = ConfigDict(extra="forbid")
    warehouse: Optional[str] = Field(
        default=None,
        description="Filter by warehouse or storage facility name",
    )
    limit: int = Field(
        default=50,
        ge=1,
        le=100,
        description="Maximum inventory records to retrieve (1-100)",
    )


# =============================================================================
# Tool Definition & Registry
# =============================================================================

class ToolDefinition(BaseModel):
    name: str = Field(description="Hierarchical tool taxonomy (read.<category>.<action>)")
    description: str = Field(description="Human-readable tool documentation")
    risk_level: RiskLevel = Field(description="Graduated risk level L0-L5")
    input_schema_class: Type[BaseModel] = Field(description="Pydantic class for input validation")
    output_summary: str = Field(description="Summary of output shape for human review and discovery")

    @property
    def is_mutating(self) -> bool:
        return RISK_RANK[self.risk_level] >= RISK_RANK[RiskLevel.WRITE_DRAFT]

    def get_json_schema(self) -> Dict[str, Any]:
        return self.input_schema_class.model_json_schema()


class ToolRegistry:
    """
    In-memory registry of validated 1C operational tools.
    Blocks registration of forbidden operations at declaration time.
    """

    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}
        self._executors: Dict[str, Callable] = {}

    def register(self, tool: ToolDefinition, executor: Callable) -> None:
        if tool.name in FORBIDDEN_OPERATIONS:
            raise ValueError(
                f"Cannot register tool '{tool.name}': operation is strictly prohibited by FORBIDDEN_OPERATIONS denylist."
            )
        self._tools[tool.name] = tool
        self._executors[tool.name] = executor

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def get_executor(self, name: str) -> Optional[Callable]:
        return self._executors.get(name)

    def list(self, max_risk_level: Optional[RiskLevel] = None) -> List[ToolDefinition]:
        tools = list(self._tools.values())
        if max_risk_level is not None:
            max_rank = RISK_RANK[max_risk_level]
            tools = [t for t in tools if RISK_RANK[t.risk_level] <= max_rank]
        return tools


# Global default tool registry
registry = ToolRegistry()


# =============================================================================
# Built-in Executors
# =============================================================================

async def _exec_health_check(adapter: OneCAdapter, params: HealthCheckInput) -> Any:
    return await adapter.health_check()


async def _exec_unposted_docs(adapter: OneCAdapter, params: UnpostedDocsInput) -> Any:
    filter_expr = F("Posted") == False
    return await adapter.list_document(params.doc_type, top=params.limit, filter_expr=filter_expr)


async def _exec_debtors(adapter: OneCAdapter, params: DebtorsInput) -> Any:
    return await adapter.list_accumulation_register("ВзаиморасчетыСКонтрагентами", top=params.limit)


async def _exec_inventory(adapter: OneCAdapter, params: InventoryInput) -> Any:
    return await adapter.list_accumulation_register("ТоварыНаСкладах", top=params.limit)


# Register initial foundation tools
registry.register(
    ToolDefinition(
        name="read.system.health_check",
        description="Verify 1C OData connectivity, infobase version, and response latency.",
        risk_level=RiskLevel.SAFE_READ,
        input_schema_class=HealthCheckInput,
        output_summary="Object containing connection status, metadata info, and response latency in ms.",
    ),
    _exec_health_check,
)

registry.register(
    ToolDefinition(
        name="read.documents.get_unposted",
        description="Retrieve unposted draft documents (e.g. payment orders) requiring accountant review.",
        risk_level=RiskLevel.SAFE_READ,
        input_schema_class=UnpostedDocsInput,
        output_summary="List of unposted accounting documents with masked BIN/IIN numbers and amounts.",
    ),
    _exec_unposted_docs,
)

registry.register(
    ToolDefinition(
        name="read.analytics.get_debtors",
        description="Analyze accounts receivable and identify counterparties with outstanding debt balances.",
        risk_level=RiskLevel.ANALYTICS_READ,
        input_schema_class=DebtorsInput,
        output_summary="List of debtor counterparties with masked BIN, overdue days, and debt amounts.",
    ),
    _exec_debtors,
)

registry.register(
    ToolDefinition(
        name="read.warehouse.get_inventory",
        description="Retrieve inventory balances, reserves, and free availability across warehouses.",
        risk_level=RiskLevel.ANALYTICS_READ,
        input_schema_class=InventoryInput,
        output_summary="List of items with SKU, quantity, reserved balance, and available stock.",
    ),
    _exec_inventory,
)
