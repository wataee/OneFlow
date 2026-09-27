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
    schema_hash: str = Field(default="", description="Cryptographic SHA-256 fingerprint for tool poisoning protection")
    allowed_roles: Optional[List[str]] = Field(default=None, description="Caller roles permitted to execute this tool")
    requires_approval: bool = Field(default=False, description="Whether this tool requires Human-in-the-Loop authorization")


class ToolExecuteRequest(BaseModel):
    tool_name: str = Field(description="Name of tool to execute")
    params: Dict[str, Any] = Field(default_factory=dict, description="Typed arguments matching tool schema")
    dry_run: bool = Field(default=False, description="Simulate execution without external side-effects")
    idempotency_key: Optional[str] = Field(default=None, description="Client idempotency key")
    request_id: Optional[str] = Field(default=None, description="Client request correlation ID")
    approval_review_id: Optional[str] = Field(default=None, description="ID of resolved approval review if tool requires approval")


class ToolExecuteResponse(BaseModel):
    tool: str
    risk_level: str
    data: Optional[Any] = None
    is_truncated: bool = False
    is_mock: bool = False
    dry_run: bool = False
    request_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    status: Optional[str] = None
    review_task_id: Optional[str] = None
    task_id: Optional[str] = None
    message: Optional[str] = None


class ToolCallHistoryItem(BaseModel):
    id: str
    tool_name: str
    risk_level: str
    status: str
    is_dry_run: bool
    latency_ms: Optional[int] = None
    params: Dict[str, Any]
    error: Optional[str] = None
    error_code: Optional[str] = None
    request_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    created_at: datetime
