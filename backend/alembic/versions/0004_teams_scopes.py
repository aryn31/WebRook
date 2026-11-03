"""Milestone 4: team accounts, scoped API keys, custom retry schedules, and the acting user in audit entries.

Pattern subscriptions ("order.*") and bulk replay need no schema changes.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'account_members',
        sa.Column('account_id', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.String(length=32), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('invited_by_user_id', sa.String(length=32), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['account_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['invited_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('account_id', 'user_id'),
    )
    op.create_index('ix_account_members_user_id', 'account_members', ['user_id'], unique=False)

    op.create_table(
        'account_invites',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('account_id', sa.String(length=32), nullable=False),
        sa.Column('email', sa.String(length=320), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('invited_by_user_id', sa.String(length=32), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['account_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['invited_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash'),
    )
    op.create_index('ix_account_invites_account_id', 'account_invites', ['account_id'], unique=False)

    op.add_column('sessions', sa.Column('account_id', sa.String(length=32), nullable=True))
    op.create_foreign_key('fk_sessions_account_id', 'sessions', 'users', ['account_id'], ['id'], ondelete='SET NULL')

    # NULL scopes = every API scope, so existing keys keep working exactly as before.
    op.add_column('api_keys', sa.Column('scopes', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('api_keys', sa.Column('created_by_user_id', sa.String(length=32), nullable=True))
    op.create_foreign_key('fk_api_keys_created_by', 'api_keys', 'users', ['created_by_user_id'], ['id'],
                          ondelete='SET NULL')
    # Before teams, every key was made by the account owner.
    op.execute("UPDATE api_keys SET created_by_user_id = user_id")

    op.add_column('endpoints', sa.Column('retry_schedule', postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    op.add_column('audit_logs', sa.Column('actor_user_id', sa.String(length=32), nullable=True))
    op.create_foreign_key('fk_audit_logs_actor_user_id', 'audit_logs', 'users', ['actor_user_id'], ['id'],
                          ondelete='SET NULL')
    op.execute("UPDATE audit_logs SET actor_user_id = user_id")


def downgrade() -> None:
    op.drop_constraint('fk_audit_logs_actor_user_id', 'audit_logs', type_='foreignkey')
    op.drop_column('audit_logs', 'actor_user_id')
    op.drop_column('endpoints', 'retry_schedule')
    op.drop_constraint('fk_api_keys_created_by', 'api_keys', type_='foreignkey')
    op.drop_column('api_keys', 'created_by_user_id')
    op.drop_column('api_keys', 'scopes')
    op.drop_constraint('fk_sessions_account_id', 'sessions', type_='foreignkey')
    op.drop_column('sessions', 'account_id')
    op.drop_index('ix_account_invites_account_id', table_name='account_invites')
    op.drop_table('account_invites')
    op.drop_index('ix_account_members_user_id', table_name='account_members')
    op.drop_table('account_members')
