"""Standardize scan statuses

Revision ID: 008_standardize_scan_statuses
Revises: 007_add_file_processing_history
Create Date: 2025-07-11

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '008_standardize_scan_statuses'
down_revision = '007_add_file_processing_history'
branch_labels = None
depends_on = None


def upgrade():
    """
    Update existing scan statuses to use standardized values:
    - 'running' -> 'in_progress'
    - 'processing' -> 'in_progress' 
    - 'done' -> 'completed'
    """
    # Update running scans to in_progress
    op.execute("""
        UPDATE scans 
        SET status = 'in_progress' 
        WHERE status = 'running'
    """)
    
    # Update processing scans to in_progress
    op.execute("""
        UPDATE scans 
        SET status = 'in_progress' 
        WHERE status = 'processing'
    """)
    
    # Update done scans to completed
    op.execute("""
        UPDATE scans 
        SET status = 'completed' 
        WHERE status = 'done'
    """)


def downgrade():
    """
    Revert scan statuses to old values:
    - 'in_progress' -> 'running' (for older scans)
    - 'completed' -> 'done'
    
    Note: We can't perfectly distinguish between what was 'running' vs 'processing',
    so we'll default to 'running' for all 'in_progress' scans.
    """
    # Revert completed scans to done
    op.execute("""
        UPDATE scans 
        SET status = 'done' 
        WHERE status = 'completed'
    """)
    
    # Revert in_progress scans to running
    op.execute("""
        UPDATE scans 
        SET status = 'running' 
        WHERE status = 'in_progress'
    """)