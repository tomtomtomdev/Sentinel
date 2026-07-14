"""create monitor_states table

Revision ID: e11783af3b0a
Revises: a7c3f1e9d2b4
Create Date: 2026-07-14 20:30:02.871803

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'e11783af3b0a'
down_revision: Union[str, Sequence[str], None] = 'a7c3f1e9d2b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'monitor_states',
        sa.Column('monitor_id', sa.Uuid(), nullable=False),
        sa.Column('status', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('since', sa.DateTime(timezone=True), nullable=False),
        sa.Column('consecutive_failures', sa.Integer(), nullable=False),
        sa.Column('consecutive_successes', sa.Integer(), nullable=False),
        sa.Column('last_check_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('monitor_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('monitor_states')
