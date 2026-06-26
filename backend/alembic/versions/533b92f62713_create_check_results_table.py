"""create check_results table

Revision ID: 533b92f62713
Revises: 6518c1e84b71
Create Date: 2026-06-26 23:49:52.019595

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '533b92f62713'
down_revision: Union[str, Sequence[str], None] = '6518c1e84b71'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'check_results',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('monitor_id', sa.Uuid(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status_code', sa.Integer(), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('response_size_bytes', sa.Integer(), nullable=True),
        sa.Column('cert_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.Column('error', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('assertion_results', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_check_results_monitor_id'), 'check_results', ['monitor_id'], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_check_results_monitor_id'), table_name='check_results')
    op.drop_table('check_results')
