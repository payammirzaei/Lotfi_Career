"""Job-ad details on forms and review workflow on submissions

Revision ID: a7c2d9e41b10
Revises: f38ef2badcf1
Create Date: 2026-11-09 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a7c2d9e41b10'
down_revision = 'f38ef2badcf1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('forms', schema=None) as batch_op:
        batch_op.add_column(sa.Column('location', sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column('employment_type', sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column('closes_at', sa.Date(), nullable=True))

    with op.batch_alter_table('form_submissions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('status', sa.String(length=20), nullable=False, server_default='new'))
        batch_op.add_column(sa.Column('notes', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('reviewed_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('reviewed_by_id', sa.Integer(), nullable=True))
        batch_op.create_index('ix_form_submissions_status', ['status'])
        batch_op.create_foreign_key('fk_form_submissions_reviewed_by_id_users', 'users',
                                    ['reviewed_by_id'], ['id'], ondelete='SET NULL')


def downgrade():
    with op.batch_alter_table('form_submissions', schema=None) as batch_op:
        batch_op.drop_constraint('fk_form_submissions_reviewed_by_id_users', type_='foreignkey')
        batch_op.drop_index('ix_form_submissions_status')
        batch_op.drop_column('reviewed_by_id')
        batch_op.drop_column('reviewed_at')
        batch_op.drop_column('notes')
        batch_op.drop_column('status')

    with op.batch_alter_table('forms', schema=None) as batch_op:
        batch_op.drop_column('closes_at')
        batch_op.drop_column('employment_type')
        batch_op.drop_column('location')
