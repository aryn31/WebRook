"""Customer portal: consumers, and which consumer an endpoint or event belongs to.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-07
"""
from alembic import op
import sqlalchemy as sa


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'consumers',
        sa.Column('id', sa.String(length=32), nullable=False),
        sa.Column('user_id', sa.String(length=32), nullable=False),
        sa.Column('uid', sa.String(length=100), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'uid', name='uq_consumers_user_id_uid'),
    )
    op.create_index('ix_consumers_user_id', 'consumers', ['user_id'])
    op.add_column('endpoints', sa.Column('consumer_id', sa.String(length=32), nullable=True))
    op.create_foreign_key('fk_endpoints_consumer_id', 'endpoints', 'consumers', ['consumer_id'], ['id'],
                          ondelete='SET NULL')
    op.create_index('ix_endpoints_consumer_id', 'endpoints', ['consumer_id'])
    op.add_column('events', sa.Column('consumer_id', sa.String(length=32), nullable=True))
    op.create_foreign_key('fk_events_consumer_id', 'events', 'consumers', ['consumer_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint('fk_events_consumer_id', 'events', type_='foreignkey')
    op.drop_column('events', 'consumer_id')
    op.drop_index('ix_endpoints_consumer_id', table_name='endpoints')
    op.drop_constraint('fk_endpoints_consumer_id', 'endpoints', type_='foreignkey')
    op.drop_column('endpoints', 'consumer_id')
    op.drop_index('ix_consumers_user_id', table_name='consumers')
    op.drop_table('consumers')
