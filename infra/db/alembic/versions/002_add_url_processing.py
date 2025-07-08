"""Add URL processing and locking functionality

Revision ID: 002_url_processing
Revises: 001_initial_schema
Create Date: 2025-07-07 10:15:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '002_url_processing'
down_revision = '001_initial_schema'
branch_labels = None
depends_on = None


def upgrade():
    """Add URL processing tables and columns"""
    
    # Create processing_urls table for URL locking
    op.create_table('processing_urls',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('url', sa.String(), nullable=False),
        sa.Column('content_hash', sa.String(), nullable=False),
        sa.Column('scan_id', sa.Integer(), nullable=False),
        sa.Column('worker_id', sa.String(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, default='processing'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Add unique constraint on (url, content_hash) for active processing
    op.create_unique_constraint('uq_processing_urls_url_hash', 'processing_urls', ['url', 'content_hash'])
    
    # Add indexes for efficient lookups
    op.create_index('ix_processing_urls_url', 'processing_urls', ['url'])
    op.create_index('ix_processing_urls_scan_id', 'processing_urls', ['scan_id'])
    op.create_index('ix_processing_urls_expires_at', 'processing_urls', ['expires_at'])
    op.create_index('ix_processing_urls_status', 'processing_urls', ['status'])
    
    # Add processing columns to pages table for overlap detection
    op.add_column('pages', sa.Column('processing_started_at', sa.DateTime(), nullable=True))
    op.add_column('pages', sa.Column('processing_worker_id', sa.String(), nullable=True))
    op.add_column('pages', sa.Column('processing_expires_at', sa.DateTime(), nullable=True))
    
    # Add indexes for efficient overlap detection queries
    op.create_index('ix_pages_url_status', 'pages', ['url', 'status'])
    op.create_index('ix_pages_url_content_hash', 'pages', ['url', 'content_hash'])
    op.create_index('ix_pages_processing_expires_at', 'pages', ['processing_expires_at'])


def downgrade():
    """Remove URL processing functionality"""
    
    # Remove processing-related indexes and columns
    op.drop_index('ix_pages_processing_expires_at', table_name='pages')
    op.drop_index('ix_pages_url_content_hash', table_name='pages')
    op.drop_index('ix_pages_url_status', table_name='pages')
    op.drop_column('pages', 'processing_expires_at')
    op.drop_column('pages', 'processing_worker_id')
    op.drop_column('pages', 'processing_started_at')
    
    # Drop processing_urls table
    op.drop_index('ix_processing_urls_status', table_name='processing_urls')
    op.drop_index('ix_processing_urls_expires_at', table_name='processing_urls')
    op.drop_index('ix_processing_urls_scan_id', table_name='processing_urls')
    op.drop_index('ix_processing_urls_url', table_name='processing_urls')
    op.drop_constraint('uq_processing_urls_url_hash', 'processing_urls', type_='unique')
    op.drop_table('processing_urls')