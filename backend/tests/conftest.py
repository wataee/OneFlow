import asyncio
import os
from pathlib import Path
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy import text

TEST_DB_PATH = Path("./test_suite.db").resolve()

# Set test environment flags
os.environ["ENV"] = "test"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB_PATH.as_posix()}"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "true"
os.environ["DEMO_MODE"] = "true"

from app.core.config import settings
from app.core.database import Base, get_db
import app.core.database as app_db
from app.main import app
from app.models.entities import Organization, User, UserRole
from app.core.security import get_password_hash, create_access_token

test_engine = create_async_engine(
    f"sqlite+aiosqlite:///{TEST_DB_PATH.as_posix()}",
    connect_args={"check_same_thread": False},
    poolclass=NullPool,
    echo=False,
)
TestingSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

app_db.AsyncSessionLocal = TestingSessionLocal
app_db.engine = test_engine


@pytest_asyncio.fixture(scope="function")
async def db_session():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Install SQLite immutability triggers
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

    async with TestingSessionLocal() as session:
        yield session

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture(scope="function")
async def seed_tenants(db_session: AsyncSession):
    """Creates two isolated organizations with admin users."""
    org_a = Organization(name="Test Organization A")
    org_b = Organization(name="Test Organization B")
    db_session.add_all([org_a, org_b])
    await db_session.flush()

    user_a = User(
        organization_id=org_a.id,
        email="admin_a@tenant-a.com",
        hashed_password=get_password_hash("Secret123!"),
        full_name="User Tenant A",
        role=UserRole.ADMIN,
    )
    user_b = User(
        organization_id=org_b.id,
        email="admin_b@tenant-b.com",
        hashed_password=get_password_hash("Secret123!"),
        full_name="User Tenant B",
        role=UserRole.ADMIN,
    )
    user_a_member = User(
        organization_id=org_a.id,
        email="member_a@tenant-a.com",
        hashed_password=get_password_hash("Secret123!"),
        full_name="Member Tenant A",
        role=UserRole.USER,
    )
    db_session.add_all([user_a, user_b, user_a_member])
    await db_session.commit()

    token_a = create_access_token(user_a.id, org_a.id, user_a.role.value)
    token_b = create_access_token(user_b.id, org_b.id, user_b.role.value)
    token_a_member = create_access_token(user_a_member.id, org_a.id, user_a_member.role.value)

    return {
        "org_a": org_a,
        "org_b": org_b,
        "user_a": user_a,
        "user_b": user_b,
        "user_a_member": user_a_member,
        "token_a": token_a,
        "token_b": token_b,
        "token_a_member": token_a_member,
        "headers_a": {"Authorization": f"Bearer {token_a}"},
        "headers_b": {"Authorization": f"Bearer {token_b}"},
        "headers_a_member": {"Authorization": f"Bearer {token_a_member}"},
    }
