"""Hotfix: Add proposed_change_id column if missing

Revision ID: 010_hotfix_proposed_change_id
Revises: 009_add_user_tables
Create Date: 2025-07-17

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = '010_hotfix_proposed_change_id'
down_revision = '009_add_user_tables'
branch_labels = None
depends_on = None


def upgrade():
    """
    Add proposed_change_id column to snippets table if it doesn't exist.
    This is a hotfix for cases where migration 009 didn't apply cleanly.
    Uses PostgreSQL's IF NOT EXISTS to avoid transaction state issues.
    """
    
    print("Adding proposed_change_id column to snippets table (if not exists)...")
    
    # Use direct SQL with IF NOT EXISTS - more reliable than querying information_schema
    op.execute("ALTER TABLE snippets ADD COLUMN IF NOT EXISTS proposed_change_id VARCHAR(255);")
    
    # Create index if it doesn't exist
    op.execute("CREATE INDEX IF NOT EXISTS idx_snippets_proposed_change ON snippets(proposed_change_id);")
    
    print("Column and index creation completed successfully.")


def downgrade():
    """
    Remove proposed_change_id column if it exists
    """
    
    # Check if the column exists before trying to drop it
    connection = op.get_bind()
    result = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'snippets' 
        AND column_name = 'proposed_change_id'
    """))
    
    column_exists = result.scalar() > 0
    
    if column_exists:
        print("Removing proposed_change_id column from snippets table...")
        op.drop_index('idx_snippets_proposed_change', table_name='snippets')
        op.drop_column('snippets', 'proposed_change_id')
        print("Column removed successfully.")
    else:
        print("proposed_change_id column doesn't exist, skipping...")