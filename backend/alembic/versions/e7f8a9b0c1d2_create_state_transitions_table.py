"""create state_transitions table

Revision ID: e7f8a9b0c1d2
Revises: d4a1b2c3e5f6
Create Date: 2026-07-16 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7f8a9b0c1d2'
down_revision: Union[str, Sequence[str], None] = 'd4a1b2c3e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'state_transitions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('monitor_id', sa.Uuid(), nullable=False),
        sa.Column('from_status', sa.String(), nullable=False),
        sa.Column('to_status', sa.String(), nullable=False),
        sa.Column('at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_state_transitions_monitor_id'), 'state_transitions', ['monitor_id'], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_state_transitions_monitor_id'), table_name='state_transitions')
    op.drop_table('state_transitions')
