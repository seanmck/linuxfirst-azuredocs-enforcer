"""Initial database schema with all tables and columns

Revision ID: 001_initial_schema
Revises: 
Create Date: 2025-07-07 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001_initial_schema'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """Create all tables with complete schema"""
    
    # Note: Base tables (scans, pages, snippets) are created by schema.sql
    # This migration adds all the additional columns and new tables
    
    # Add mcp_holistic column to pages table
    op.add_column('pages', sa.Column('mcp_holistic', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    
    # Add progress tracking fields to scans table
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
    
    # Add change detection fields to pages table
    op.add_column('pages', sa.Column('content_hash', sa.String(), nullable=True))
    op.add_column('pages', sa.Column('last_modified', sa.DateTime(), nullable=True))
    op.add_column('pages', sa.Column('github_sha', sa.String(), nullable=True))
    op.add_column('pages', sa.Column('last_scanned_at', sa.DateTime(), nullable=True))
    
    # Add scan cancellation fields to scans table
    op.add_column('scans', sa.Column('cancellation_requested', sa.Boolean(), nullable=True, default=False))
    op.add_column('scans', sa.Column('cancellation_requested_at', sa.DateTime(), nullable=True))
    op.add_column('scans', sa.Column('cancellation_reason', sa.String(), nullable=True))
    
    # Create performance indexes
    op.create_index('idx_scans_status_started_at', 'scans', ['status', 'started_at'])
    op.create_index('idx_pages_scan_id', 'pages', ['scan_id'])
    op.create_index('idx_snippets_page_id', 'snippets', ['page_id'])
    op.execute("CREATE INDEX IF NOT EXISTS idx_snippets_windows_biased ON snippets USING btree ((llm_score->>'windows_biased'))")
    


def downgrade():
    """Drop all additional columns and tables"""
    
    # Remove performance indexes
    op.execute("DROP INDEX IF EXISTS idx_snippets_windows_biased")
    op.drop_index('idx_snippets_page_id', 'snippets')
    op.drop_index('idx_pages_scan_id', 'pages')
    op.drop_index('idx_scans_status_started_at', 'scans')
    
    # Remove scan cancellation columns
    op.drop_column('scans', 'cancellation_reason')
    op.drop_column('scans', 'cancellation_requested_at')
    op.drop_column('scans', 'cancellation_requested')
    
    # Remove change detection columns
    op.drop_column('pages', 'last_scanned_at')
    op.drop_column('pages', 'github_sha')
    op.drop_column('pages', 'last_modified')
    op.drop_column('pages', 'content_hash')
    
    # Remove progress tracking columns
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
    
    # Remove mcp_holistic column
    op.drop_column('pages', 'mcp_holistic')