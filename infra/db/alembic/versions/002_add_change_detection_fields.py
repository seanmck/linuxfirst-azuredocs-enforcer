"""Add change detection fields to pages table

Revision ID: 002_change_detection
Revises: 001_progress_tracking
Create Date: 2025-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '002_change_detection'
down_revision = '001_progress_tracking'
branch_labels = None
depends_on = None


def upgrade():
    """Add change detection fields to pages table"""
    
    # Add new columns to pages table
    op.add_column('pages', sa.Column('content_hash', sa.String(), nullable=True))
    op.add_column('pages', sa.Column('last_modified', sa.DateTime(), nullable=True))
    op.add_column('pages', sa.Column('github_sha', sa.String(), nullable=True))
    op.add_column('pages', sa.Column('last_scanned_at', sa.DateTime(), nullable=True))


def downgrade():
    """Remove change detection fields from pages table"""
    
    # Remove the new columns
    op.drop_column('pages', 'last_scanned_at')
    op.drop_column('pages', 'github_sha')
    op.drop_column('pages', 'last_modified')
    op.drop_column('pages', 'content_hash')