"""Add retry mechanism fields to Page model

Revision ID: 003_retry_mechanism
Revises: 002_url_processing
Create Date: 2025-07-08 07:15:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = '003_retry_mechanism'
down_revision = '002_url_processing'
branch_labels = None
depends_on = None


def upgrade():
    """Add retry mechanism fields to pages table"""
    
    connection = op.get_bind()
    
    # Check if retry_count column exists
    retry_count_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'pages' 
        AND column_name = 'retry_count'
    """)).scalar() > 0
    
    # Check if last_error_at column exists
    last_error_at_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'pages' 
        AND column_name = 'last_error_at'
    """)).scalar() > 0
    
    # Add retry_count column if it doesn't exist
    if not retry_count_exists:
        print("Adding retry_count column...")
        op.add_column('pages', sa.Column('retry_count', sa.Integer(), nullable=True))
        
        # Set default value for existing rows in batches to avoid locks
        op.execute("UPDATE pages SET retry_count = 0 WHERE retry_count IS NULL")
        
        # Now add the NOT NULL constraint and default separately (PostgreSQL 11+ optimization)
        op.execute("ALTER TABLE pages ALTER COLUMN retry_count SET DEFAULT 0")
        op.execute("ALTER TABLE pages ALTER COLUMN retry_count SET NOT NULL")
        
        # Add index for efficient queries on retry_count
        op.create_index('ix_pages_retry_count', 'pages', ['retry_count'])
        print("retry_count column added successfully.")
    else:
        print("retry_count column already exists, skipping...")
    
    # Add last_error_at column if it doesn't exist
    if not last_error_at_exists:
        print("Adding last_error_at column...")
        op.add_column('pages', sa.Column('last_error_at', sa.DateTime(), nullable=True))
        print("last_error_at column added successfully.")
    else:
        print("last_error_at column already exists, skipping...")


def downgrade():
    """Remove retry mechanism fields"""
    
    connection = op.get_bind()
    
    # Check if retry_count column exists before dropping
    retry_count_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'pages' 
        AND column_name = 'retry_count'
    """)).scalar() > 0
    
    # Check if last_error_at column exists before dropping
    last_error_at_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'pages' 
        AND column_name = 'last_error_at'
    """)).scalar() > 0
    
    if retry_count_exists:
        # Remove index if it exists
        try:
            op.drop_index('ix_pages_retry_count', table_name='pages')
        except:
            pass  # Index might not exist
        
        # Remove retry_count column
        op.drop_column('pages', 'retry_count')
    
    if last_error_at_exists:
        # Remove last_error_at column
        op.drop_column('pages', 'last_error_at')