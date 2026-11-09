"""Initial schema (users, forms, submissions)

Revision ID: f38ef2badcf1
Revises:
Create Date: 2026-01-01 20:01:55.337037

The original revision only added two columns and assumed the tables already
existed (created by db.create_all()), which fails on a fresh PostgreSQL
database. It now creates the full schema. The revision id is unchanged, so
databases already stamped with it are unaffected.
"""
from alembic import op
import sqlalchemy as sa


revision = 'f38ef2badcf1'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('username', sa.String(length=80), nullable=False),
        sa.Column('email', sa.String(length=120), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('is_admin', sa.Boolean(), nullable=True),
        sa.Column('is_approved', sa.Boolean(), nullable=True),
    )
    op.create_index('ix_users_username', 'users', ['username'], unique=True)
    op.create_index('ix_users_email', 'users', ['email'], unique=True)

    op.create_table(
        'forms',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('form_template', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=True),
    )
    op.create_index('ix_forms_created_at', 'forms', ['created_at'])

    op.create_table(
        'form_submissions',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('form_id', sa.Integer(), sa.ForeignKey('forms.id'), nullable=False),
        sa.Column('submitted_at', sa.DateTime(), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.String(length=255), nullable=True),
    )
    op.create_index('ix_form_submissions_form_id', 'form_submissions', ['form_id'])
    op.create_index('ix_form_submissions_submitted_at', 'form_submissions', ['submitted_at'])

    op.create_table(
        'form_submission_fields',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('submission_id', sa.Integer(), sa.ForeignKey('form_submissions.id'), nullable=False),
        sa.Column('field_name', sa.String(length=100), nullable=False),
        sa.Column('field_value', sa.Text(), nullable=True),
        sa.Column('file_path', sa.String(length=500), nullable=True),
        sa.Column('file_name', sa.String(length=255), nullable=True),
    )
    op.create_index('ix_form_submission_fields_submission_id', 'form_submission_fields', ['submission_id'])
    op.create_index('ix_form_submission_fields_field_name', 'form_submission_fields', ['field_name'])


def downgrade():
    op.drop_table('form_submission_fields')
    op.drop_table('form_submissions')
    op.drop_table('forms')
    op.drop_table('users')
