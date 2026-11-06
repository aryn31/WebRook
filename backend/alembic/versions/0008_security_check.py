"""Receiver security check result on endpoints.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-06
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('endpoints', sa.Column('security_check', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('endpoints', 'security_check')
