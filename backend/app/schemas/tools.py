from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ToolDefinitionResponse(BaseModel):
    name: str = Field(description="Taxonomy identifier of the tool")
    description: str = Field(description="Operational summary")
    risk_level: str = Field(description="Graduated risk level L0-L5")
    is_mutating: bool = Field(description="True if operation performs database mutations")
    output_summary: str = Field(description="Description of result structure")
    input_schema: Dict[str, Any] = Field(description="JSON Schema specification for input parameters")


class ToolExecuteRequest(BaseModel):
    tool_name: str = Field(description="Name of tool to execute")
    params: Dict[str, Any] = Field(default_factory=dict, description="Typed arguments matching tool schema")
    dry_run: bool = Field(default=False, description="Simulate execution without external side-effects")


class ToolExecuteResponse(BaseModel):
    tool: str
    risk_level: str
    data: Any
    is_truncated: bool = False
    is_mock: bool = False
    dry_run: bool = False


class ToolCallHistoryItem(BaseModel):
    id: str
    tool_name: str
    risk_level: str
    status: str
    is_dry_run: bool
    latency_ms: Optional[int] = None
    params: Dict[str, Any]
    error: Optional[str] = None
    created_at: datetime
