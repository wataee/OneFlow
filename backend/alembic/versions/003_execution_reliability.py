"""Add execution reliability columns to tool_calls

Revision ID: 003_execution_reliability
Revises: 002_tool_calls_and_org_risk
Create Date: 2026-09-28 02:20:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '003_execution_reliability'
down_revision: Union[str, None] = '002_tool_calls_and_org_risk'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tool_calls', sa.Column('request_id', sa.String(length=128), nullable=True))
    op.add_column('tool_calls', sa.Column('idempotency_key', sa.String(length=128), nullable=True))
    op.add_column('tool_calls', sa.Column('error_code', sa.String(length=50), nullable=True))
    op.add_column('tool_calls', sa.Column('result_payload', sa.JSON(), nullable=True))

    op.create_index('ix_tool_calls_request_id', 'tool_calls', ['request_id'], unique=False)
    op.create_index('ix_tool_calls_idempotency_key', 'tool_calls', ['idempotency_key'], unique=False)
    op.create_index('ix_tool_calls_error_code', 'tool_calls', ['error_code'], unique=False)
    op.create_index('ix_tool_calls_org_idempotency', 'tool_calls', ['organization_id', 'idempotency_key'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_tool_calls_org_idempotency', table_name='tool_calls')
    op.drop_index('ix_tool_calls_error_code', table_name='tool_calls')
    op.drop_index('ix_tool_calls_idempotency_key', table_name='tool_calls')
    op.drop_index('ix_tool_calls_request_id', table_name='tool_calls')

    op.drop_column('tool_calls', 'result_payload')
    op.drop_column('tool_calls', 'error_code')
    op.drop_column('tool_calls', 'idempotency_key')
    op.drop_column('tool_calls', 'request_id')
