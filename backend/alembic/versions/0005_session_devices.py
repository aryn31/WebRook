"""Device details on sessions, for the Security page (where you're logged in).

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-04
"""
from alembic import op
import sqlalchemy as sa


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('sessions', sa.Column('ip_address', sa.String(length=64), nullable=True))
    op.add_column('sessions', sa.Column('user_agent', sa.String(length=512), nullable=True))
    op.add_column('sessions', sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('sessions', 'last_seen_at')
    op.drop_column('sessions', 'user_agent')
    op.drop_column('sessions', 'ip_address')
