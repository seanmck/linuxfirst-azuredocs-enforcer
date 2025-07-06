"""Add performance indexes for faster queries

Revision ID: 003_performance_indexes
Revises: 002_change_detection
Create Date: 2025-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '003_performance_indexes'
down_revision = '002_change_detection'
branch_labels = None
depends_on = None


def upgrade():
    """Add performance indexes for faster queries"""
    
    # Index on scans table for common queries
    op.create_index('idx_scans_status_started_at', 'scans', ['status', 'started_at'])
    
    # Index on pages table for joins
    op.create_index('idx_pages_scan_id', 'pages', ['scan_id'])
    
    # Index on snippets table for joins
    op.create_index('idx_snippets_page_id', 'snippets', ['page_id'])
    
    # Index for filtering snippets by windows_biased JSON field (most critical for performance)
    op.execute("CREATE INDEX IF NOT EXISTS idx_snippets_windows_biased ON snippets USING btree ((llm_score->>'windows_biased'))")


def downgrade():
    """Remove performance indexes"""
    
    # Remove the indexes
    op.execute("DROP INDEX IF EXISTS idx_snippets_windows_biased")
    op.drop_index('idx_snippets_page_id', 'snippets')
    op.drop_index('idx_pages_scan_id', 'pages')
    op.drop_index('idx_scans_status_started_at', 'scans')