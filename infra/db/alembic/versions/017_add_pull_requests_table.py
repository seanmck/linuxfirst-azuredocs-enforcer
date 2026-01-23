"""Add pull_requests table for tracking PR contributions

Revision ID: 017_add_pull_requests_table
Revises: 016_add_performance_indexes
Create Date: 2025-01-20 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '017_add_pull_requests_table'
down_revision = '016_add_performance_indexes'
branch_labels = None
depends_on = None


def upgrade():
    """Create pull_requests table for tracking PR contributions"""

    print("Creating pull_requests table...")
    op.create_table('pull_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        # PR identification
        sa.Column('compare_url', sa.String(length=500), nullable=False),
        sa.Column('pr_url', sa.String(length=500), nullable=True),
        sa.Column('pr_number', sa.Integer(), nullable=True),
        # Repository information
        sa.Column('source_repo', sa.String(length=255), nullable=False),
        sa.Column('target_branch', sa.String(length=100), nullable=False, server_default='main'),
        sa.Column('head_branch', sa.String(length=255), nullable=False),
        sa.Column('fork_repo', sa.String(length=255), nullable=True),
        # Document information
        sa.Column('file_path', sa.String(length=500), nullable=False),
        sa.Column('doc_set', sa.String(length=255), nullable=True),
        sa.Column('page_id', sa.Integer(), nullable=True),
        sa.Column('rewritten_document_id', sa.Integer(), nullable=True),
        # User information
        sa.Column('user_id', sa.Integer(), nullable=True),
        # Status tracking
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        # Timestamps
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('submitted_at', sa.DateTime(), nullable=True),
        sa.Column('closed_at', sa.DateTime(), nullable=True),
        sa.Column('merged_at', sa.DateTime(), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        # PR metadata
        sa.Column('pr_title', sa.String(length=500), nullable=True),
        sa.Column('pr_state', sa.String(length=20), nullable=True),
        # Primary key and foreign keys
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['page_id'], ['pages.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['rewritten_document_id'], ['rewritten_documents.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    )

    # Create indexes for common query patterns
    print("Creating indexes for pull_requests table...")
    op.create_index('ix_pull_requests_user_id', 'pull_requests', ['user_id'])
    op.create_index('ix_pull_requests_status', 'pull_requests', ['status'])
    op.create_index('ix_pull_requests_doc_set', 'pull_requests', ['doc_set'])
    op.create_index('ix_pull_requests_created_at', 'pull_requests', ['created_at'])
    op.create_index('ix_pull_requests_source_repo', 'pull_requests', ['source_repo'])

    # Unique constraint on compare_url to prevent duplicates
    op.create_unique_constraint('uq_pull_requests_compare_url', 'pull_requests', ['compare_url'])

    print("pull_requests table created successfully")


def downgrade():
    """Drop pull_requests table"""

    connection = op.get_bind()

    # Check if table exists before dropping
    table_exists = connection.execute(sa.text("""
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_name = 'pull_requests'
    """)).scalar() > 0

    if table_exists:
        print("Dropping pull_requests table...")

        # Drop indexes first; ignore failures but log them for visibility
        try:
            op.drop_index('ix_pull_requests_source_repo', 'pull_requests')
        except Exception as exc:
            print("Warning: failed to drop index ix_pull_requests_source_repo on pull_requests:", exc)
        try:
            op.drop_index('ix_pull_requests_created_at', 'pull_requests')
        except Exception as exc:
            print("Warning: failed to drop index ix_pull_requests_created_at on pull_requests:", exc)
        try:
            op.drop_index('ix_pull_requests_doc_set', 'pull_requests')
        except Exception as exc:
            print("Warning: failed to drop index ix_pull_requests_doc_set on pull_requests:", exc)
        try:
            op.drop_index('ix_pull_requests_status', 'pull_requests')
        except Exception as exc:
            print("Warning: failed to drop index ix_pull_requests_status on pull_requests:", exc)
        try:
            op.drop_index('ix_pull_requests_user_id', 'pull_requests')
        except Exception as exc:
            print("Warning: failed to drop index ix_pull_requests_user_id on pull_requests:", exc)
        try:
            op.drop_constraint('uq_pull_requests_compare_url', 'pull_requests', type_='unique')
        except Exception as exc:
            print("Warning: failed to drop unique constraint uq_pull_requests_compare_url on pull_requests:", exc)

        # Drop the table
        op.drop_table('pull_requests')
        print("pull_requests table dropped")
