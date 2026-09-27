import bcrypt
import jwt
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from app.core.config import settings


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plain password against an argon2/bcrypt hash."""
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8")
    )


def get_password_hash(password: str) -> str:
    """Generates a secure salted bcrypt hash for the password."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def create_access_token(subject: str, organization_id: str, role: str, expires_delta: Optional[timedelta] = None) -> str:
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    payload: Dict[str, Any] = {
        "sub": subject,
        "org_id": organization_id,
        "role": role,
        "type": "access",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(subject: str, organization_id: str, expires_delta: Optional[timedelta] = None) -> str:
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    
    payload: Dict[str, Any] = {
        "sub": subject,
        "org_id": organization_id,
        "type": "refresh",
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> Dict[str, Any]:
    """Decodes and validates a JWT token."""
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


import base64
import hashlib
import logging
from cryptography.fernet import Fernet, InvalidToken

_security_logger = logging.getLogger("app.core.security")


def _get_onec_fernet() -> Fernet:
    raw_key = settings.ONEC_CREDENTIALS_ENCRYPTION_KEY
    if raw_key:
        try:
            return Fernet(raw_key.encode("utf-8") if isinstance(raw_key, str) else raw_key)
        except Exception:
            derived = base64.urlsafe_b64encode(hashlib.sha256(raw_key.encode("utf-8")).digest())
            return Fernet(derived)
    else:
        _security_logger.warning(
            "ONEC_CREDENTIALS_ENCRYPTION_KEY is unset. Deriving development encryption key from JWT_SECRET_KEY. "
            "Set a dedicated ONEC_CREDENTIALS_ENCRYPTION_KEY in production!"
        )
        derived = base64.urlsafe_b64encode(hashlib.sha256(settings.JWT_SECRET_KEY.encode("utf-8")).digest())
        return Fernet(derived)


def encrypt_onec_credential(plain_text: str) -> str:
    """Encrypts sensitive tenant credentials (passwords, tokens) using Fernet symmetric encryption."""
    if not plain_text:
        return ""
    fernet = _get_onec_fernet()
    return fernet.encrypt(plain_text.encode("utf-8")).decode("utf-8")


def decrypt_onec_credential(cipher_text: str) -> str:
    """Decrypts encrypted tenant credentials using Fernet. Falls back to plain text if not encrypted."""
    if not cipher_text:
        return ""
    fernet = _get_onec_fernet()
    try:
        return fernet.decrypt(cipher_text.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return cipher_text

