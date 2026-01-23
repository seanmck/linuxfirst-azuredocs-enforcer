"""Initial database schema with all tables and columns

Revision ID: 001_initial_schema
Revises: 
Create Date: 2025-07-07 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001_initial_schema'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """Create all tables with complete schema"""

    # Create base tables if they don't exist
    connection = op.get_bind()

    # Check if scans table exists
    scans_exists = connection.execute(text("""
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'scans'
    """)).scalar() > 0

    if not scans_exists:
        print("Creating scans table...")
        op.create_table(
            'scans',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('url', sa.String(), nullable=True),
            sa.Column('started_at', sa.DateTime(), nullable=True),
            sa.Column('finished_at', sa.DateTime(), nullable=True),
            sa.Column('status', sa.String(), nullable=True),
            sa.Column('biased_pages_count', sa.Integer(), nullable=True),
            sa.Column('flagged_snippets_count', sa.Integer(), nullable=True),
        )
        print("scans table created successfully.")
    else:
        print("scans table already exists, skipping...")

    # Check if pages table exists
    pages_exists = connection.execute(text("""
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'pages'
    """)).scalar() > 0

    if not pages_exists:
        print("Creating pages table...")
        op.create_table(
            'pages',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('scan_id', sa.Integer(), sa.ForeignKey('scans.id'), nullable=True),
            sa.Column('url', sa.String(), nullable=True),
            sa.Column('status', sa.String(), nullable=True),
        )
        print("pages table created successfully.")
    else:
        print("pages table already exists, skipping...")

    # Check if snippets table exists
    snippets_exists = connection.execute(text("""
        SELECT COUNT(*) FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'snippets'
    """)).scalar() > 0

    if not snippets_exists:
        print("Creating snippets table...")
        op.create_table(
            'snippets',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('page_id', sa.Integer(), sa.ForeignKey('pages.id'), nullable=True),
            sa.Column('context', sa.Text(), nullable=True),
            sa.Column('code', sa.Text(), nullable=True),
            sa.Column('llm_score', sa.JSON(), nullable=True),
        )
        print("snippets table created successfully.")
    else:
        print("snippets table already exists, skipping...")

    # Add mcp_holistic column to pages table
    # Check if mcp_holistic column exists in pages
    connection = op.get_bind()
    column_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'pages' 
        AND column_name = 'mcp_holistic'
    """)).scalar() > 0
    
    if not column_exists:
        print("Adding mcp_holistic column to pages...")
        op.add_column('pages', sa.Column('mcp_holistic', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
        print("mcp_holistic column added successfully.")
    else:
        print("mcp_holistic column already exists in pages, skipping...")

    
    # Add progress tracking fields to scans table
    # Check if current_phase column exists in scans
    connection = op.get_bind()
    column_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'scans' 
        AND column_name = 'current_phase'
    """)).scalar() > 0
    
    if not column_exists:
        print("Adding current_phase column to scans...")
        op.add_column('scans', sa.Column('current_phase', sa.String(), nullable=True))
        print("current_phase column added successfully.")
    else:
        print("current_phase column already exists in scans, skipping...")

    # Check if current_page_url column exists in scans
    connection = op.get_bind()
    column_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'scans' 
        AND column_name = 'current_page_url'
    """)).scalar() > 0
    
    if not column_exists:
        print("Adding current_page_url column to scans...")
        op.add_column('scans', sa.Column('current_page_url', sa.String(), nullable=True))
        print("current_page_url column added successfully.")
    else:
        print("current_page_url column already exists in scans, skipping...")

    # Check if total_pages_found column exists in scans
    connection = op.get_bind()
    column_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'scans' 
        AND column_name = 'total_pages_found'
    """)).scalar() > 0
    
    if not column_exists:
        print("Adding total_pages_found column to scans...")
        op.add_column('scans', sa.Column('total_pages_found', sa.Integer(), default=0))
        print("total_pages_found column added successfully.")
    else:
        print("total_pages_found column already exists in scans, skipping...")

    # Check if pages_processed column exists in scans
    connection = op.get_bind()
    column_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'scans' 
        AND column_name = 'pages_processed'
    """)).scalar() > 0
    
    if not column_exists:
        print("Adding pages_processed column to scans...")
        op.add_column('scans', sa.Column('pages_processed', sa.Integer(), default=0))
        print("pages_processed column added successfully.")
    else:
        print("pages_processed column already exists in scans, skipping...")

    # Check if snippets_processed column exists in scans
    connection = op.get_bind()
    column_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'scans' 
        AND column_name = 'snippets_processed'
    """)).scalar() > 0
    
    if not column_exists:
        print("Adding snippets_processed column to scans...")
        op.add_column('scans', sa.Column('snippets_processed', sa.Integer(), default=0))
        print("snippets_processed column added successfully.")
    else:
        print("snippets_processed column already exists in scans, skipping...")

    # Check if phase_progress column exists in scans
    connection = op.get_bind()
    column_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'scans' 
        AND column_name = 'phase_progress'
    """)).scalar() > 0
    
    if not column_exists:
        print("Adding phase_progress column to scans...")
        op.add_column('scans', sa.Column('phase_progress', sa.JSON(), nullable=True))
        print("phase_progress column added successfully.")
    else:
        print("phase_progress column already exists in scans, skipping...")

    # Check if error_log column exists in scans
    connection = op.get_bind()
    column_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'scans' 
        AND column_name = 'error_log'
    """)).scalar() > 0
    
    if not column_exists:
        print("Adding error_log column to scans...")
        op.add_column('scans', sa.Column('error_log', sa.JSON(), nullable=True))
        print("error_log column added successfully.")
    else:
        print("error_log column already exists in scans, skipping...")

    # Check if phase_timestamps column exists in scans
    connection = op.get_bind()
    column_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'scans' 
        AND column_name = 'phase_timestamps'
    """)).scalar() > 0
    
    if not column_exists:
        print("Adding phase_timestamps column to scans...")
        op.add_column('scans', sa.Column('phase_timestamps', sa.JSON(), nullable=True))
        print("phase_timestamps column added successfully.")
    else:
        print("phase_timestamps column already exists in scans, skipping...")

    # Check if estimated_completion column exists in scans
    connection = op.get_bind()
    column_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'scans' 
        AND column_name = 'estimated_completion'
    """)).scalar() > 0
    
    if not column_exists:
        print("Adding estimated_completion column to scans...")
        op.add_column('scans', sa.Column('estimated_completion', sa.DateTime(), nullable=True))
        print("estimated_completion column added successfully.")
    else:
        print("estimated_completion column already exists in scans, skipping...")

    # Check if performance_metrics column exists in scans
    connection = op.get_bind()
    column_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'scans' 
        AND column_name = 'performance_metrics'
    """)).scalar() > 0
    
    if not column_exists:
        print("Adding performance_metrics column to scans...")
        op.add_column('scans', sa.Column('performance_metrics', sa.JSON(), nullable=True))
        print("performance_metrics column added successfully.")
    else:
        print("performance_metrics column already exists in scans, skipping...")

    
    # Add change detection fields to pages table
    # Check if content_hash column exists in pages
    connection = op.get_bind()
    column_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'pages' 
        AND column_name = 'content_hash'
    """)).scalar() > 0
    
    if not column_exists:
        print("Adding content_hash column to pages...")
        op.add_column('pages', sa.Column('content_hash', sa.String(), nullable=True))
        print("content_hash column added successfully.")
    else:
        print("content_hash column already exists in pages, skipping...")

    # Check if last_modified column exists in pages
    connection = op.get_bind()
    column_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'pages' 
        AND column_name = 'last_modified'
    """)).scalar() > 0
    
    if not column_exists:
        print("Adding last_modified column to pages...")
        op.add_column('pages', sa.Column('last_modified', sa.DateTime(), nullable=True))
        print("last_modified column added successfully.")
    else:
        print("last_modified column already exists in pages, skipping...")

    # Check if github_sha column exists in pages
    connection = op.get_bind()
    column_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'pages' 
        AND column_name = 'github_sha'
    """)).scalar() > 0
    
    if not column_exists:
        print("Adding github_sha column to pages...")
        op.add_column('pages', sa.Column('github_sha', sa.String(), nullable=True))
        print("github_sha column added successfully.")
    else:
        print("github_sha column already exists in pages, skipping...")

    # Check if last_scanned_at column exists in pages
    connection = op.get_bind()
    column_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'pages' 
        AND column_name = 'last_scanned_at'
    """)).scalar() > 0
    
    if not column_exists:
        print("Adding last_scanned_at column to pages...")
        op.add_column('pages', sa.Column('last_scanned_at', sa.DateTime(), nullable=True))
        print("last_scanned_at column added successfully.")
    else:
        print("last_scanned_at column already exists in pages, skipping...")

    
    # Add scan cancellation fields to scans table
    # Check if cancellation_requested column exists in scans
    connection = op.get_bind()
    column_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'scans' 
        AND column_name = 'cancellation_requested'
    """)).scalar() > 0
    
    if not column_exists:
        print("Adding cancellation_requested column to scans...")
        op.add_column('scans', sa.Column('cancellation_requested', sa.Boolean(), nullable=True, default=False))
        print("cancellation_requested column added successfully.")
    else:
        print("cancellation_requested column already exists in scans, skipping...")

    # Check if cancellation_requested_at column exists in scans
    connection = op.get_bind()
    column_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'scans' 
        AND column_name = 'cancellation_requested_at'
    """)).scalar() > 0
    
    if not column_exists:
        print("Adding cancellation_requested_at column to scans...")
        op.add_column('scans', sa.Column('cancellation_requested_at', sa.DateTime(), nullable=True))
        print("cancellation_requested_at column added successfully.")
    else:
        print("cancellation_requested_at column already exists in scans, skipping...")

    # Check if cancellation_reason column exists in scans
    connection = op.get_bind()
    column_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'scans' 
        AND column_name = 'cancellation_reason'
    """)).scalar() > 0
    
    if not column_exists:
        print("Adding cancellation_reason column to scans...")
        op.add_column('scans', sa.Column('cancellation_reason', sa.String(), nullable=True))
        print("cancellation_reason column added successfully.")
    else:
        print("cancellation_reason column already exists in scans, skipping...")

    
    # Create performance indexes
    # Create index if it doesn't exist
    try:
        op.create_index('idx_scans_status_started_at', 'scans', ['status', 'started_at'])
        print("Index idx_scans_status_started_at created successfully.")
    except Exception:
        print("Index idx_scans_status_started_at already exists, skipping...")

    # Create index if it doesn't exist
    try:
        op.create_index('idx_pages_scan_id', 'pages', ['scan_id'])
        print("Index idx_pages_scan_id created successfully.")
    except Exception:
        print("Index idx_pages_scan_id already exists, skipping...")

    # Create index if it doesn't exist
    try:
        op.create_index('idx_snippets_page_id', 'snippets', ['page_id'])
        print("Index idx_snippets_page_id created successfully.")
    except Exception:
        print("Index idx_snippets_page_id already exists, skipping...")

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