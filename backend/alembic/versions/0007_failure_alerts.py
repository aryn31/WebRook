"""Email alerts when an endpoint keeps failing.

endpoints: a count of failed attempts in a row, when the current run of failures started, and when the alert
for it was emailed. users: whether they want these emails.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-06
"""
from alembic import op
import sqlalchemy as sa


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('endpoints', sa.Column('consecutive_failures', sa.Integer(), server_default='0', nullable=False))
    op.add_column('endpoints', sa.Column('failing_since', sa.DateTime(timezone=True), nullable=True))
    op.add_column('endpoints', sa.Column('alert_sent_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('users', sa.Column('failure_alerts', sa.Boolean(), server_default=sa.true(), nullable=False))


def downgrade() -> None:
    op.drop_column('users', 'failure_alerts')
    op.drop_column('endpoints', 'alert_sent_at')
    op.drop_column('endpoints', 'failing_since')
    op.drop_column('endpoints', 'consecutive_failures')
