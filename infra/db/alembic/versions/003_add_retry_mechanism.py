"""Add retry mechanism fields to Page model

Revision ID: 003_retry_mechanism
Revises: 002_url_processing
Create Date: 2025-07-08 07:15:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '003_retry_mechanism'
down_revision = '002_url_processing'
branch_labels = None
depends_on = None


def upgrade():
    """Add retry mechanism fields to pages table"""
    
    # Add retry_count column as nullable first to avoid table rewrite
    op.add_column('pages', sa.Column('retry_count', sa.Integer(), nullable=True))
    
    # Add last_error_at column for tracking when last error occurred
    op.add_column('pages', sa.Column('last_error_at', sa.DateTime(), nullable=True))
    
    # Set default value for existing rows in batches to avoid locks
    op.execute("UPDATE pages SET retry_count = 0 WHERE retry_count IS NULL")
    
    # Now add the NOT NULL constraint and default separately (PostgreSQL 11+ optimization)
    op.execute("ALTER TABLE pages ALTER COLUMN retry_count SET DEFAULT 0")
    op.execute("ALTER TABLE pages ALTER COLUMN retry_count SET NOT NULL")
    
    # Add index for efficient queries on retry_count
    op.create_index('ix_pages_retry_count', 'pages', ['retry_count'])


def downgrade():
    """Remove retry mechanism fields"""
    
    # Remove index
    op.drop_index('ix_pages_retry_count', table_name='pages')
    
    # Remove columns
    op.drop_column('pages', 'last_error_at')
    op.drop_column('pages', 'retry_count')