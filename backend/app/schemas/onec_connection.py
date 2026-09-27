from typing import Optional
from pydantic import BaseModel, Field


class OneCConnectionStatus(BaseModel):
    base_url: Optional[str] = None
    username: Optional[str] = None
    is_writable: bool = False
    is_configured: bool = False
    is_mock: bool = True
    max_onec_risk_level: Optional[str] = None


class OneCConnectionUpdate(BaseModel):
    base_url: str = Field(description="1C:Enterprise OData base URL endpoint")
    username: Optional[str] = Field(default=None, description="1C Infobase user login")
    password: Optional[str] = Field(default=None, description="1C Infobase user password (encrypted on storage)")
    is_writable: bool = Field(default=False, description="Enable draft document write permissions")
    max_onec_risk_level: Optional[str] = Field(
        default=None,
        description="Tenant-level maximum risk ceiling override (e.g. SAFE_READ, ANALYTICS_READ)",
    )


class OneCTestConnectionRequest(BaseModel):
    base_url: Optional[str] = Field(default=None, description="Optional provisional base URL to test")
    username: Optional[str] = Field(default=None, description="Optional provisional username")
    password: Optional[str] = Field(default=None, description="Optional provisional password")
