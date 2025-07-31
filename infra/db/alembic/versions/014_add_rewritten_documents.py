"""Add rewritten documents support with versioning

Revision ID: 014_add_rewritten_documents
Revises: 013_add_page_feedback_support
Create Date: 2025-01-22 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '014_add_rewritten_documents'
down_revision = '013_add_page_feedback_support'
branch_labels = None
depends_on = None


def upgrade():
    """Add rewritten_documents table and update user_feedback to support document versioning"""
    
    connection = op.get_bind()
    
    # Create rewritten_documents table
    print("Creating rewritten_documents table...")
    op.create_table('rewritten_documents',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('page_id', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('content_hash', sa.String(length=64), nullable=False),
        sa.Column('yaml_header', sa.JSON(), nullable=True),
        sa.Column('generation_params', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['page_id'], ['pages.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes for performance
    op.create_index('ix_rewritten_documents_content_hash', 'rewritten_documents', ['content_hash'])
    op.create_index('ix_rewritten_documents_page_id', 'rewritten_documents', ['page_id'])
    op.create_index('ix_rewritten_documents_created_at', 'rewritten_documents', ['created_at'])
    print("rewritten_documents table created successfully")
    
    # Add rewritten_document_id column to user_feedback table
    print("Adding rewritten_document_id to user_feedback table...")
    op.add_column('user_feedback', sa.Column('rewritten_document_id', sa.Integer(), nullable=True))
    
    # Add foreign key constraint
    op.create_foreign_key(
        'fk_user_feedback_rewritten_document', 
        'user_feedback', 
        'rewritten_documents', 
        ['rewritten_document_id'], 
        ['id'], 
        ondelete='CASCADE'
    )
    
    # Drop existing check constraint
    try:
        op.drop_constraint('check_feedback_target', 'user_feedback', type_='check')
        print("Dropped existing check constraint")
    except:
        print("No existing check constraint to drop")
    
    # Add updated check constraint to support three feedback target types
    op.create_check_constraint(
        'check_feedback_target',
        'user_feedback',
        '(snippet_id IS NOT NULL AND page_id IS NULL AND rewritten_document_id IS NULL) OR ' +
        '(snippet_id IS NULL AND page_id IS NOT NULL AND rewritten_document_id IS NULL) OR ' +
        '(snippet_id IS NULL AND page_id IS NULL AND rewritten_document_id IS NOT NULL)'
    )
    
    # Create index for performance
    op.create_index('ix_user_feedback_rewritten_document', 'user_feedback', ['rewritten_document_id'])
    op.create_index('ix_user_feedback_user_rewritten_document', 'user_feedback', ['user_id', 'rewritten_document_id'])
    
    print("Rewritten documents support added successfully")


def downgrade():
    """Remove rewritten documents support"""
    
    connection = op.get_bind()
    
    # Check if rewritten_document_id column exists in user_feedback
    rewritten_col_exists = connection.execute(sa.text("""
        SELECT COUNT(*) 
        FROM information_schema.columns 
        WHERE table_name = 'user_feedback' 
        AND column_name = 'rewritten_document_id'
    """)).scalar() > 0
    
    if rewritten_col_exists:
        print("Removing rewritten document support from user_feedback...")
        
        # Drop indexes
        try:
            op.drop_index('ix_user_feedback_user_rewritten_document', 'user_feedback')
        except:
            pass
        try:
            op.drop_index('ix_user_feedback_rewritten_document', 'user_feedback')
        except:
            pass
        
        # Drop check constraint
        try:
            op.drop_constraint('check_feedback_target', 'user_feedback', type_='check')
        except:
            pass
        
        # Drop foreign key constraint
        try:
            op.drop_constraint('fk_user_feedback_rewritten_document', 'user_feedback', type_='foreignkey')
        except:
            pass
        
        # Remove rewritten_document_id column
        op.drop_column('user_feedback', 'rewritten_document_id')
        
        # Restore original check constraint
        op.create_check_constraint(
            'check_feedback_target',
            'user_feedback',
            '(snippet_id IS NOT NULL AND page_id IS NULL) OR (snippet_id IS NULL AND page_id IS NOT NULL)'
        )
        
        print("Removed rewritten document support from user_feedback")
    
    # Drop rewritten_documents table
    rewritten_table_exists = connection.execute(sa.text("""
        SELECT COUNT(*) 
        FROM information_schema.tables 
        WHERE table_name = 'rewritten_documents'
    """)).scalar() > 0
    
    if rewritten_table_exists:
        print("Dropping rewritten_documents table...")
        op.drop_table('rewritten_documents')
        print("rewritten_documents table dropped")