"""Add bias snapshots tables

Revision ID: 004
Revises: 003
Create Date: 2025-01-08

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '004_add_bias_snapshots'
down_revision = '003_retry_mechanism'
branch_labels = None
depends_on = None


def upgrade():
    # Create bias_snapshots table for overall daily bias tracking
    op.create_table('bias_snapshots',
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('total_pages', sa.Integer(), nullable=False),
        sa.Column('biased_pages', sa.Integer(), nullable=False),
        sa.Column('bias_percentage', sa.Float(), nullable=False),
        sa.Column('last_calculated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('additional_data', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint('date')
    )
    
    # Create index for efficient date range queries
    op.create_index('idx_bias_snapshots_date', 'bias_snapshots', ['date'])
    
    # Create bias_snapshots_by_docset table for per-docset tracking
    op.create_table('bias_snapshots_by_docset',
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('doc_set', sa.String(), nullable=False),
        sa.Column('total_pages', sa.Integer(), nullable=False),
        sa.Column('biased_pages', sa.Integer(), nullable=False),
        sa.Column('bias_percentage', sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint('date', 'doc_set')
    )
    
    # Create composite index for efficient queries
    op.create_index('idx_bias_snapshots_by_docset_date_docset', 'bias_snapshots_by_docset', ['date', 'doc_set'])
    op.create_index('idx_bias_snapshots_by_docset_docset', 'bias_snapshots_by_docset', ['doc_set'])


def downgrade():
    # Drop indexes
    op.drop_index('idx_bias_snapshots_by_docset_docset', table_name='bias_snapshots_by_docset')
    op.drop_index('idx_bias_snapshots_by_docset_date_docset', table_name='bias_snapshots_by_docset')
    op.drop_index('idx_bias_snapshots_date', table_name='bias_snapshots')
    
    # Drop tables
    op.drop_table('bias_snapshots_by_docset')
    op.drop_table('bias_snapshots')