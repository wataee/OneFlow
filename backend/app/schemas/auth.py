from datetime import datetime
from typing import Optional
from pydantic import EmailStr, Field

from app.models.entities import BusinessRole, UserRole
from app.schemas.common import BaseSchema


class UserRegisterRequest(BaseSchema):
    email: EmailStr
    password: str = Field(min_length=8, description="Password at least 8 chars")
    full_name: str = Field(min_length=2, max_length=255)
    organization_name: str = Field(min_length=2, max_length=255)
    business_role: Optional[BusinessRole] = None


class LoginRequest(BaseSchema):
    email: EmailStr
    password: str


class TokenResponse(BaseSchema):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseSchema):
    id: str
    organization_id: str
    email: str
    full_name: str
    role: UserRole
    business_role: Optional[BusinessRole] = None
    is_active: bool
    created_at: datetime


class OrganizationResponse(BaseSchema):
    id: str
    name: str
    created_at: datetime
