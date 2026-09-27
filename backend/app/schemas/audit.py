from datetime import datetime
from typing import Any, Dict, Optional
from app.schemas.common import BaseSchema


class AuditLogResponse(BaseSchema):
    id: str
    organization_id: str
    user_id: Optional[str] = None
    action: str
    entity_type: str
    entity_id: str
    old_values: Optional[Dict[str, Any]] = None
    new_values: Optional[Dict[str, Any]] = None
    created_at: datetime
