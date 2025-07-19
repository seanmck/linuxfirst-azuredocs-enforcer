"""Force add proposed_change_id column

Revision ID: 011_force_add_proposed_change_id
Revises: 010_hotfix_proposed_change_id
Create Date: 2025-07-17

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '011_force_add_proposed_change_id'
down_revision = '010_hotfix_proposed_change_id'
branch_labels = None
depends_on = None


def upgrade():
    """
    Force add proposed_change_id column to snippets table.
    This migration will always run and use PostgreSQL's IF NOT EXISTS.
    """
    
    print("FORCE ADDING proposed_change_id column to snippets table...")
    
    # Use direct SQL with IF NOT EXISTS - this will work regardless of current state
    op.execute("ALTER TABLE snippets ADD COLUMN IF NOT EXISTS proposed_change_id VARCHAR(255);")
    
    # Create index if it doesn't exist
    op.execute("CREATE INDEX IF NOT EXISTS idx_snippets_proposed_change ON snippets(proposed_change_id);")
    
    print("FORCE ADD completed successfully - column should now exist.")


def downgrade():
    """
    Remove proposed_change_id column
    """
    op.execute("DROP INDEX IF EXISTS idx_snippets_proposed_change;")
    op.execute("ALTER TABLE snippets DROP COLUMN IF EXISTS proposed_change_id;")