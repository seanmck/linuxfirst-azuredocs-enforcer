"""
URL Lock Service - Manages global URL processing locks to prevent duplicate work across scans
"""
import datetime
import uuid
import socket
from typing import Optional, Tuple, List
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import and_, or_

from shared.models import ProcessingUrl, Page
from shared.utils.logging import get_logger
from shared.utils.database import safe_commit

logger = get_logger(__name__)


class UrlLockService:
    """Service to manage URL processing locks across multiple scans"""
    
    def __init__(self, lock_timeout_minutes: int = 30):
        self.lock_timeout_minutes = lock_timeout_minutes
        self.worker_id = f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
        
    def acquire_url_lock(
        self, 
        db: Session, 
        url: str, 
        content_hash: str, 
        scan_id: int
    ) -> Tuple[bool, Optional[str]]:
        """
        Attempt to acquire a processing lock for a URL+content_hash combination.
        
        Args:
            db: Database session
            url: The URL to lock
            content_hash: Content hash for the URL
            scan_id: ID of the scan requesting the lock
            
        Returns:
            Tuple of (success: bool, reason: Optional[str])
            - (True, None) if lock acquired successfully
            - (False, reason) if lock could not be acquired
        """
        try:
            # Clean up expired locks first
            self._cleanup_expired_locks(db)
            
            # Check if URL+hash is already being processed
            existing_lock = db.query(ProcessingUrl).filter(
                ProcessingUrl.url == url,
                ProcessingUrl.content_hash == content_hash,
                ProcessingUrl.status == 'processing'
            ).first()
            
            if existing_lock:
                # Check if it's the same scan
                if existing_lock.scan_id == scan_id:
                    logger.info(f"URL {url} already locked by same scan {scan_id}")
                    return False, f"Already processing in scan {scan_id}"
                else:
                    logger.info(f"URL {url} already locked by scan {existing_lock.scan_id}")
                    return False, f"Already processing in scan {existing_lock.scan_id}"
            
            # Check if content hasn't changed since last processing
            if not self._should_reprocess_url(db, url, content_hash, scan_id):
                logger.info(f"URL {url} content unchanged, skipping processing")
                return False, "Content unchanged since last processing"
            
            # Attempt to acquire lock
            now = datetime.datetime.utcnow()
            expires_at = now + datetime.timedelta(minutes=self.lock_timeout_minutes)
            
            processing_lock = ProcessingUrl(
                url=url,
                content_hash=content_hash,
                scan_id=scan_id,
                worker_id=self.worker_id,
                started_at=now,
                expires_at=expires_at,
                status='processing'
            )
            
            db.add(processing_lock)
            safe_commit(db)
            
            logger.info(f"Acquired processing lock for {url} (scan {scan_id}, worker {self.worker_id})")
            return True, None
            
        except IntegrityError as e:
            db.rollback()
            logger.warning(f"Failed to acquire lock for {url} due to constraint violation: {e}")
            return False, "Lock already exists (race condition)"
        except Exception as e:
            db.rollback()
            logger.error(f"Error acquiring lock for {url}: {e}")
            return False, f"Database error: {str(e)}"
    
    def release_url_lock(
        self, 
        db: Session, 
        url: str, 
        content_hash: str, 
        scan_id: int,
        success: bool = True
    ) -> bool:
        """
        Release a processing lock for a URL.
        
        Args:
            db: Database session
            url: The URL to unlock
            content_hash: Content hash for the URL
            scan_id: ID of the scan releasing the lock
            success: Whether processing completed successfully
            
        Returns:
            True if lock was released, False otherwise
        """
        try:
            lock = db.query(ProcessingUrl).filter(
                ProcessingUrl.url == url,
                ProcessingUrl.content_hash == content_hash,
                ProcessingUrl.scan_id == scan_id,
                ProcessingUrl.status == 'processing'
            ).first()
            
            if lock:
                if success:
                    lock.status = 'completed'
                else:
                    lock.status = 'failed'
                
                safe_commit(db)
                logger.info(f"Released processing lock for {url} (scan {scan_id}, status: {lock.status})")
                return True
            else:
                logger.warning(f"No active lock found for {url} (scan {scan_id})")
                return False
                
        except Exception as e:
            logger.error(f"Error releasing lock for {url}: {e}")
            return False
    
    def is_url_locked(
        self, 
        db: Session, 
        url: str, 
        content_hash: str
    ) -> Tuple[bool, Optional[int]]:
        """
        Check if a URL+content_hash is currently locked for processing.
        
        Args:
            db: Database session
            url: The URL to check
            content_hash: Content hash for the URL
            
        Returns:
            Tuple of (is_locked: bool, scan_id: Optional[int])
        """
        try:
            # Clean up expired locks first
            self._cleanup_expired_locks(db)
            
            lock = db.query(ProcessingUrl).filter(
                ProcessingUrl.url == url,
                ProcessingUrl.content_hash == content_hash,
                ProcessingUrl.status == 'processing'
            ).first()
            
            if lock:
                return True, lock.scan_id
            else:
                return False, None
                
        except Exception as e:
            logger.error(f"Error checking lock for {url}: {e}")
            return False, None
    
    def _should_reprocess_url(
        self, 
        db: Session, 
        url: str, 
        content_hash: str, 
        current_scan_id: int
    ) -> bool:
        """
        Determine if a URL should be reprocessed based on content changes.
        
        Args:
            db: Database session
            url: The URL to check
            content_hash: Content hash for the URL
            current_scan_id: Current scan ID
            
        Returns:
            True if URL should be processed, False if can be skipped
        """
        try:
            # Check if this exact content has been processed before
            existing_processing = db.query(ProcessingUrl).filter(
                ProcessingUrl.url == url,
                ProcessingUrl.content_hash == content_hash,
                ProcessingUrl.status == 'completed'
            ).first()
            
            if existing_processing:
                logger.info(f"URL {url} with same content hash already processed successfully")
                return False
            
            # Check for recent successful processing of this URL with same content
            recent_page = db.query(Page).filter(
                Page.url == url,
                Page.content_hash == content_hash,
                Page.status == 'processed'
            ).order_by(Page.last_scanned_at.desc()).first()
            
            if recent_page:
                logger.info(f"URL {url} with same content recently processed in scan {recent_page.scan_id}")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error checking if URL should be reprocessed: {e}")
            # When in doubt, allow processing
            return True
    
    def _cleanup_expired_locks(self, db: Session) -> int:
        """
        Clean up expired processing locks.
        
        Args:
            db: Database session
            
        Returns:
            Number of locks cleaned up
        """
        try:
            now = datetime.datetime.utcnow()
            
            # Find expired locks
            expired_locks = db.query(ProcessingUrl).filter(
                ProcessingUrl.expires_at < now,
                ProcessingUrl.status == 'processing'
            ).all()
            
            # Mark them as expired
            for lock in expired_locks:
                lock.status = 'expired'
                logger.warning(f"Expired processing lock for {lock.url} (scan {lock.scan_id}, worker {lock.worker_id})")
            
            if expired_locks:
                safe_commit(db)
                
            return len(expired_locks)
            
        except Exception as e:
            logger.error(f"Error cleaning up expired locks: {e}")
            return 0
    
    def get_processing_stats(self, db: Session) -> dict:
        """
        Get statistics about current processing locks.
        
        Args:
            db: Database session
            
        Returns:
            Dictionary with processing statistics
        """
        try:
            # Clean up expired locks first
            self._cleanup_expired_locks(db)
            
            total_locks = db.query(ProcessingUrl).count()
            active_locks = db.query(ProcessingUrl).filter(
                ProcessingUrl.status == 'processing'
            ).count()
            completed_locks = db.query(ProcessingUrl).filter(
                ProcessingUrl.status == 'completed'
            ).count()
            failed_locks = db.query(ProcessingUrl).filter(
                ProcessingUrl.status == 'failed'
            ).count()
            expired_locks = db.query(ProcessingUrl).filter(
                ProcessingUrl.status == 'expired'
            ).count()
            
            return {
                'total_locks': total_locks,
                'active_processing': active_locks,
                'completed': completed_locks,
                'failed': failed_locks,
                'expired': expired_locks,
                'worker_id': self.worker_id
            }
            
        except Exception as e:
            logger.error(f"Error getting processing stats: {e}")
            return {'error': str(e)}


# Global URL lock service instance
url_lock_service = UrlLockService()