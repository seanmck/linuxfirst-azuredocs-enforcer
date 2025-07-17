"""Add bias snapshots tables

Revision ID: 004
Revises: 003
Create Date: 2025-01-08

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '004_add_bias_snapshots'
down_revision = '003_retry_mechanism'
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    
    # Create bias_snapshots table for overall daily bias tracking
    try:
        print("Creating bias_snapshots table...")
        op.create_table('bias_snapshots',
            sa.Column('date', sa.Date(), nullable=False),
            sa.Column('total_pages', sa.Integer(), nullable=False),
            sa.Column('biased_pages', sa.Integer(), nullable=False),
            sa.Column('bias_percentage', sa.Float(), nullable=False),
            sa.Column('last_calculated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('additional_data', postgresql.JSON(astext_type=sa.Text()), nullable=True),
            sa.PrimaryKeyConstraint('date')
        )
        print("bias_snapshots table created successfully.")
    except Exception as e:
        if "already exists" in str(e):
            print("bias_snapshots table already exists, skipping...")
        else:
            # If transaction is aborted, we need to rollback and continue
            try:
                connection.rollback()
                print("Transaction rolled back, continuing...")
            except:
                pass
            raise

    
    # Create index for efficient date range queries
    try:
        op.create_index('idx_bias_snapshots_date', 'bias_snapshots', ['date'])
        print("Index idx_bias_snapshots_date created successfully.")
    except Exception as e:
        if "already exists" in str(e):
            print("Index idx_bias_snapshots_date already exists, skipping...")
        elif "transaction is aborted" in str(e):
            print("Transaction aborted, rolling back...")
            try:
                connection.rollback()
            except:
                pass
        else:
            print(f"Warning: Could not create index idx_bias_snapshots_date: {e}")

    
    # Create bias_snapshots_by_docset table for per-docset tracking
    try:
        print("Creating bias_snapshots_by_docset table...")
        op.create_table('bias_snapshots_by_docset',
            sa.Column('date', sa.Date(), nullable=False),
            sa.Column('doc_set', sa.String(), nullable=False),
            sa.Column('total_pages', sa.Integer(), nullable=False),
            sa.Column('biased_pages', sa.Integer(), nullable=False),
            sa.Column('bias_percentage', sa.Float(), nullable=False),
            sa.PrimaryKeyConstraint('date', 'doc_set')
        )
        print("bias_snapshots_by_docset table created successfully.")
    except Exception as e:
        if "already exists" in str(e):
            print("bias_snapshots_by_docset table already exists, skipping...")
        elif "transaction is aborted" in str(e):
            print("Transaction aborted, rolling back...")
            try:
                connection.rollback()
            except:
                pass
        else:
            raise

    
    # Create composite index for efficient queries
    try:
        op.create_index('idx_bias_snapshots_by_docset_date_docset', 'bias_snapshots_by_docset', ['date', 'doc_set'])
        print("Index idx_bias_snapshots_by_docset_date_docset created successfully.")
    except Exception as e:
        if "already exists" in str(e):
            print("Index idx_bias_snapshots_by_docset_date_docset already exists, skipping...")
        elif "transaction is aborted" in str(e):
            print("Transaction aborted for index creation, continuing...")
        else:
            print(f"Warning: Could not create index idx_bias_snapshots_by_docset_date_docset: {e}")

    try:
        op.create_index('idx_bias_snapshots_by_docset_docset', 'bias_snapshots_by_docset', ['doc_set'])
        print("Index idx_bias_snapshots_by_docset_docset created successfully.")
    except Exception as e:
        if "already exists" in str(e):
            print("Index idx_bias_snapshots_by_docset_docset already exists, skipping...")
        elif "transaction is aborted" in str(e):
            print("Transaction aborted for index creation, continuing...")
        else:
            print(f"Warning: Could not create index idx_bias_snapshots_by_docset_docset: {e}")



def downgrade():
    # Drop indexes
    op.drop_index('idx_bias_snapshots_by_docset_docset', table_name='bias_snapshots_by_docset')
    op.drop_index('idx_bias_snapshots_by_docset_date_docset', table_name='bias_snapshots_by_docset')
    op.drop_index('idx_bias_snapshots_date', table_name='bias_snapshots')
    
    # Drop tables
    op.drop_table('bias_snapshots_by_docset')
    op.drop_table('bias_snapshots')