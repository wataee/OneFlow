import asyncio
import os
import sys
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from app.core.database import AsyncSessionLocal, engine, Base
from app.core.security import get_password_hash
from app.main import init_db_and_triggers
from app.models.entities import (
    AuditLog,
    FileMetadata,
    Organization,
    ReviewDecision,
    ReviewStatus,
    ReviewTask,
    Task,
    TaskStatus,
    TaskType,
    User,
    UserRole,
    BusinessRole,
)


async def seed_data():
    print("Initializing database and immutability triggers...")
    await init_db_and_triggers()

    async with AsyncSessionLocal() as session:
        # Check if already seeded
        from sqlalchemy import select
        existing_org = await session.execute(select(Organization).limit(1))
        if existing_org.scalars().first():
            print("Database already contains data. Skipping seed.")
            return

        print("Seeding demo organizations and users...")
        # 1. Organization A (Main Demo Tenant)
        org_a = Organization(name="ТОО Базис-Аудит")
        session.add(org_a)
        await session.flush()

        # Admin user
        admin_a = User(
            organization_id=org_a.id,
            email="admin@example.kz",
            hashed_password=get_password_hash("Secret123!"),
            full_name="Ерлан Каримов",
            role=UserRole.ADMIN,
            business_role=BusinessRole.OWNER,
        )
        # Regular accountant user
        user_a = User(
            organization_id=org_a.id,
            email="user@example.kz",
            hashed_password=get_password_hash("Secret123!"),
            full_name="Айгерим Смагулова",
            role=UserRole.USER,
            business_role=BusinessRole.ACCOUNTANT,
        )
        session.add_all([admin_a, user_a])
        await session.flush()

        # 2. Organization B (Second Tenant to test Multi-tenancy isolation!)
        org_b = Organization(name="ТОО Степь Логистик")
        session.add(org_b)
        await session.flush()

        other_user = User(
            organization_id=org_b.id,
            email="other@example.kz",
            hashed_password=get_password_hash("Secret123!"),
            full_name="Марат Омаров",
            role=UserRole.ADMIN,
            business_role=BusinessRole.MANAGER,
        )
        session.add(other_user)

        # Isolated task in Org B
        task_b = Task(
            organization_id=org_b.id,
            type=TaskType.BANK_OPERATION,
            status=TaskStatus.PENDING,
            input_data={"secret_organization_b_data": "CONFIDENTIAL_STEPPE_123"},
            retry_count=0,
        )
        session.add(task_b)
        await session.flush()

        print("Seeding tasks across all lifecycle states for Organization A...")
        # Task 1: PENDING
        task_pending = Task(
            organization_id=org_a.id,
            type=TaskType.DOCUMENT_PROCESSING,
            status=TaskStatus.PENDING,
            input_data={"document_id": "DOC-2026-001", "declared_sum": 450000, "currency": "KZT"},
            retry_count=0,
        )

        # Task 2: PROCESSING
        task_processing = Task(
            organization_id=org_a.id,
            type=TaskType.NOMENCLATURE_MATCHING,
            status=TaskStatus.PROCESSING,
            input_data={"items_to_match": 14, "catalog_version": "2026.2"},
            retry_count=0,
        )

        # Task 3: REVIEW (Confidence below threshold 0.85 -> Requires human-in-the-loop review)
        task_review = Task(
            organization_id=org_a.id,
            type=TaskType.BANK_OPERATION,
            status=TaskStatus.REVIEW,
            input_data={"transaction_ref": "TX-998811", "amount": 1285000},
            output_data=None,
            confidence=0.72,
            retry_count=0,
        )

        # Task 4: COMPLETED (Automated without human intervention, confidence 0.96)
        task_completed_auto = Task(
            organization_id=org_a.id,
            type=TaskType.WAREHOUSE_RECONCILIATION,
            status=TaskStatus.COMPLETED,
            input_data={"batch_code": "WH-ALM-44", "scanned_units": 120},
            output_data={"reconciliation_status": "MATCHED", "delta": 0, "discrepancies": []},
            confidence=0.96,
            retry_count=0,
        )

        # Task 5: COMPLETED (Through Human Review approval)
        task_completed_reviewed = Task(
            organization_id=org_a.id,
            type=TaskType.DOCUMENT_PROCESSING,
            status=TaskStatus.COMPLETED,
            input_data={"contract_num": "KZ-884/26"},
            output_data={"extracted_vendor": "ТОО Альфа Снаб", "bin": "981240001122", "total": 750000},
            confidence=0.68,
            retry_count=0,
        )

        # Task 6: FAILED (with error and retry count)
        task_failed = Task(
            organization_id=org_a.id,
            type=TaskType.BANK_OPERATION,
            status=TaskStatus.FAILED,
            input_data={"account": "KZ1234567890"},
            error="Upstream network timeout during transaction inquiry",
            confidence=None,
            retry_count=1,
        )

        session.add_all([
            task_pending,
            task_processing,
            task_review,
            task_completed_auto,
            task_completed_reviewed,
            task_failed,
        ])
        await session.flush()

        print("Seeding ReviewTasks...")
        # ReviewTask for task_review (Pending human decision)
        review_pending = ReviewTask(
            organization_id=org_a.id,
            task_id=task_review.id,
            status=ReviewStatus.PENDING,
            ai_result={
                "counterparty": "ТОО КазТрансСервис",
                "payment_code": "KN_14",
                "tax_deductible": True,
                "confidence_breakdown": {"counterparty": 0.92, "payment_code": 0.52},
            },
        )

        # ReviewTask for task_completed_reviewed (Resolved with approve)
        review_resolved = ReviewTask(
            organization_id=org_a.id,
            task_id=task_completed_reviewed.id,
            status=ReviewStatus.RESOLVED,
            ai_result={"extracted_vendor": "ТОО Альфа Снаб", "bin": "981240001122", "total": 750000},
            user_decision=ReviewDecision.APPROVE,
            decided_by=admin_a.id,
        )
        session.add_all([review_pending, review_resolved])
        await session.flush()

        print("Seeding FileMetadata...")
        file_1 = FileMetadata(
            organization_id=org_a.id,
            task_id=task_pending.id,
            filename="akt_vypolnennyh_rabot.pdf",
            stored_path=f"{org_a.id}/seed_akt.pdf",
            mime_type="application/pdf",
            size_bytes=1048576,
        )
        file_2 = FileMetadata(
            organization_id=org_a.id,
            task_id=task_review.id,
            filename="bank_statement_september.xlsx",
            stored_path=f"{org_a.id}/seed_statement.xlsx",
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            size_bytes=245800,
        )
        session.add_all([file_1, file_2])
        await session.flush()

        print("Seeding AuditLogs...")
        audit_1 = AuditLog(
            organization_id=org_a.id,
            user_id=admin_a.id,
            action="ORGANIZATION_INITIALIZED",
            entity_type="Organization",
            entity_id=org_a.id,
            new_values={"name": org_a.name, "seeded": True},
        )
        audit_2 = AuditLog(
            organization_id=org_a.id,
            user_id=None,
            action="TASK_SENT_TO_REVIEW",
            entity_type="Task",
            entity_id=task_review.id,
            old_values={"status": "PROCESSING"},
            new_values={"status": "REVIEW", "confidence": 0.72},
        )
        audit_3 = AuditLog(
            organization_id=org_a.id,
            user_id=admin_a.id,
            action="REVIEW_APPROVED",
            entity_type="ReviewTask",
            entity_id=review_resolved.id,
            old_values={"status": "PENDING"},
            new_values={"status": "RESOLVED", "decision": "approve"},
        )
        session.add_all([audit_1, audit_2, audit_3])

        await session.commit()
        print("Seed completed successfully!")
        print("Credentials for testing:")
        print("Organization A (ТОО Базис-Аудит):")
        print("  Admin:      admin@example.kz / Secret123!")
        print("  Accountant: user@example.kz  / Secret123!")
        print("Organization B (ТОО Степь Логистик):")
        print("  Admin:      other@example.kz / Secret123!")


if __name__ == "__main__":
    asyncio.run(seed_data())
