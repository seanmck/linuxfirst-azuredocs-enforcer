"""Backfill doc_set column for all configured repositories

Revision ID: 015_backfill_doc_set_all_repos
Revises: 014_add_rewritten_documents
Create Date: 2025-12-13 00:00:00.000000

The original migration (012) only handled azure-docs URLs.
This migration backfills doc_set for all configured repos including:
- azure-docs-pr / azure-docs
- azure-management-docs-pr / azure-management-docs
- azure-compute-docs-pr / azure-compute-docs
"""
from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = '015_backfill_doc_set_all_repos'
down_revision = '014_add_rewritten_documents'
branch_labels = None
depends_on = None


def upgrade():
    """Backfill doc_set for pages from all configured repositories"""

    # Update pages where doc_set is NULL by extracting from URL
    # This handles all repo patterns: azure-docs, azure-management-docs, azure-compute-docs, etc.
    op.execute(text("""
        UPDATE pages SET doc_set = (
            CASE
                -- GitHub URLs with articles path: extract service from articles/{service}/
                WHEN url LIKE '%github.com%' AND url LIKE '%/articles/%' THEN
                    CASE
                        -- Match any repo with articles path pattern
                        WHEN url ~ '/blob/[^/]+/articles/([^/]+)' THEN
                            substring(url from '/blob/[^/]+/articles/([^/]+)')
                        ELSE NULL
                    END
                -- Other GitHub URLs: extract repo name as fallback
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

    print("doc_set column backfilled for all repositories")


def downgrade():
    """No downgrade needed - this is a data backfill"""
    pass
