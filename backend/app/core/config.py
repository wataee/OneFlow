from typing import List, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    APP_NAME: str = "OneFlow"
    ENV: str = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./saas.db"
    
    # Redis & Celery
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/0"
    CELERY_TASK_ALWAYS_EAGER: bool = False
    TASK_PROCESSING_TIMEOUT_SECONDS: int = 300
    MAX_TASK_RETRIES: int = 3

    # Auth & Tokens
    JWT_SECRET_KEY: str = "default-insecure-secret-key-change-in-production-min32bytes"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    COOKIE_NAME: str = "refresh_token"
    COOKIE_SAMESITE: str = "lax"
    COOKIE_SECURE: bool = False  # Set to True in production HTTPS

    # AI & Review System
    # Configurable threshold: tasks with confidence below this threshold transition to REVIEW
    REVIEW_CONFIDENCE_THRESHOLD: float = Field(
        default=0.85,
        description="Confidence threshold below which tasks require human review"
    )
    DEMO_MODE: bool = True
    AI_PROVIDER: str = "demo"  # 'demo' or 'llm'
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_MODEL: str = "gpt-4o-mini"

    # 1C:Enterprise OData Access Settings
    # Default is strictly READ_ONLY_MODE = True
    ONEC_ODATA_URL: Optional[str] = None
    ONEC_USERNAME: Optional[str] = None
    ONEC_PASSWORD: Optional[str] = None
    ONEC_READ_ONLY_MODE: bool = True
    ONEC_MAX_RISK_LEVEL: str = "ANALYTICS_READ"
    ONEC_OUTPUT_MAX_ROWS: int = 100

    # Storage
    STORAGE_BACKEND: str = "local"  # 'local' or 's3'
    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_SIZE_BYTES: int = 25 * 1024 * 1024  # 25 MB
    ALLOWED_EXTENSIONS: List[str] = [".pdf", ".jpg", ".jpeg", ".png", ".xlsx", ".xml", ".zip"]

    # CORS
    CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000"
    ]


settings = Settings()
