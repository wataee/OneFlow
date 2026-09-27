from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import Field

from app.models.entities import TaskStatus, TaskType
from app.schemas.common import BaseSchema


class TaskCreateRequest(BaseSchema):
    type: TaskType
    input_data: Dict[str, Any] = Field(default_factory=dict)


class TaskResponse(BaseSchema):
    id: str
    organization_id: str
    type: TaskType
    status: TaskStatus
    input_data: Dict[str, Any]
    output_data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    confidence: Optional[float] = None
    retry_count: int
    created_at: datetime
    updated_at: datetime


class TaskStatusTransitionRequest(BaseSchema):
    target_status: TaskStatus
    reason: Optional[str] = None
