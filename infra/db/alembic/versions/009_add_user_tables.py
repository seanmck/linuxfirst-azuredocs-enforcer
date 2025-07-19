"""Add user and feedback tables for GitHub OAuth

Revision ID: 009_add_user_tables
Revises: 008_standardize_scan_statuses
Create Date: 2025-07-16

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = '009_add_user_tables'
down_revision = '008_standardize_scan_statuses'
branch_labels = None
depends_on = None


def upgrade():
    """
    Create tables for user authentication and feedback tracking:
    - users: Store GitHub user information
    - user_sessions: Temporary session storage with encrypted tokens
    - user_feedback: Track user feedback on LLM recommendations
    """
    
    # Create users table
    # Check if users table exists
    connection = op.get_bind()
    table_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.tables 
        WHERE table_name = 'users'
    """)).scalar() > 0
    
    if not table_exists:
        print("Creating users table...")
        op.create_table('users',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('github_username', sa.String(length=255), nullable=False),
            sa.Column('github_id', sa.Integer(), nullable=False),
            sa.Column('email', sa.String(length=255), nullable=True),
            sa.Column('avatar_url', sa.Text(), nullable=True),
            sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('now()'), nullable=False),
            sa.Column('last_login', sa.TIMESTAMP(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('github_username'),
            sa.UniqueConstraint('github_id')
        )
        print("users table added successfully.")
    else:
        print("users table already exists, skipping...")

    
    # Create index on github_id for fast lookups during OAuth
    # Create index if it doesn't exist
    try:
        op.create_index('idx_users_github_id', 'users', ['github_id'])
        print("Index idx_users_github_id created successfully.")
    except Exception:
        print("Index idx_users_github_id already exists, skipping...")

    
    # Create user_sessions table
    # Check if user_sessions table exists
    connection = op.get_bind()
    table_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.tables 
        WHERE table_name = 'user_sessions'
    """)).scalar() > 0
    
    if not table_exists:
        print("Creating user_sessions table...")
        op.create_table('user_sessions',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('session_token', sa.String(length=255), nullable=False),
            sa.Column('github_access_token', sa.Text(), nullable=True),  # Will be encrypted
            sa.Column('expires_at', sa.TIMESTAMP(), nullable=False),
            sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('session_token')
        )
        print("user_sessions table added successfully.")
    else:
        print("user_sessions table already exists, skipping...")

    
    # Create indexes for session lookups and cleanup
    # Create index if it doesn't exist
    try:
        op.create_index('idx_user_sessions_token', 'user_sessions', ['session_token'])
        print("Index idx_user_sessions_token created successfully.")
    except Exception:
        print("Index idx_user_sessions_token already exists, skipping...")

    # Create index if it doesn't exist
    try:
        op.create_index('idx_user_sessions_expires', 'user_sessions', ['expires_at'])
        print("Index idx_user_sessions_expires created successfully.")
    except Exception:
        print("Index idx_user_sessions_expires already exists, skipping...")

    
    # Create user_feedback table
    # Check if user_feedback table exists
    connection = op.get_bind()
    table_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.tables 
        WHERE table_name = 'user_feedback'
    """)).scalar() > 0
    
    if not table_exists:
        print("Creating user_feedback table...")
        op.create_table('user_feedback',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('snippet_id', sa.Integer(), nullable=False),
            sa.Column('rating', sa.String(length=10), nullable=False),  # 'thumbs_up' or 'thumbs_down'
            sa.Column('comment', sa.Text(), nullable=True),
            sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('now()'), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['snippet_id'], ['snippets.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.CheckConstraint("rating IN ('thumbs_up', 'thumbs_down')", name='check_rating_value')
        )
        print("user_feedback table added successfully.")
    else:
        print("user_feedback table already exists, skipping...")

    
    # Create composite index for checking if user already provided feedback
    # Create index if it doesn't exist
    try:
        op.create_index('idx_user_feedback_user_snippet', 'user_feedback', ['user_id', 'snippet_id'])
        print("Index idx_user_feedback_user_snippet created successfully.")
    except Exception:
        print("Index idx_user_feedback_user_snippet already exists, skipping...")

    
    # Add proposed_change_id column to snippets table to link feedback to specific proposed changes
    # Check if proposed_change_id column exists in snippets
    connection = op.get_bind()
    column_exists = connection.execute(text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'snippets' 
        AND column_name = 'proposed_change_id'
    """)).scalar() > 0
    
    if not column_exists:
        print("Adding proposed_change_id column to snippets...")
        op.add_column('snippets', sa.Column('proposed_change_id', sa.String(length=255), nullable=True))
        print("proposed_change_id column added successfully.")
    else:
        print("proposed_change_id column already exists in snippets, skipping...")

    # Create index if it doesn't exist
    try:
        op.create_index('idx_snippets_proposed_change', 'snippets', ['proposed_change_id'])
        print("Index idx_snippets_proposed_change created successfully.")
    except Exception:
        print("Index idx_snippets_proposed_change already exists, skipping...")



def downgrade():
    """
    Remove user-related tables and columns
    """
    # Remove proposed_change_id from snippets
    op.drop_index('idx_snippets_proposed_change', table_name='snippets')
    op.drop_column('snippets', 'proposed_change_id')
    
    # Drop user_feedback table and indexes
    op.drop_index('idx_user_feedback_user_snippet', table_name='user_feedback')
    op.drop_table('user_feedback')
    
    # Drop user_sessions table and indexes
    op.drop_index('idx_user_sessions_expires', table_name='user_sessions')
    op.drop_index('idx_user_sessions_token', table_name='user_sessions')
    op.drop_table('user_sessions')
    
    # Drop users table and indexes
    op.drop_index('idx_users_github_id', table_name='users')
    op.drop_table('users')