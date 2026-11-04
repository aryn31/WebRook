"""Email verification: users.email_verified_at and emailed codes.

Accounts that already exist are treated as verified.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-04
"""
from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('email_verified_at', sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE users SET email_verified_at = created_at")

    op.create_table(
        'email_codes',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.String(length=32), nullable=False),
        sa.Column('purpose', sa.String(length=32), nullable=False),
        sa.Column('code_hash', sa.String(length=64), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_email_codes_user_id', 'email_codes', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_email_codes_user_id', table_name='email_codes')
    op.drop_table('email_codes')
    op.drop_column('users', 'email_verified_at')
