"""
Typed Tool Registry and Definition for 1C:Enterprise Operations.
Enforces static input schema validation, graduated risk tiers, operation naming taxonomy,
per-tool RBAC role policies, and cryptographic schema fingerprinting.

Architectural attribution:
- Per-tool RBAC inspired by PanosSalt/MCP-Gateway (MIT).
- Tool Poisoning Protection & Schema Fingerprinting inspired by Niraven/mcp-gateway (MIT).
- Dynamic metadata introspection inspired by vgtitov/bsl-ai-toolkit (MIT) and pyrfor/onec-odata-mcp (MIT).
- Generic catalog querying inspired by hacker-cb/1c-odata (MIT).
"""

import hashlib
import json
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


class GetMetadataInput(BaseModel):
    """Input parameters for inspecting 1C OData metadata schema."""
    model_config = ConfigDict(extra="forbid")
    entity_type: Optional[str] = Field(
        default="all",
        description="Filter entity category: 'all', 'catalogs', 'documents', or 'registers'",
    )


class CatalogQueryInput(BaseModel):
    """Input parameters for querying 1C Catalog entities."""
    model_config = ConfigDict(extra="forbid")
    catalog_name: str = Field(
        default="Контрагенты",
        pattern=r"^[a-zA-Z0-9_А-Яа-я]+$",
        description="1C Catalog entity name (e.g. Контрагенты, Номенклатура, Склады, Валюты)",
    )
    limit: int = Field(
        default=50,
        ge=1,
        le=100,
        description="Maximum number of records to retrieve (1-100)",
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Number of records to skip for pagination",
    )


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
    allowed_roles: Optional[List[str]] = Field(
        default=None,
        description="Allowed caller roles (e.g. ['admin', 'accountant']). None means any authenticated role.",
    )
    requires_approval: bool = Field(
        default=False,
        description="Whether this tool requires human review/approval before execution.",
    )

    @property
    def is_mutating(self) -> bool:
        return RISK_RANK[self.risk_level] >= RISK_RANK[RiskLevel.WRITE_DRAFT]

    @property
    def read_only(self) -> bool:
        return not self.is_mutating

    def get_json_schema(self) -> Dict[str, Any]:
        return self.input_schema_class.model_json_schema()

    @property
    def schema_hash(self) -> str:
        """
        Computes deterministic SHA-256 fingerprint of the tool definition and input schema.
        Protects against tool poisoning, parameter tampering, and drift.
        """
        raw = {
            "name": self.name,
            "risk_level": self.risk_level.value,
            "is_mutating": self.is_mutating,
            "requires_approval": self.requires_approval,
            "schema": self.get_json_schema(),
        }
        encoded = json.dumps(raw, sort_keys=True).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class ToolRegistry:
    """
    In-memory registry of validated 1C operational tools.
    Blocks registration of forbidden operations at declaration time.
    Supports role-based access filtering and risk-ceiling queries.
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

    def list(
        self,
        max_risk_level: Optional[RiskLevel] = None,
        user_role: Optional[str] = None,
    ) -> List[ToolDefinition]:
        tools = list(self._tools.values())
        if max_risk_level is not None:
            max_rank = RISK_RANK[max_risk_level]
            tools = [t for t in tools if RISK_RANK[t.risk_level] <= max_rank]
        if user_role is not None:
            tools = [
                t for t in tools
                if t.allowed_roles is None or user_role in t.allowed_roles
            ]
        return tools


registry = ToolRegistry()
tool_registry = registry


# =============================================================================
# Built-in Executors
# =============================================================================

async def _exec_health_check(adapter: OneCAdapter, params: HealthCheckInput) -> Any:
    return await adapter.health_check()


async def _exec_get_metadata(adapter: OneCAdapter, params: GetMetadataInput) -> Any:
    meta = await adapter.get_metadata()
    if params.entity_type == "catalogs":
        return {"catalogs": meta.get("catalogs", [])}
    if params.entity_type == "documents":
        return {"documents": meta.get("documents", [])}
    if params.entity_type == "registers":
        return {"accumulation_registers": meta.get("accumulation_registers", [])}
    return meta


async def _exec_catalog_query(adapter: OneCAdapter, params: CatalogQueryInput) -> Any:
    return await adapter.list_catalog(
        catalog_name=params.catalog_name,
        top=params.limit,
        skip=params.offset,
    )


async def _exec_unposted_docs(adapter: OneCAdapter, params: UnpostedDocsInput) -> Any:
    filter_expr = F("Posted") == False
    return await adapter.list_document(params.doc_type, top=params.limit, filter_expr=filter_expr)


async def _exec_debtors(adapter: OneCAdapter, params: DebtorsInput) -> Any:
    return await adapter.list_accumulation_register("ВзаиморасчетыСКонтрагентами", top=params.limit)


async def _exec_inventory(adapter: OneCAdapter, params: InventoryInput) -> Any:
    return await adapter.list_accumulation_register("ТоварыНаСкладах", top=params.limit)


# =============================================================================
# Foundation Tool Registrations
# =============================================================================

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
        name="read.system.get_metadata",
        description="Inspect 1C:Enterprise metadata schema, available catalogs, documents, and accumulation registers.",
        risk_level=RiskLevel.SAFE_READ,
        input_schema_class=GetMetadataInput,
        output_summary="Metadata schema with categorized entity listings and total entity count.",
    ),
    _exec_get_metadata,
)

registry.register(
    ToolDefinition(
        name="read.catalog.query",
        description="Query records from a 1C Catalog (Справочник) with pagination and field masking.",
        risk_level=RiskLevel.SAFE_READ,
        input_schema_class=CatalogQueryInput,
        output_summary="List of catalog entity records with masked PII and row capping.",
    ),
    _exec_catalog_query,
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
