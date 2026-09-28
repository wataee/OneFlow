from typing import AsyncGenerator
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_token

http_bearer = HTTPBearer(auto_error=True)


class CurrentUserContext:
    def __init__(self, user_id: str, organization_id: str, role: str, business_role: Optional[str] = None):
        self.user_id = user_id
        self.organization_id = organization_id
        self.role = role
        self.business_role = business_role


async def get_current_user_context(
    credentials: HTTPAuthorizationCredentials = Security(http_bearer),
) -> CurrentUserContext:
    token = credentials.credentials
    try:
        payload = decode_token(token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials or token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type. Access token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id: str = payload.get("sub")
    organization_id: str = payload.get("org_id")
    role: str = payload.get("role", "user")
    business_role: Optional[str] = payload.get("business_role")

    if not user_id or not organization_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incomplete token credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return CurrentUserContext(
        user_id=user_id,
        organization_id=organization_id,
        role=role,
        business_role=business_role,
    )


def require_admin(
    current_user: CurrentUserContext = Depends(get_current_user_context),
) -> CurrentUserContext:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrative privileges required.",
        )
    return current_user
