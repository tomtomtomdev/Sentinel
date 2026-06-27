"""create auth_sources and token_states tables

Revision ID: a7c3f1e9d2b4
Revises: 533b92f62713
Create Date: 2026-06-27 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a7c3f1e9d2b4'
down_revision: Union[str, Sequence[str], None] = '533b92f62713'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'auth_sources',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('mode', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('request', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('oauth', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('extractor', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('expiry', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('token_type', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('injection', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('refresh_before_expiry_seconds', sa.Integer(), nullable=False),
        sa.Column('refresh_on_status', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'token_states',
        sa.Column('auth_source_id', sa.Uuid(), nullable=False),
        sa.Column('token', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('refresh_token', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('token_type', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('obtained_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_refresh_error', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.PrimaryKeyConstraint('auth_source_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('token_states')
    op.drop_table('auth_sources')
