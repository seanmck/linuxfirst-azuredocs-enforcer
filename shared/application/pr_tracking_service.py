"""Service for tracking pull requests throughout their lifecycle."""

import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc

from shared.models import PullRequest, PRStatus, User, Page, RewrittenDocument
from shared.infrastructure.github_service import GitHubService
from shared.utils.database import SessionLocal
from shared.utils.error_handling import handle_errors

logger = logging.getLogger(__name__)


class PRTrackingService:
    """Service for managing pull request tracking."""
    
    def __init__(self, github_service: Optional[GitHubService] = None):
        """Initialize PR tracking service."""
        self.github_service = github_service or GitHubService()
    
    @handle_errors
    def create_pr_record(
        self,
        user_id: int,
        pr_url: str,
        pr_number: int,
        repository: str,
        branch_name: str,
        title: str,
        page_id: Optional[int] = None,
        rewritten_document_id: Optional[int] = None,
        db: Optional[Session] = None
    ) -> Optional[PullRequest]:
        """Create a new PR tracking record."""
        close_session = False
        if not db:
            db = SessionLocal()
            close_session = True
        
        try:
            # Check if PR already exists
            existing_pr = db.query(PullRequest).filter_by(github_pr_url=pr_url).first()
            if existing_pr:
                logger.warning(f"PR already exists: {pr_url}")
                return existing_pr
            
            # Create new PR record
            pr = PullRequest(
                user_id=user_id,
                page_id=page_id,
                rewritten_document_id=rewritten_document_id,
                github_pr_number=pr_number,
                github_pr_url=pr_url,
                repository=repository,
                branch_name=branch_name,
                title=title,
                status=PRStatus.OPEN
            )
            
            db.add(pr)
            db.commit()
            db.refresh(pr)
            
            logger.info(f"Created PR record: {pr_url}")
            return pr
            
        except Exception as e:
            logger.error(f"Error creating PR record: {e}")
            db.rollback()
            raise
        finally:
            if close_session:
                db.close()
    
    @handle_errors
    def update_pr_status(
        self,
        pr_id: int,
        status: PRStatus,
        merged_at: Optional[datetime] = None,
        db: Optional[Session] = None
    ) -> Optional[PullRequest]:
        """Update PR status."""
        close_session = False
        if not db:
            db = SessionLocal()
            close_session = True
        
        try:
            pr = db.query(PullRequest).filter_by(id=pr_id).first()
            if not pr:
                logger.warning(f"PR not found: {pr_id}")
                return None
            
            pr.status = status
            pr.updated_at = datetime.utcnow()
            
            if merged_at and status == PRStatus.MERGED:
                pr.merged_at = merged_at
            
            db.commit()
            db.refresh(pr)
            
            logger.info(f"Updated PR {pr_id} status to {status.value}")
            return pr
            
        except Exception as e:
            logger.error(f"Error updating PR status: {e}")
            db.rollback()
            raise
        finally:
            if close_session:
                db.close()
    
    @handle_errors
    def sync_pr_status_from_github(self, pr_id: int, db: Optional[Session] = None) -> Optional[PullRequest]:
        """Sync PR status from GitHub."""
        close_session = False
        if not db:
            db = SessionLocal()
            close_session = True
        
        try:
            pr = db.query(PullRequest).filter_by(id=pr_id).first()
            if not pr:
                logger.warning(f"PR not found: {pr_id}")
                return None
            
            # Extract owner and repo from repository
            parts = pr.repository.split('/')
            if len(parts) != 2:
                logger.error(f"Invalid repository format: {pr.repository}")
                return pr
            
            owner, repo = parts
            
            # Get PR details from GitHub
            github_pr = self.github_service.get_pull_request(owner, repo, pr.github_pr_number)
            if not github_pr:
                logger.warning(f"GitHub PR not found: {owner}/{repo}#{pr.github_pr_number}")
                return pr
            
            # Map GitHub state to our PRStatus
            new_status = self._map_github_state_to_status(
                github_pr['state'], 
                github_pr.get('draft', False),
                github_pr.get('merged', False)
            )
            
            # Update if status changed
            if pr.status != new_status:
                merged_at = None
                if new_status == PRStatus.MERGED and github_pr.get('merged_at'):
                    merged_at = datetime.fromisoformat(github_pr['merged_at'].replace('Z', '+00:00'))
                
                return self.update_pr_status(pr.id, new_status, merged_at, db)
            
            return pr
            
        except Exception as e:
            logger.error(f"Error syncing PR status from GitHub: {e}")
            raise
        finally:
            if close_session:
                db.close()
    
    @handle_errors
    def sync_all_open_prs(self, db: Optional[Session] = None) -> int:
        """Sync all open PRs from GitHub. Returns count of updated PRs."""
        close_session = False
        if not db:
            db = SessionLocal()
            close_session = True
        
        try:
            # Get all open PRs
            open_prs = db.query(PullRequest).filter(
                PullRequest.status.in_([PRStatus.OPEN, PRStatus.DRAFT])
            ).all()
            
            updated_count = 0
            for pr in open_prs:
                try:
                    updated_pr = self.sync_pr_status_from_github(pr.id, db)
                    if updated_pr and updated_pr.status != pr.status:
                        updated_count += 1
                except Exception as e:
                    logger.error(f"Error syncing PR {pr.id}: {e}")
                    continue
            
            logger.info(f"Synced {len(open_prs)} open PRs, {updated_count} updated")
            return updated_count
            
        except Exception as e:
            logger.error(f"Error syncing all open PRs: {e}")
            raise
        finally:
            if close_session:
                db.close()
    
    @handle_errors
    def get_user_prs(
        self,
        user_id: int,
        status: Optional[PRStatus] = None,
        limit: int = 50,
        offset: int = 0,
        db: Optional[Session] = None
    ) -> List[PullRequest]:
        """Get PRs for a specific user."""
        close_session = False
        if not db:
            db = SessionLocal()
            close_session = True
        
        try:
            query = db.query(PullRequest).filter_by(user_id=user_id)
            
            if status:
                query = query.filter_by(status=status)
            
            prs = query.order_by(desc(PullRequest.created_at)).limit(limit).offset(offset).all()
            
            return prs
            
        except Exception as e:
            logger.error(f"Error getting user PRs: {e}")
            raise
        finally:
            if close_session:
                db.close()
    
    @handle_errors
    def get_pr_stats(self, user_id: Optional[int] = None, db: Optional[Session] = None) -> Dict[str, int]:
        """Get PR statistics."""
        close_session = False
        if not db:
            db = SessionLocal()
            close_session = True
        
        try:
            query = db.query(PullRequest)
            if user_id:
                query = query.filter_by(user_id=user_id)
            
            total = query.count()
            open_count = query.filter_by(status=PRStatus.OPEN).count()
            draft_count = query.filter_by(status=PRStatus.DRAFT).count()
            merged_count = query.filter_by(status=PRStatus.MERGED).count()
            closed_count = query.filter_by(status=PRStatus.CLOSED).count()
            
            return {
                'total': total,
                'open': open_count,
                'draft': draft_count,
                'merged': merged_count,
                'closed': closed_count
            }
            
        except Exception as e:
            logger.error(f"Error getting PR stats: {e}")
            raise
        finally:
            if close_session:
                db.close()
    
    def _map_github_state_to_status(self, state: str, is_draft: bool, merged: bool = False) -> PRStatus:
        """Map GitHub PR state to our PRStatus enum."""
        if is_draft:
            return PRStatus.DRAFT
        elif state == 'open':
            return PRStatus.OPEN
        elif state == 'closed':
            # Check if it was merged
            return PRStatus.MERGED if merged else PRStatus.CLOSED
        else:
            return PRStatus.CLOSED
    
    @handle_errors
    def get_all_prs(
        self,
        status: Optional[PRStatus] = None,
        repository: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        db: Optional[Session] = None
    ) -> List[PullRequest]:
        """Get all PRs with optional filtering."""
        close_session = False
        if not db:
            db = SessionLocal()
            close_session = True
        
        try:
            query = db.query(PullRequest)
            
            if status:
                query = query.filter_by(status=status)
            
            if repository:
                query = query.filter_by(repository=repository)
            
            prs = query.order_by(desc(PullRequest.created_at)).limit(limit).offset(offset).all()
            
            return prs
            
        except Exception as e:
            logger.error(f"Error getting all PRs: {e}")
            raise
        finally:
            if close_session:
                db.close()