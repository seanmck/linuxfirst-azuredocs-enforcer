"""Add commit tracking for safe incremental scans

Revision ID: 006_commit_tracking
Revises: 005_add_page_unique_constraint
Create Date: 2025-01-09 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '006_commit_tracking'
down_revision = '005_add_page_unique_constraint'
branch_labels = None
depends_on = None


def upgrade():
    """Add commit tracking fields to scans table"""
    
    # Add commit tracking columns to scans table
    op.add_column('scans', sa.Column('working_commit_sha', sa.String(40), nullable=True))
    op.add_column('scans', sa.Column('last_commit_sha', sa.String(40), nullable=True))
    op.add_column('scans', sa.Column('baseline_type', sa.String(20), nullable=True))
    
    # Add scan completion tracking columns
    op.add_column('scans', sa.Column('total_files_discovered', sa.Integer(), nullable=True, default=0))
    op.add_column('scans', sa.Column('total_files_queued', sa.Integer(), nullable=True, default=0))
    op.add_column('scans', sa.Column('total_files_completed', sa.Integer(), nullable=True, default=0))
    
    # Add indexes for efficient baseline queries
    op.create_index('idx_scans_url_status_finished', 'scans', ['url', 'status', 'finished_at'])
    op.create_index('idx_scans_last_commit_sha', 'scans', ['last_commit_sha'])
    op.create_index('idx_scans_working_commit_sha', 'scans', ['working_commit_sha'])


def downgrade():
    """Remove commit tracking fields"""
    
    # Remove indexes
    op.drop_index('idx_scans_working_commit_sha', table_name='scans')
    op.drop_index('idx_scans_last_commit_sha', table_name='scans')
    op.drop_index('idx_scans_url_status_finished', table_name='scans')
    
    # Remove scan completion tracking columns
    op.drop_column('scans', 'total_files_completed')
    op.drop_column('scans', 'total_files_queued')
    op.drop_column('scans', 'total_files_discovered')
    
    # Remove commit tracking columns
    op.drop_column('scans', 'baseline_type')
    op.drop_column('scans', 'last_commit_sha')
    op.drop_column('scans', 'working_commit_sha')