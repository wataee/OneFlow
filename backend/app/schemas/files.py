from datetime import datetime
from typing import Optional
from app.schemas.common import BaseSchema


class FileMetadataResponse(BaseSchema):
    id: str
    organization_id: str
    task_id: Optional[str] = None
    filename: str
    mime_type: str
    size_bytes: int
    created_at: datetime
    deleted_at: Optional[datetime] = None
