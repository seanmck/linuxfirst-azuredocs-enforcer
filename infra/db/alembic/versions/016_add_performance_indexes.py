"""Add performance indexes for common query patterns

Revision ID: 016_add_performance_indexes
Revises: 015_backfill_doc_set_all_repos
Create Date: 2025-01-09 12:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = '016_add_performance_indexes'
down_revision = '015_backfill_doc_set_all_repos'
branch_labels = None
depends_on = None


def upgrade():
    """Add indexes for frequently queried columns to improve query performance"""

    # Page indexes for common query patterns
    # Used in: docpage.py get_page_scan_history, docset.py queries
    print("Creating index idx_pages_scan_id on pages(scan_id)...")
    op.execute("CREATE INDEX IF NOT EXISTS idx_pages_scan_id ON pages (scan_id)")

    print("Creating index idx_pages_url on pages(url)...")
    op.execute("CREATE INDEX IF NOT EXISTS idx_pages_url ON pages (url)")

    # Composite index for the common (scan_id, url) lookup pattern
    print("Creating composite index idx_pages_scan_url on pages(scan_id, url)...")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_pages_scan_url "
        "ON pages (scan_id, url)"
    )

    # Snippet indexes
    # Used in: loading snippets for a page
    print("Creating index idx_snippets_page_id on snippets(page_id)...")
    op.execute("CREATE INDEX IF NOT EXISTS idx_snippets_page_id ON snippets (page_id)")

    # UserFeedback indexes for aggregation queries
    # Used in: feedback.py stats calculations
    print("Creating index idx_user_feedback_rating on user_feedback(rating)...")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_feedback_rating "
        "ON user_feedback (rating)"
    )

    print("Creating index idx_user_feedback_snippet_id on user_feedback(snippet_id)...")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_feedback_snippet_id "
        "ON user_feedback (snippet_id)"
    )

    print("Creating index idx_user_feedback_page_id on user_feedback(page_id)...")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_feedback_page_id "
        "ON user_feedback (page_id)"
    )

    print("Performance indexes created successfully")


def downgrade():
    """Remove performance indexes"""
    op.drop_index('idx_user_feedback_page_id', 'user_feedback')
    op.drop_index('idx_user_feedback_snippet_id', 'user_feedback')
    op.drop_index('idx_user_feedback_rating', 'user_feedback')
    op.drop_index('idx_snippets_page_id', 'snippets')
    op.drop_index('idx_pages_scan_url', 'pages')
    op.drop_index('idx_pages_url', 'pages')
    op.drop_index('idx_pages_scan_id', 'pages')
