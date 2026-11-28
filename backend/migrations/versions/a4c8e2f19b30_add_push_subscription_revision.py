"""add push_subscriptions revision column

Revision ID: a4c8e2f19b30
Revises: 71a56dd5987e
Create Date: 2026-11-28 00:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a4c8e2f19b30'
down_revision = '71a56dd5987e'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('push_subscriptions', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('revision', sa.Integer(), nullable=False, server_default='1')
        )


def downgrade():
    with op.batch_alter_table('push_subscriptions', schema=None) as batch_op:
        batch_op.drop_column('revision')
