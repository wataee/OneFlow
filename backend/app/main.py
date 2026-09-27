import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1.audit import router as audit_router
from app.api.v1.auth import router as auth_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.files import router as files_router
from app.api.v1.onec import router as onec_router
from app.api.v1.onec_connection import router as onec_connection_router
from app.api.v1.review import router as review_router
from app.api.v1.tasks import router as tasks_router
from app.api.v1.tools import router as tools_router
from app.core.config import settings
from app.core.database import AsyncSessionLocal, Base, engine

logging.basicConfig(level=logging.INFO if settings.DEBUG else logging.WARNING)
logger = logging.getLogger("app.main")


async def init_db_and_triggers():
    """
    Ensures tables exist and installs immutability triggers on audit_logs.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Database-level immutability enforcement
        dialect = engine.url.get_backend_name()
        if "postgresql" in dialect:
            await conn.execute(text("""
                CREATE OR REPLACE FUNCTION forbid_audit_modification()
                RETURNS TRIGGER AS $$
                BEGIN
                    RAISE EXCEPTION 'Audit log entries are strictly immutable.';
                END;
                $$ LANGUAGE plpgsql;
            """))
            await conn.execute(text("""
                DROP TRIGGER IF EXISTS trg_forbid_audit_modification ON audit_logs;
                CREATE TRIGGER trg_forbid_audit_modification
                BEFORE UPDATE OR DELETE ON audit_logs
                FOR EACH ROW EXECUTE FUNCTION forbid_audit_modification();
            """))
            logger.info("PostgreSQL immutability trigger installed for audit_logs.")

        elif "sqlite" in dialect:
            await conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS trg_forbid_audit_update
                BEFORE UPDATE ON audit_logs
                BEGIN
                    SELECT RAISE(FAIL, 'Audit log entries are strictly immutable.');
                END;
            """))
            await conn.execute(text("""
                CREATE TRIGGER IF NOT EXISTS trg_forbid_audit_delete
                BEFORE DELETE ON audit_logs
                BEGIN
                    SELECT RAISE(FAIL, 'Audit log entries are strictly immutable.');
                END;
            """))
            logger.info("SQLite immutability triggers installed for audit_logs.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {settings.APP_NAME} in [{settings.ENV}] mode...")
    await init_db_and_triggers()
    yield
    logger.info("Shutting down...")
    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    description="Universal SaaS Platform Foundation for Accountants and Automation Workflows",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Explicit CORS configuration - strictly from env settings
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
)


@app.get("/health", tags=["Health"])
async def health_check():
    """
    Health check endpoint for Docker and load balancers.
    Verifies live database connectivity. Returns 200 OK only if DB responds.
    """
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("SELECT 1"))
            value = result.scalar()
            if value != 1:
                raise Exception("Database returned unexpected response")
    except Exception as exc:
        logger.error(f"Health check failed: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database connection failed: {str(exc)}",
        )

    return {
        "status": "healthy",
        "database": "connected",
        "demo_mode": settings.DEMO_MODE,
        "ai_provider": settings.AI_PROVIDER,
        "review_threshold": settings.REVIEW_CONFIDENCE_THRESHOLD,
    }


# API v1 Versioned Router
api_v1 = FastAPI(title="SaaS Foundation API v1")
api_v1.include_router(auth_router)
api_v1.include_router(tasks_router)
api_v1.include_router(onec_router)
api_v1.include_router(onec_connection_router)
api_v1.include_router(tools_router)
api_v1.include_router(review_router)
api_v1.include_router(files_router)
api_v1.include_router(dashboard_router)
api_v1.include_router(audit_router)

app.mount(settings.API_V1_PREFIX, api_v1)
