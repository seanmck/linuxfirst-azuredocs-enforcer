"""Add pull request tracking

Revision ID: 015_add_pull_request_tracking
Revises: 014_add_rewritten_documents
Create Date: 2025-08-01 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '015_add_pull_request_tracking'
down_revision = '014_add_rewritten_documents'
branch_labels = None
depends_on = None


def upgrade():
    """Add pull_requests table for tracking PR lifecycle"""
    
    connection = op.get_bind()
    
    # Create pull_requests table
    print("Creating pull_requests table...")
    op.create_table('pull_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('page_id', sa.Integer(), nullable=True),
        sa.Column('rewritten_document_id', sa.Integer(), nullable=True),
        sa.Column('github_pr_number', sa.Integer(), nullable=False),
        sa.Column('github_pr_url', sa.Text(), nullable=False),
        sa.Column('repository', sa.String(length=255), nullable=False),
        sa.Column('branch_name', sa.String(length=255), nullable=False),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('status', sa.Enum('open', 'merged', 'closed', 'draft', name='pr_status'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('merged_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['page_id'], ['pages.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['rewritten_document_id'], ['rewritten_documents.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for performance
    op.create_index('ix_pull_requests_user_id', 'pull_requests', ['user_id'])
    op.create_index('ix_pull_requests_page_id', 'pull_requests', ['page_id'])
    op.create_index('ix_pull_requests_rewritten_document_id', 'pull_requests', ['rewritten_document_id'])
    op.create_index('ix_pull_requests_status', 'pull_requests', ['status'])
    op.create_index('ix_pull_requests_created_at', 'pull_requests', ['created_at'])
    op.create_index('ix_pull_requests_repository', 'pull_requests', ['repository'])
    op.create_index('ix_pull_requests_user_status', 'pull_requests', ['user_id', 'status'])
    
    # Create unique index for PR URL to prevent duplicates
    op.create_index('ix_pull_requests_github_pr_url', 'pull_requests', ['github_pr_url'], unique=True)
    
    print("pull_requests table created successfully")


def downgrade():
    """Remove pull request tracking"""
    
    connection = op.get_bind()
    
    # Drop pull_requests table
    pull_requests_exists = connection.execute(sa.text("""
        SELECT COUNT(*) 
        FROM information_schema.tables 
        WHERE table_name = 'pull_requests'
    """)).scalar() > 0
    
    if pull_requests_exists:
        print("Dropping pull_requests table...")
        
        # Drop indexes
        indexes = [
            'ix_pull_requests_github_pr_url',
            'ix_pull_requests_user_status',
            'ix_pull_requests_repository',
            'ix_pull_requests_created_at',
            'ix_pull_requests_status',
            'ix_pull_requests_rewritten_document_id',
            'ix_pull_requests_page_id',
            'ix_pull_requests_user_id'
        ]
        
        for index in indexes:
            try:
                op.drop_index(index, 'pull_requests')
            except:
                pass
        
        # Drop table
        op.drop_table('pull_requests')
        
        # Drop enum type
        op.execute("DROP TYPE IF EXISTS pr_status")
        
        print("pull_requests table dropped")