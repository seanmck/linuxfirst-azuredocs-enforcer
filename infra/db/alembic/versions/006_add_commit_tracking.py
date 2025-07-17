"""Add commit tracking for safe incremental scans

Revision ID: 006_add_commit_tracking
Revises: 005_add_page_unique_constraint
Create Date: 2025-01-09 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = '006_add_commit_tracking'
down_revision = '005_add_page_unique_constraint'
branch_labels = None
depends_on = None


def upgrade():
    """Add commit tracking fields to scans table"""
    
    # Add commit tracking columns to scans table
    # Check if working_commit_sha column exists in scans
    connection = op.get_bind()
    column_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'scans' 
        AND column_name = 'working_commit_sha'
    """)).scalar() > 0
    
    if not column_exists:
        print("Adding working_commit_sha column to scans...")
        op.add_column('scans', sa.Column('working_commit_sha', sa.String(40), nullable=True))
        print("working_commit_sha column added successfully.")
    else:
        print("working_commit_sha column already exists in scans, skipping...")

    # Check if last_commit_sha column exists in scans
    connection = op.get_bind()
    column_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'scans' 
        AND column_name = 'last_commit_sha'
    """)).scalar() > 0
    
    if not column_exists:
        print("Adding last_commit_sha column to scans...")
        op.add_column('scans', sa.Column('last_commit_sha', sa.String(40), nullable=True))
        print("last_commit_sha column added successfully.")
    else:
        print("last_commit_sha column already exists in scans, skipping...")

    # Check if baseline_type column exists in scans
    connection = op.get_bind()
    column_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'scans' 
        AND column_name = 'baseline_type'
    """)).scalar() > 0
    
    if not column_exists:
        print("Adding baseline_type column to scans...")
        op.add_column('scans', sa.Column('baseline_type', sa.String(20), nullable=True))
        print("baseline_type column added successfully.")
    else:
        print("baseline_type column already exists in scans, skipping...")

    
    # Add scan completion tracking columns
    # Check if total_files_discovered column exists in scans
    connection = op.get_bind()
    column_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'scans' 
        AND column_name = 'total_files_discovered'
    """)).scalar() > 0
    
    if not column_exists:
        print("Adding total_files_discovered column to scans...")
        op.add_column('scans', sa.Column('total_files_discovered', sa.Integer(), nullable=True, default=0))
        print("total_files_discovered column added successfully.")
    else:
        print("total_files_discovered column already exists in scans, skipping...")

    # Check if total_files_queued column exists in scans
    connection = op.get_bind()
    column_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'scans' 
        AND column_name = 'total_files_queued'
    """)).scalar() > 0
    
    if not column_exists:
        print("Adding total_files_queued column to scans...")
        op.add_column('scans', sa.Column('total_files_queued', sa.Integer(), nullable=True, default=0))
        print("total_files_queued column added successfully.")
    else:
        print("total_files_queued column already exists in scans, skipping...")

    # Check if total_files_completed column exists in scans
    connection = op.get_bind()
    column_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'scans' 
        AND column_name = 'total_files_completed'
    """)).scalar() > 0
    
    if not column_exists:
        print("Adding total_files_completed column to scans...")
        op.add_column('scans', sa.Column('total_files_completed', sa.Integer(), nullable=True, default=0))
        print("total_files_completed column added successfully.")
    else:
        print("total_files_completed column already exists in scans, skipping...")

    
    # Add indexes for efficient baseline queries
    # Create index if it doesn't exist
    try:
        op.create_index('idx_scans_url_status_finished', 'scans', ['url', 'status', 'finished_at'])
        print("Index idx_scans_url_status_finished created successfully.")
    except Exception:
        print("Index idx_scans_url_status_finished already exists, skipping...")

    # Create index if it doesn't exist
    try:
        op.create_index('idx_scans_last_commit_sha', 'scans', ['last_commit_sha'])
        print("Index idx_scans_last_commit_sha created successfully.")
    except Exception:
        print("Index idx_scans_last_commit_sha already exists, skipping...")

    # Create index if it doesn't exist
    try:
        op.create_index('idx_scans_working_commit_sha', 'scans', ['working_commit_sha'])
        print("Index idx_scans_working_commit_sha created successfully.")
    except Exception:
        print("Index idx_scans_working_commit_sha already exists, skipping...")



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