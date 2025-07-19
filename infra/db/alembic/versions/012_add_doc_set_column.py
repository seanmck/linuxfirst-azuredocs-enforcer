"""Add doc_set column to pages table for performance optimization

Revision ID: 012_add_doc_set_column
Revises: 011_force_add_proposed_change_id
Create Date: 2025-07-18 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = '012_add_doc_set_column'
down_revision = '011_force_add_proposed_change_id'
branch_labels = None
depends_on = None


def upgrade():
    """Add doc_set column to pages table and populate it"""
    
    # Add doc_set column
    op.add_column('pages', sa.Column('doc_set', sa.String(255), nullable=True))
    
    # Create index on doc_set for fast filtering
    op.create_index('idx_pages_doc_set', 'pages', ['doc_set'])
    
    # Create composite index on (doc_set, scan_id) for common query patterns
    op.create_index('idx_pages_doc_set_scan_id', 'pages', ['doc_set', 'scan_id'])
    
    # Populate the doc_set column with values computed from URLs
    # This SQL uses the same regex logic as the Python extract_doc_set_from_url function
    op.execute(text("""
        UPDATE pages SET doc_set = (
            CASE 
                -- GitHub azure-docs URLs: extract service from articles/{service}/
                WHEN url LIKE '%github.com%' AND url LIKE '%azure-docs%' AND url LIKE '%/articles/%' THEN
                    CASE 
                        WHEN url ~ 'azure-docs/blob/[^/]+/articles/([^/]+)' THEN
                            substring(url from 'azure-docs/blob/[^/]+/articles/([^/]+)')
                        ELSE 'azure-docs'
                    END
                -- Other GitHub URLs: extract repo name
                WHEN url LIKE '%github.com%' THEN
                    CASE 
                        WHEN url ~ 'github\.com/[^/]+/([^/]+)' THEN
                            substring(url from 'github\.com/[^/]+/([^/]+)')
                        ELSE NULL
                    END
                -- learn.microsoft.com URLs: extract service from /azure/{service}/
                WHEN url LIKE '%learn.microsoft.com%' AND url LIKE '%/azure/%' THEN
                    CASE 
                        WHEN url ~ 'learn\.microsoft\.com/[^/]+/azure/([^/]+)' THEN
                            substring(url from 'learn\.microsoft\.com/[^/]+/azure/([^/]+)')
                        ELSE NULL
                    END
                -- learn.microsoft.com URLs: extract product from /{product}/
                WHEN url LIKE '%learn.microsoft.com%' THEN
                    CASE 
                        WHEN url ~ 'learn\.microsoft\.com/[^/]+/([^/]+)' THEN
                            substring(url from 'learn\.microsoft\.com/[^/]+/([^/]+)')
                        ELSE NULL
                    END
                ELSE NULL
            END
        )
        WHERE doc_set IS NULL
    """))
    
    print("doc_set column populated successfully")


def downgrade():
    """Remove doc_set column and indexes"""
    op.drop_index('idx_pages_doc_set_scan_id', 'pages')
    op.drop_index('idx_pages_doc_set', 'pages')
    op.drop_column('pages', 'doc_set')