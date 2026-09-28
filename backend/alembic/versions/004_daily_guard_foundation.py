"""Add Daily Guard foundation tables and business_role to users

Revision ID: 004_daily_guard_foundation
Revises: 003_execution_reliability
Create Date: 2026-09-28 04:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '004_daily_guard_foundation'
down_revision: Union[str, None] = '003_execution_reliability'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add business_role to users
    op.add_column('users', sa.Column('business_role', sa.String(length=50), nullable=True))
    op.create_index('ix_users_business_role', 'users', ['business_role'], unique=False)

    # 2. Create findings table
    op.create_table(
        'findings',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(length=36), nullable=False),
        sa.Column('rule_code', sa.String(length=100), nullable=False),
        sa.Column('rule_version', sa.String(length=20), server_default='1.0', nullable=False),
        sa.Column('status', sa.String(length=50), server_default='OPEN', nullable=False),
        sa.Column('severity', sa.String(length=50), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('business_role', sa.String(length=50), nullable=False),
        sa.Column('entity_type', sa.String(length=100), nullable=True),
        sa.Column('entity_id', sa.String(length=255), nullable=True),
        sa.Column('fingerprint', sa.String(length=64), nullable=False),
        sa.Column('evidence', sa.JSON(), nullable=True),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
        sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('acknowledged_by', sa.String(length=36), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['acknowledged_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_findings_organization_id', 'findings', ['organization_id'], unique=False)
    op.create_index('ix_findings_rule_code', 'findings', ['rule_code'], unique=False)
    op.create_index('ix_findings_status', 'findings', ['status'], unique=False)
    op.create_index('ix_findings_severity', 'findings', ['severity'], unique=False)
    op.create_index('ix_findings_business_role', 'findings', ['business_role'], unique=False)
    op.create_index('ix_findings_fingerprint', 'findings', ['fingerprint'], unique=False)
    op.create_index('ix_findings_org_fingerprint', 'findings', ['organization_id', 'fingerprint'], unique=True)
    op.create_index('ix_findings_org_status', 'findings', ['organization_id', 'status'], unique=False)
    op.create_index('ix_findings_org_role', 'findings', ['organization_id', 'business_role'], unique=False)
    op.create_index('ix_findings_org_severity', 'findings', ['organization_id', 'severity'], unique=False)

    # 3. Create scan_runs table
    op.create_table(
        'scan_runs',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(length=36), nullable=False),
        sa.Column('status', sa.String(length=50), server_default='PENDING', nullable=False),
        sa.Column('trigger_type', sa.String(length=50), server_default='MANUAL', nullable=False),
        sa.Column('triggered_by', sa.String(length=36), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('rules_total', sa.Integer(), server_default='0', nullable=False),
        sa.Column('rules_completed', sa.Integer(), server_default='0', nullable=False),
        sa.Column('findings_created', sa.Integer(), server_default='0', nullable=False),
        sa.Column('findings_updated', sa.Integer(), server_default='0', nullable=False),
        sa.Column('findings_resolved', sa.Integer(), server_default='0', nullable=False),
        sa.Column('error_code', sa.String(length=50), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['triggered_by'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_scan_runs_organization_id', 'scan_runs', ['organization_id'], unique=False)
    op.create_index('ix_scan_runs_status', 'scan_runs', ['status'], unique=False)
    op.create_index('ix_scan_runs_created_at', 'scan_runs', ['created_at'], unique=False)
    op.create_index('ix_scan_runs_org_status', 'scan_runs', ['organization_id', 'status'], unique=False)
    op.create_index('ix_scan_runs_org_created', 'scan_runs', ['organization_id', 'created_at'], unique=False)
    op.create_index('uq_scan_runs_active_org', 'scan_runs', ['organization_id'], unique=True,
        postgresql_where=sa.text("status IN ('PENDING', 'RUNNING')"),
        sqlite_where=sa.text("status IN ('PENDING', 'RUNNING')"))


def downgrade() -> None:
    op.drop_index('uq_scan_runs_active_org', table_name='scan_runs')
    op.drop_table('scan_runs')
    op.drop_table('findings')
    op.drop_index('ix_users_business_role', table_name='users')
    op.drop_column('users', 'business_role')
