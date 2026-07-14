"""create check_rollups table

Revision ID: c9d2e5f80a14
Revises: e11783af3b0a
Create Date: 2026-07-14 22:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9d2e5f80a14'
down_revision: Union[str, Sequence[str], None] = 'e11783af3b0a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'check_rollups',
        sa.Column('monitor_id', sa.Uuid(), nullable=False),
        sa.Column('bucket_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('checks', sa.Integer(), nullable=False),
        sa.Column('failures', sa.Integer(), nullable=False),
        sa.Column('latency_p50_ms', sa.Integer(), nullable=False),
        sa.Column('latency_p95_ms', sa.Integer(), nullable=False),
        sa.Column('latency_p99_ms', sa.Integer(), nullable=False),
        sa.Column('latency_sum_ms', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('monitor_id', 'bucket_start'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('check_rollups')
