"""Add file processing history for recovery and audit trails

Revision ID: 007_add_file_processing_history
Revises: 006_add_commit_tracking
Create Date: 2025-01-09 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = '007_add_file_processing_history'
down_revision = '006_add_commit_tracking'
branch_labels = None
depends_on = None


def upgrade():
    """Create file processing history table"""
    
    # Create file_processing_history table
    # Check if file_processing_history table exists
    connection = op.get_bind()
    table_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.tables 
        WHERE table_name = 'file_processing_history'
    """)).scalar() > 0
    
    if not table_exists:
        print("Creating file_processing_history table...")
        op.create_table('file_processing_history',
            sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column('file_path', sa.String(500), nullable=False),
            sa.Column('github_sha', sa.String(40), nullable=False),
            sa.Column('scan_id', sa.Integer(), nullable=False),
            sa.Column('processed_at', sa.DateTime(), nullable=False),
            sa.Column('processing_result', sa.String(20), nullable=False),  # completed, failed, skipped
            sa.Column('processing_duration_ms', sa.Integer(), nullable=True),
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('snippets_found', sa.Integer(), nullable=True, default=0),
            sa.Column('bias_detected', sa.Boolean(), nullable=True, default=False),
            sa.Column('worker_id', sa.String(100), nullable=True),
            sa.Column('commit_sha', sa.String(40), nullable=True),
            
            # Foreign key to scans table
            sa.ForeignKeyConstraint(['scan_id'], ['scans.id'], ondelete='CASCADE'),
            
            # Unique constraint to prevent duplicate processing records
            sa.UniqueConstraint('file_path', 'github_sha', 'scan_id', name='uq_file_processing_history')
        )
        print("file_processing_history table added successfully.")
    else:
        print("file_processing_history table already exists, skipping...")

    
    # Create indexes for efficient lookups
    # Create index if it doesn't exist
    try:
        op.create_index('idx_file_processing_history_path_sha', 'file_processing_history', ['file_path', 'github_sha'])
        print("Index idx_file_processing_history_path_sha created successfully.")
    except Exception:
        print("Index idx_file_processing_history_path_sha already exists, skipping...")

    # Create index if it doesn't exist
    try:
        op.create_index('idx_file_processing_history_scan_id', 'file_processing_history', ['scan_id'])
        print("Index idx_file_processing_history_scan_id created successfully.")
    except Exception:
        print("Index idx_file_processing_history_scan_id already exists, skipping...")

    # Create index if it doesn't exist
    try:
        op.create_index('idx_file_processing_history_processed_at', 'file_processing_history', ['processed_at'])
        print("Index idx_file_processing_history_processed_at created successfully.")
    except Exception:
        print("Index idx_file_processing_history_processed_at already exists, skipping...")

    # Create index if it doesn't exist
    try:
        op.create_index('idx_file_processing_history_result', 'file_processing_history', ['processing_result'])
        print("Index idx_file_processing_history_result created successfully.")
    except Exception:
        print("Index idx_file_processing_history_result already exists, skipping...")

    # Create index if it doesn't exist
    try:
        op.create_index('idx_file_processing_history_commit_sha', 'file_processing_history', ['commit_sha'])
        print("Index idx_file_processing_history_commit_sha created successfully.")
    except Exception:
        print("Index idx_file_processing_history_commit_sha already exists, skipping...")

    
    # Add enhanced processing state tracking to pages table
    # Check if processing_state column exists in pages
    connection = op.get_bind()
    column_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'pages' 
        AND column_name = 'processing_state'
    """)).scalar() > 0
    
    if not column_exists:
        print("Adding processing_state column to pages...")
        op.add_column('pages', sa.Column('processing_state', sa.String(30), nullable=True, default='discovered'))
        print("processing_state column added successfully.")
    else:
        print("processing_state column already exists in pages, skipping...")

    
    # Update existing pages to have the new processing state
    op.execute("UPDATE pages SET processing_state = 'completed' WHERE status = 'processed'")
    op.execute("UPDATE pages SET processing_state = 'failed' WHERE status = 'error'")
    op.execute("UPDATE pages SET processing_state = 'queued' WHERE status = 'queued'")
    op.execute("UPDATE pages SET processing_state = 'discovered' WHERE status IN ('discovered', 'crawled')")
    
    # Add index for processing state
    # Create index if it doesn't exist
    try:
        op.create_index('idx_pages_processing_state', 'pages', ['processing_state'])
        print("Index idx_pages_processing_state created successfully.")
    except Exception:
        print("Index idx_pages_processing_state already exists, skipping...")

    

def downgrade():
    """Remove file processing history table"""
    
    # Remove processing state from pages table
    op.drop_index('idx_pages_processing_state', table_name='pages')
    op.drop_column('pages', 'processing_state')
    
    # Remove file_processing_history table
    op.drop_index('idx_file_processing_history_commit_sha', table_name='file_processing_history')
    op.drop_index('idx_file_processing_history_result', table_name='file_processing_history')
    op.drop_index('idx_file_processing_history_processed_at', table_name='file_processing_history')
    op.drop_index('idx_file_processing_history_scan_id', table_name='file_processing_history')
    op.drop_index('idx_file_processing_history_path_sha', table_name='file_processing_history')
    op.drop_table('file_processing_history')