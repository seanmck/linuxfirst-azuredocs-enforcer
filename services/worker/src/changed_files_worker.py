"""
ChangedFilesWorker - Handles processing of individual files from the changed_files queue

This worker processes file change messages from the GitHubDiscoveryService and creates
document processing tasks for the main document worker pipeline.
"""
import sys
import os
import time
import datetime
import hashlib
from typing import Dict, Any, Optional

# Add the project root to the Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
sys.path.insert(0, project_root)

from sqlalchemy.orm import Session
from shared.models import Scan, Page, Snippet
from shared.config import config
from shared.infrastructure.queue_service import QueueService
from shared.infrastructure.github_service import GitHubService
from shared.infrastructure.url_lock_service import url_lock_service
from shared.application.progress_tracker import progress_tracker
from shared.application.processing_history_service import ProcessingHistoryService
from shared.utils.database import SessionLocal
from shared.utils.logging import get_logger
from shared.utils.metrics import get_metrics


class ChangedFilesWorker:
    """Worker that processes individual file changes from the changed_files queue"""
    
    def __init__(self):
        self.queue_service = QueueService(queue_name='changed_files')
        self.doc_queue_service = QueueService(queue_name='doc_processing')
        self.github_service = GitHubService()
        self.logger = get_logger(__name__)
        self.metrics = get_metrics()
        self.worker_id = f"changed_files_worker_{os.getpid()}_{int(time.time())}"

    def process_file_change(self, message: Dict[str, Any]) -> bool:
        """
        Process a single file change message from the queue
        
        Args:
            message: File change message from GitHubDiscoveryService
            
        Returns:
            True if successful, False otherwise
        """
        scan_id = message.get('scan_id')
        file_path = message.get('path')
        file_sha = message.get('sha')
        change_type = message.get('change_type')
        commit_sha = message.get('commit_sha')
        
        self.logger.info(f"Processing file change: {file_path} (scan_id: {scan_id}, change_type: {change_type})")
        
        # Check if scan has been cancelled
        if self._is_scan_cancelled(scan_id):
            self.logger.info(f"Scan {scan_id} was cancelled, skipping file processing for {file_path}")
            return True
        
        # Record file processing start time
        processing_start_time = time.time()
        
        # Create database session
        db_session = SessionLocal()
        
        try:
            # Get scan record
            scan = db_session.query(Scan).filter(Scan.id == scan_id).first()
            if not scan:
                self.logger.error(f"Scan with ID {scan_id} not found")
                return False
            
            # Parse GitHub URL to get repo info
            parsed_url = self.github_service.parse_github_url(scan.url)
            if not parsed_url:
                self.logger.error(f"Could not parse GitHub URL: {scan.url}")
                return False
            
            repo_full_name = parsed_url['repo_full_name']
            branch = parsed_url['branch']
            
            # Generate GitHub URL for this file
            github_url = self.github_service.generate_github_url(repo_full_name, branch, file_path)
            
            # Skip Windows-focused files
            if self.github_service.is_windows_focused_url(github_url):
                self.logger.info(f"Skipping Windows-focused file: {github_url}")
                return True
            
            # Handle deleted files
            if change_type == 'removed':
                return self._handle_deleted_file(db_session, scan_id, github_url, file_path)
            
            # Get file content
            file_content = self.github_service.get_file_content(repo_full_name, file_path, branch)
            if not file_content:
                self.logger.error(f"Could not get file content for {file_path}")
                return False
            
            # Skip Windows-focused content
            if self.github_service.is_windows_focused_content(file_content):
                self.logger.info(f"Skipping Windows-focused content: {file_path}")
                return True
            
            # Create processing history service
            history_service = ProcessingHistoryService(db_session)
            
            # Record processing start
            history_id = history_service.record_processing_start(
                file_path, file_sha, scan_id, self.worker_id, commit_sha
            )
            
            # Create or update page record
            page = self._create_or_update_page(db_session, scan_id, github_url, file_path, file_sha, file_content)
            if not page:
                self.logger.error(f"Could not create page record for {file_path}")
                # Record failure in history
                history_service.record_processing_completion(
                    file_path, file_sha, scan_id, 'failed', int(time.time() * 1000 - processing_start_time * 1000),
                    error_message="Could not create page record"
                )
                return False
            
            # Try to acquire URL processing lock
            content_hash = hashlib.sha256(file_content.encode('utf-8')).hexdigest()
            lock_acquired, lock_reason = url_lock_service.acquire_url_lock(
                db_session, github_url, content_hash, scan_id
            )
            
            if not lock_acquired:
                self.logger.info(f"Could not acquire lock for {github_url}: {lock_reason}")
                page.status = 'skipped_locked'
                page.processing_state = 'skipped_locked'
                db_session.commit()
                
                # Record in history
                history_service.record_processing_completion(
                    file_path, file_sha, scan_id, 'skipped', 
                    int(time.time() * 1000 - processing_start_time * 1000),
                    error_message=f"Could not acquire lock: {lock_reason}"
                )
                return True
            
            # Create document processing task
            task_data = {
                'page_id': page.id,
                'scan_id': scan_id,
                'url': github_url,
                'file_content': file_content
            }
            
            # Queue the document for processing
            if self.doc_queue_service.connect():
                if self.doc_queue_service.publish_task(task_data):
                    page.status = 'queued'
                    page.processing_state = 'queued'
                    db_session.commit()
                    
                    # Record queue metrics
                    self.metrics.record_queue_task_published('doc_processing')
                    
                    # Record successful queuing in history
                    history_service.record_processing_completion(
                        file_path, file_sha, scan_id, 'queued',
                        int(time.time() * 1000 - processing_start_time * 1000)
                    )
                    
                    self.logger.info(f"Successfully queued document for processing: {github_url}")
                else:
                    # Failed to queue, release the lock
                    url_lock_service.release_url_lock(
                        db_session, github_url, content_hash, scan_id, success=False
                    )
                    page.status = 'queue_failed'
                    page.processing_state = 'failed'
                    db_session.commit()
                    
                    # Record failure in history
                    history_service.record_processing_completion(
                        file_path, file_sha, scan_id, 'failed',
                        int(time.time() * 1000 - processing_start_time * 1000),
                        error_message="Failed to queue document for processing"
                    )
                    
                    self.logger.error(f"Failed to queue document for processing: {github_url}")
                    
                self.doc_queue_service.disconnect()
            else:
                self.logger.error("Failed to connect to document processing queue")
                return False
            
            # Record successful file processing
            self.metrics.record_file_change_processed(change_type, 'success', time.time() - processing_start_time)
            
            # Update scan progress
            self._update_scan_progress(db_session, scan_id)
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error processing file change {file_path}: {e}", exc_info=True)
            self.metrics.record_file_change_processed(change_type, 'error', time.time() - processing_start_time)
            
            # Record error in history if we have the required info
            if 'db_session' in locals() and file_path and file_sha:
                try:
                    history_service = ProcessingHistoryService(db_session)
                    history_service.record_processing_completion(
                        file_path, file_sha, scan_id, 'failed',
                        int(time.time() * 1000 - processing_start_time * 1000),
                        error_message=str(e)
                    )
                except Exception as hist_error:
                    self.logger.error(f"Error recording processing history: {hist_error}")
            
            return False
            
        finally:
            db_session.close()

    def _create_or_update_page(self, db_session: Session, scan_id: int, github_url: str, 
                              file_path: str, file_sha: str, file_content: str) -> Optional[Page]:
        """Create or update a page record for the file"""
        try:
            # Check if page already exists for this scan
            page = db_session.query(Page).filter(
                Page.scan_id == scan_id,
                Page.url == github_url
            ).first()
            
            if not page:
                # Create new page
                page = Page(
                    scan_id=scan_id,
                    url=github_url,
                    status='discovered'
                )
                db_session.add(page)
            
            # Update page metadata
            page.github_sha = file_sha
            page.content_hash = hashlib.sha256(file_content.encode('utf-8')).hexdigest()
            page.last_scanned_at = datetime.datetime.now(datetime.timezone.utc)
            page.processing_state = 'discovered'
            
            # Note: File SHA already available from discovery stage, no need for additional metadata calls
            # This removes 2 redundant GitHub API calls per file (get_contents + get_commits)
            
            db_session.commit()
            return page
            
        except Exception as e:
            self.logger.error(f"Error creating/updating page for {github_url}: {e}")
            return None

    def _handle_deleted_file(self, db_session: Session, scan_id: int, github_url: str, file_path: str) -> bool:
        """Handle deleted files by marking them as removed"""
        try:
            # Find existing page for this URL
            page = db_session.query(Page).filter(
                Page.scan_id == scan_id,
                Page.url == github_url
            ).first()
            
            if page:
                page.status = 'removed'
                db_session.commit()
                self.logger.info(f"Marked file as removed: {github_url}")
            else:
                self.logger.info(f"No existing page found for deleted file: {github_url}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error handling deleted file {github_url}: {e}")
            return False

    def _update_scan_progress(self, db_session: Session, scan_id: int):
        """Update scan progress counters"""
        try:
            # Get current progress
            scan = db_session.query(Scan).filter(Scan.id == scan_id).first()
            if not scan:
                return
            
            # Count completed files
            completed_count = db_session.query(Page).filter(
                Page.scan_id == scan_id,
                Page.status.in_(['processed', 'removed', 'skipped_locked', 'skipped_no_change'])
            ).count()
            
            # Update scan progress
            scan.total_files_completed = completed_count
            db_session.commit()
            
            # Check if scan is complete
            if scan.total_files_queued > 0 and completed_count >= scan.total_files_queued:
                self._finalize_scan(db_session, scan_id)
                
        except Exception as e:
            self.logger.error(f"Error updating scan progress for scan {scan_id}: {e}")

    def _finalize_scan(self, db_session: Session, scan_id: int):
        """Finalize scan when all files are processed"""
        try:
            scan = db_session.query(Scan).filter(Scan.id == scan_id).first()
            if not scan:
                return
            
            # Mark scan as complete
            scan.status = 'done'
            scan.finished_at = datetime.datetime.now(datetime.timezone.utc)
            
            # Set last_commit_sha for future incremental scans
            if scan.working_commit_sha:
                scan.last_commit_sha = scan.working_commit_sha
            
            db_session.commit()
            
            self.logger.info(f"Scan {scan_id} finalized successfully")
            
        except Exception as e:
            self.logger.error(f"Error finalizing scan {scan_id}: {e}")

    def _is_scan_cancelled(self, scan_id: int) -> bool:
        """Check if scan has been cancelled"""
        try:
            db_session = SessionLocal()
            scan = db_session.query(Scan).filter(Scan.id == scan_id).first()
            cancelled = scan and scan.cancellation_requested
            db_session.close()
            return cancelled
        except Exception as e:
            self.logger.error(f"Error checking cancellation status: {e}")
            return False

    def start_consuming(self):
        """Start consuming file change messages from the queue"""
        self.logger.info("Changed files worker starting...")
        
        retry_count = 0
        max_retries = 3
        base_delay = 5  # seconds
        
        while retry_count < max_retries:
            try:
                self.logger.info(f"Starting to consume file changes (attempt {retry_count + 1}/{max_retries})...")
                self.queue_service.consume_tasks(self.process_file_change)
                
                # If we get here, consumption ended normally
                break
                
            except Exception as e:
                retry_count += 1
                self.logger.error(f"Error during file change consumption (attempt {retry_count}/{max_retries}): {e}", exc_info=True)
                
                if retry_count < max_retries:
                    delay = base_delay * (2 ** (retry_count - 1))  # Exponential backoff
                    self.logger.info(f"Retrying in {delay} seconds...")
                    time.sleep(delay)
                else:
                    self.logger.error("Max retries reached. Changed files worker shutting down.")


if __name__ == "__main__":
    worker = ChangedFilesWorker()
    worker.start_consuming()