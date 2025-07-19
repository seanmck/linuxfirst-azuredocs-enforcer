"""Add URL processing and locking functionality

Revision ID: 002_url_processing
Revises: 001_initial_schema
Create Date: 2025-07-07 10:15:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = '002_url_processing'
down_revision = '001_initial_schema'
branch_labels = None
depends_on = None


def upgrade():
    """Add URL processing tables and columns"""
    
    # Create processing_urls table for URL locking
    # Check if processing_urls table exists
    connection = op.get_bind()
    table_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.tables 
        WHERE table_name = 'processing_urls'
    """)).scalar() > 0
    
    if not table_exists:
        print("Creating processing_urls table...")
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
        print("processing_urls table added successfully.")
    else:
        print("processing_urls table already exists, skipping...")

    
    # Add unique constraint on (url, content_hash) for active processing
    op.create_unique_constraint('uq_processing_urls_url_hash', 'processing_urls', ['url', 'content_hash'])
    
    # Add indexes for efficient lookups
    # Create index if it doesn't exist
    try:
        op.create_index('ix_processing_urls_url', 'processing_urls', ['url'])
        print("Index ix_processing_urls_url created successfully.")
    except Exception:
        print("Index ix_processing_urls_url already exists, skipping...")

    # Create index if it doesn't exist
    try:
        op.create_index('ix_processing_urls_scan_id', 'processing_urls', ['scan_id'])
        print("Index ix_processing_urls_scan_id created successfully.")
    except Exception:
        print("Index ix_processing_urls_scan_id already exists, skipping...")

    # Create index if it doesn't exist
    try:
        op.create_index('ix_processing_urls_expires_at', 'processing_urls', ['expires_at'])
        print("Index ix_processing_urls_expires_at created successfully.")
    except Exception:
        print("Index ix_processing_urls_expires_at already exists, skipping...")

    # Create index if it doesn't exist
    try:
        op.create_index('ix_processing_urls_status', 'processing_urls', ['status'])
        print("Index ix_processing_urls_status created successfully.")
    except Exception:
        print("Index ix_processing_urls_status already exists, skipping...")

    
    # Add processing columns to pages table for overlap detection
    # Check if processing_started_at column exists in pages
    connection = op.get_bind()
    column_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'pages' 
        AND column_name = 'processing_started_at'
    """)).scalar() > 0
    
    if not column_exists:
        print("Adding processing_started_at column to pages...")
        op.add_column('pages', sa.Column('processing_started_at', sa.DateTime(), nullable=True))
        print("processing_started_at column added successfully.")
    else:
        print("processing_started_at column already exists in pages, skipping...")

    # Check if processing_worker_id column exists in pages
    connection = op.get_bind()
    column_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'pages' 
        AND column_name = 'processing_worker_id'
    """)).scalar() > 0
    
    if not column_exists:
        print("Adding processing_worker_id column to pages...")
        op.add_column('pages', sa.Column('processing_worker_id', sa.String(), nullable=True))
        print("processing_worker_id column added successfully.")
    else:
        print("processing_worker_id column already exists in pages, skipping...")

    # Check if processing_expires_at column exists in pages
    connection = op.get_bind()
    column_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'pages' 
        AND column_name = 'processing_expires_at'
    """)).scalar() > 0
    
    if not column_exists:
        print("Adding processing_expires_at column to pages...")
        op.add_column('pages', sa.Column('processing_expires_at', sa.DateTime(), nullable=True))
        print("processing_expires_at column added successfully.")
    else:
        print("processing_expires_at column already exists in pages, skipping...")

    
    # Add indexes for efficient overlap detection queries
    # Create index if it doesn't exist
    try:
        op.create_index('ix_pages_url_status', 'pages', ['url', 'status'])
        print("Index ix_pages_url_status created successfully.")
    except Exception:
        print("Index ix_pages_url_status already exists, skipping...")

    # Create index if it doesn't exist
    try:
        op.create_index('ix_pages_url_content_hash', 'pages', ['url', 'content_hash'])
        print("Index ix_pages_url_content_hash created successfully.")
    except Exception:
        print("Index ix_pages_url_content_hash already exists, skipping...")

    # Create index if it doesn't exist
    try:
        op.create_index('ix_pages_processing_expires_at', 'pages', ['processing_expires_at'])
        print("Index ix_pages_processing_expires_at created successfully.")
    except Exception:
        print("Index ix_pages_processing_expires_at already exists, skipping...")



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