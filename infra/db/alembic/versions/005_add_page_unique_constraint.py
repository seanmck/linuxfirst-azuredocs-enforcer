"""Add unique constraint on pages scan_id and url

Revision ID: 005
Revises: 004
Create Date: 2025-01-09

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '005_add_page_unique_constraint'
down_revision = '004_add_bias_snapshots'
branch_labels = None
depends_on = None


def upgrade():
    # First, clean up any existing duplicates
    # Keep the first occurrence (lowest id) of each duplicate
    op.execute("""
        DELETE FROM pages p1
        WHERE EXISTS (
            SELECT 1 FROM pages p2
            WHERE p2.scan_id = p1.scan_id
            AND p2.url = p1.url
            AND p2.id < p1.id
        )
    """)
    
    # Add unique constraint on scan_id and url
    op.create_unique_constraint(
        'uq_pages_scan_id_url', 
        'pages', 
        ['scan_id', 'url']
    )


def downgrade():
    # Drop the unique constraint
    op.drop_constraint('uq_pages_scan_id_url', 'pages', type_='unique')