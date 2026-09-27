"""Add tool_calls table and organization risk ceiling

Revision ID: 002_tool_calls_and_org_risk
Revises: 001_initial_tables
Create Date: 2026-09-28 01:15:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '002_tool_calls_and_org_risk'
down_revision: Union[str, None] = '001_initial_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Extend organizations table
    op.add_column('organizations', sa.Column('onec_config', sa.JSON(), nullable=True))
    op.add_column('organizations', sa.Column('max_onec_risk_level', sa.String(length=50), nullable=True))

    # 2. Create tool_calls audit/telemetry table
    op.create_table(
        'tool_calls',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=True),
        sa.Column('tool_name', sa.String(length=100), nullable=False),
        sa.Column('risk_level', sa.String(length=50), nullable=False),
        sa.Column('is_dry_run', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('params', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_tool_calls_organization_id', 'tool_calls', ['organization_id'], unique=False)
    op.create_index('ix_tool_calls_tool_name', 'tool_calls', ['tool_name'], unique=False)
    op.create_index('ix_tool_calls_created_at', 'tool_calls', ['created_at'], unique=False)
    op.create_index('ix_tool_calls_org_tool', 'tool_calls', ['organization_id', 'tool_name'], unique=False)
    op.create_index('ix_tool_calls_org_created', 'tool_calls', ['organization_id', 'created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_tool_calls_org_created', table_name='tool_calls')
    op.drop_index('ix_tool_calls_org_tool', table_name='tool_calls')
    op.drop_index('ix_tool_calls_created_at', table_name='tool_calls')
    op.drop_index('ix_tool_calls_tool_name', table_name='tool_calls')
    op.drop_index('ix_tool_calls_organization_id', table_name='tool_calls')
    op.drop_table('tool_calls')
    op.drop_column('organizations', 'max_onec_risk_level')
    op.drop_column('organizations', 'onec_config')
