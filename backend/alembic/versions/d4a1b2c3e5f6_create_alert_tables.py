"""create alert_channels and notification_logs tables

Revision ID: d4a1b2c3e5f6
Revises: c9d2e5f80a14
Create Date: 2026-07-15 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd4a1b2c3e5f6'
down_revision: Union[str, Sequence[str], None] = 'c9d2e5f80a14'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'alert_channels',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('type', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'notification_logs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('channel_id', sa.Uuid(), nullable=False),
        sa.Column('monitor_id', sa.Uuid(), nullable=False),
        sa.Column('transition_to', sa.String(), nullable=False),
        sa.Column('transition_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('fired_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ok', sa.Boolean(), nullable=False),
        sa.Column('detail', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'channel_id',
            'monitor_id',
            'transition_at',
            name='uq_notification_logs_channel_monitor_transition',
        ),
    )
    op.create_index(
        op.f('ix_notification_logs_channel_id'), 'notification_logs', ['channel_id'], unique=False
    )
    op.create_index(
        op.f('ix_notification_logs_monitor_id'), 'notification_logs', ['monitor_id'], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_notification_logs_monitor_id'), table_name='notification_logs')
    op.drop_index(op.f('ix_notification_logs_channel_id'), table_name='notification_logs')
    op.drop_table('notification_logs')
    op.drop_table('alert_channels')
