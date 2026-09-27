from datetime import timedelta
from typing import Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
    verify_password,
)
from app.models.entities import Organization, User, UserRole
from app.repositories.domain_repos import AuthGlobalRepository, UserRepository
from app.schemas.auth import UserRegisterRequest
from app.services.audit_service import AuditService


class AuthenticationError(Exception):
    pass


class AuthService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.global_repo = AuthGlobalRepository(session)

    async def register(self, req: UserRegisterRequest) -> Tuple[User, str, str]:
        existing_user = await self.global_repo.get_user_by_email(req.email)
        if existing_user:
            raise AuthenticationError(f"User with email '{req.email}' already exists.")

        # Create new Organization (multi-tenant tenant root)
        org = await self.global_repo.create_organization(req.organization_name)

        # Create Admin User for this new Organization
        hashed = get_password_hash(req.password)
        user = await self.global_repo.create_user(
            organization_id=org.id,
            email=req.email,
            hashed_password=hashed,
            full_name=req.full_name,
            role=UserRole.ADMIN,
        )

        # Audit initial registration
        audit = AuditService(self.session, org.id)
        await audit.log_event(
            action="ORGANIZATION_REGISTERED",
            entity_type="Organization",
            entity_id=org.id,
            new_values={"name": org.name, "created_by": user.email},
            user_id=user.id,
        )

        access_token = create_access_token(
            subject=user.id,
            organization_id=org.id,
            role=user.role.value,
        )
        refresh_token = create_refresh_token(
            subject=user.id,
            organization_id=org.id,
        )

        return user, access_token, refresh_token

    async def authenticate(self, email: str, password: str) -> Tuple[User, str, str]:
        user = await self.global_repo.get_user_by_email(email)
        if not user or not verify_password(password, user.hashed_password):
            raise AuthenticationError("Invalid email or password.")

        if not user.is_active:
            raise AuthenticationError("User account is inactive.")

        access_token = create_access_token(
            subject=user.id,
            organization_id=user.organization_id,
            role=user.role.value,
        )
        refresh_token = create_refresh_token(
            subject=user.id,
            organization_id=user.organization_id,
        )

        audit = AuditService(self.session, user.organization_id)
        await audit.log_event(
            action="USER_LOGGED_IN",
            entity_type="User",
            entity_id=user.id,
            user_id=user.id,
        )

        return user, access_token, refresh_token

    async def refresh_access_token(self, refresh_token: str) -> str:
        """
        Validates refresh token strictly from httpOnly cookie and produces fresh access token.
        """
        try:
            payload = decode_token(refresh_token)
        except Exception:
            raise AuthenticationError("Invalid or expired refresh token.")

        if payload.get("type") != "refresh":
            raise AuthenticationError("Invalid token type. Refresh token required.")

        user_id = payload.get("sub")
        org_id = payload.get("org_id")
        if not user_id or not org_id:
            raise AuthenticationError("Malformed token payload.")

        user_repo = UserRepository(self.session, org_id)
        user = await user_repo.get_by_id(user_id)
        if not user or not user.is_active:
            raise AuthenticationError("User is no longer active.")

        new_access_token = create_access_token(
            subject=user.id,
            organization_id=user.organization_id,
            role=user.role.value,
        )
        return new_access_token

    async def get_user_profile(self, user_id: str, organization_id: str) -> Optional[User]:
        repo = UserRepository(self.session, organization_id)
        return await repo.get_by_id(user_id)
