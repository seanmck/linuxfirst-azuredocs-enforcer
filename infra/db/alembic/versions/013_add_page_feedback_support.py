"""Add page-level feedback support to user_feedback table

Revision ID: 013_add_page_feedback_support
Revises: 012_add_doc_set_column
Create Date: 2025-07-18 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '013_add_page_feedback_support'
down_revision = '012_add_doc_set_column'
branch_labels = None
depends_on = None


def upgrade():
    """Add page_id column to user_feedback table and update constraints"""
    
    connection = op.get_bind()
    
    # Check if users table exists, if not create it
    users_table_exists = connection.execute(sa.text("""
        SELECT COUNT(*) 
        FROM information_schema.tables 
        WHERE table_name = 'users'
    """)).scalar() > 0
    
    if not users_table_exists:
        print("users table does not exist, creating it...")
        op.create_table('users',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('github_username', sa.String(length=255), nullable=False),
            sa.Column('github_id', sa.Integer(), nullable=False),
            sa.Column('email', sa.String(length=255), nullable=True),
            sa.Column('avatar_url', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column('last_login', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('github_username'),
            sa.UniqueConstraint('github_id')
        )
        op.create_index('idx_users_github_id', 'users', ['github_id'])
        print("users table created successfully")
    
    # Check if user_sessions table exists, if not create it
    sessions_table_exists = connection.execute(sa.text("""
        SELECT COUNT(*) 
        FROM information_schema.tables 
        WHERE table_name = 'user_sessions'
    """)).scalar() > 0
    
    if not sessions_table_exists:
        print("user_sessions table does not exist, creating it...")
        op.create_table('user_sessions',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('session_token', sa.String(length=255), nullable=False),
            sa.Column('github_access_token', sa.Text(), nullable=True),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('session_token')
        )
        op.create_index('idx_user_sessions_token', 'user_sessions', ['session_token'])
        op.create_index('idx_user_sessions_expires', 'user_sessions', ['expires_at'])
        print("user_sessions table created successfully")
    
    # Check if user_feedback table exists, if not create it
    feedback_table_exists = connection.execute(sa.text("""
        SELECT COUNT(*) 
        FROM information_schema.tables 
        WHERE table_name = 'user_feedback'
    """)).scalar() > 0
    
    if not feedback_table_exists:
        print("user_feedback table does not exist, creating it...")
        # Create the full table with both snippet_id and page_id support
        op.create_table('user_feedback',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('snippet_id', sa.Integer(), nullable=True),
            sa.Column('page_id', sa.Integer(), nullable=True),
            sa.Column('rating', sa.Boolean(), nullable=False),
            sa.Column('comment', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['snippet_id'], ['snippets.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['page_id'], ['pages.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.CheckConstraint("(snippet_id IS NOT NULL AND page_id IS NULL) OR (snippet_id IS NULL AND page_id IS NOT NULL)", name='check_feedback_target')
        )
        
        # Create indexes
        op.create_index('idx_user_feedback_user_snippet', 'user_feedback', ['user_id', 'snippet_id'])
        op.create_index('idx_user_feedback_user_page', 'user_feedback', ['user_id', 'page_id'])
        op.create_index('idx_user_feedback_page_id', 'user_feedback', ['page_id'])
        
        print("user_feedback table created successfully with page support")
        return
    
    # If table exists, add page_id column
    print("user_feedback table exists, adding page_id column...")
    op.add_column('user_feedback', sa.Column('page_id', sa.Integer(), nullable=True))
    
    # Add foreign key constraint to pages table
    op.create_foreign_key('fk_user_feedback_page', 'user_feedback', 'pages', ['page_id'], ['id'], ondelete='CASCADE')
    
    # Make snippet_id nullable (was already nullable in the model but may not be in DB)
    op.alter_column('user_feedback', 'snippet_id', nullable=True)
    
    # Drop existing constraints that might conflict
    try:
        op.drop_constraint('check_feedback_target', 'user_feedback', type_='check')
    except:
        pass  # Constraint may not exist
    
    try:
        op.drop_constraint('check_rating_value', 'user_feedback', type_='check')
    except:
        pass  # Constraint may not exist
    
    # Add check constraint to ensure either snippet_id or page_id is provided (but not both)
    op.create_check_constraint(
        'check_feedback_target',
        'user_feedback',
        '(snippet_id IS NOT NULL AND page_id IS NULL) OR (snippet_id IS NULL AND page_id IS NOT NULL)'
    )
    
    # Note: No rating constraint needed for boolean type
    
    # Create indexes for better performance
    op.create_index('idx_user_feedback_page_id', 'user_feedback', ['page_id'])
    op.create_index('idx_user_feedback_user_page', 'user_feedback', ['user_id', 'page_id'])
    
    # Create index on user_id + snippet_id if it doesn't exist
    try:
        op.create_index('idx_user_feedback_user_snippet', 'user_feedback', ['user_id', 'snippet_id'])
    except:
        pass  # Index may already exist
    
    print("Page feedback support added successfully")


def downgrade():
    """Remove page_id column and revert constraints"""
    
    connection = op.get_bind()
    
    # Check if we need to drop the entire user_feedback table or just the page_id column
    feedback_table_exists = connection.execute(sa.text("""
        SELECT COUNT(*) 
        FROM information_schema.tables 
        WHERE table_name = 'user_feedback'
    """)).scalar() > 0
    
    if feedback_table_exists:
        # Check if page_id column exists
        page_id_exists = connection.execute(sa.text("""
            SELECT COUNT(*) 
            FROM information_schema.columns 
            WHERE table_name = 'user_feedback' 
            AND column_name = 'page_id'
        """)).scalar() > 0
        
        if page_id_exists:
            # Drop indexes
            try:
                op.drop_index('idx_user_feedback_user_page', 'user_feedback')
            except:
                pass
            try:
                op.drop_index('idx_user_feedback_page_id', 'user_feedback')
            except:
                pass
            
            # Drop constraints
            try:
                op.drop_constraint('check_feedback_target', 'user_feedback', type_='check')
            except:
                pass
            try:
                op.drop_constraint('check_rating_value', 'user_feedback', type_='check')
            except:
                pass
            
            # Drop foreign key
            try:
                op.drop_constraint('fk_user_feedback_page', 'user_feedback', type_='foreignkey')
            except:
                pass
            
            # Remove page_id column
            op.drop_column('user_feedback', 'page_id')
            
            # Make snippet_id non-nullable again
            op.alter_column('user_feedback', 'snippet_id', nullable=False)
            
            # Note: No rating constraint needed for boolean type
            
            print("Page feedback support removed successfully")
        else:
            # If this migration created the entire table, drop it all
            try:
                op.drop_table('user_feedback')
                print("user_feedback table dropped")
            except:
                pass
            
            try:
                op.drop_table('user_sessions')
                print("user_sessions table dropped")
            except:
                pass
            
            try:
                op.drop_table('users')
                print("users table dropped")
            except:
                pass