"""Add progress tracking fields to scans table

Revision ID: 001_progress_tracking
Revises: 
Create Date: 2024-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '001_progress_tracking'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """Add progress tracking fields to scans table"""
    
    # Add new columns to scans table
    op.add_column('scans', sa.Column('current_phase', sa.String(), nullable=True))
    op.add_column('scans', sa.Column('current_page_url', sa.String(), nullable=True))
    op.add_column('scans', sa.Column('total_pages_found', sa.Integer(), default=0))
    op.add_column('scans', sa.Column('pages_processed', sa.Integer(), default=0))
    op.add_column('scans', sa.Column('snippets_processed', sa.Integer(), default=0))
    op.add_column('scans', sa.Column('phase_progress', sa.JSON(), nullable=True))
    op.add_column('scans', sa.Column('error_log', sa.JSON(), nullable=True))
    op.add_column('scans', sa.Column('phase_timestamps', sa.JSON(), nullable=True))
    op.add_column('scans', sa.Column('estimated_completion', sa.DateTime(), nullable=True))
    op.add_column('scans', sa.Column('performance_metrics', sa.JSON(), nullable=True))


def downgrade():
    """Remove progress tracking fields from scans table"""
    
    # Remove the new columns
    op.drop_column('scans', 'performance_metrics')
    op.drop_column('scans', 'estimated_completion')
    op.drop_column('scans', 'phase_timestamps')
    op.drop_column('scans', 'error_log')
    op.drop_column('scans', 'phase_progress')
    op.drop_column('scans', 'snippets_processed')
    op.drop_column('scans', 'pages_processed')
    op.drop_column('scans', 'total_pages_found')
    op.drop_column('scans', 'current_page_url')
    op.drop_column('scans', 'current_phase')