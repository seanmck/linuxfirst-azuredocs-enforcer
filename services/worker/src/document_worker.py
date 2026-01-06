"""
DocumentWorker - Handles processing of individual documents from the changed_files queue
This enables horizontal scaling based on document count rather than scan task count
"""
import sys
import os
import time
import datetime
import hashlib
import signal
import threading
from typing import Dict, Any, List, Optional

# Add the project root to the Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
sys.path.insert(0, project_root)

from sqlalchemy.orm import Session
from sqlalchemy import Boolean
from shared.models import Scan, Page, Snippet
from shared.config import config, get_repo_from_url
from shared.infrastructure.queue_service import QueueService
from scoring_service import ScoringService
from shared.infrastructure.github_service import GitHubService
from shared.infrastructure.url_lock_service import url_lock_service
from shared.application.progress_tracker import progress_tracker
from shared.application.processing_history_service import ProcessingHistoryService
from shared.utils.database import SessionLocal
from shared.utils.logging import get_logger
from shared.utils.metrics import get_metrics
from shared.utils.url_utils import extract_doc_set_from_url
from packages.extractor.parser import extract_code_snippets
from packages.scorer.heuristics import page_has_windows_signals


class DocumentWorker:
    """Worker that processes individual documents from the changed_files queue"""
    
    def __init__(self):
        self.queue_service = QueueService(queue_name='changed_files')
        self.llm_queue_service = QueueService(queue_name='llm_scoring')
        self.scoring_service = ScoringService()
        self.github_service = GitHubService()
        # Note: Using progress_tracker directly instead of progress_service to avoid FastAPI dependency
        self.logger = get_logger(__name__)
        self.metrics = get_metrics()
        self.worker_id = f"document_worker_{os.getpid()}_{int(time.time())}"
        self.shutdown_event = threading.Event()
        self.setup_signal_handlers()
        # Connect to LLM scoring queue for publishing
        self.llm_queue_service.connect()

    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        def signal_handler(signum, frame):
            self.logger.info(f"Received signal {signum}, initiating graceful shutdown...")
            self.shutdown_event.set()
        
        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

    def process_document_task(self, message: Dict[str, Any]) -> bool:
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
                # Create page record to track the skip
                page = self._create_or_update_page(db_session, scan_id, github_url, file_path, file_sha, "")
                if page:
                    page.status = 'skipped_windows_focused'
                    # Clear processing lock metadata
                    page.processing_started_at = None
                    page.processing_worker_id = None
                    page.processing_expires_at = None
                    db_session.commit()
                # Update scan progress
                self._update_scan_progress(db_session, scan_id)
                return True
            
            # Handle deleted files
            if change_type == 'removed':
                return self._handle_deleted_file(db_session, scan_id, github_url, file_path)
            
            # Get file content (with fallback to public repo if private fails)
            file_content = self.github_service.get_file_content(repo_full_name, file_path, branch)

            # If primary repo fails, try public repo fallback
            if not file_content:
                repo_config = get_repo_from_url(scan.url)
                if repo_config and repo_config.name != repo_config.public_name:
                    public_repo = repo_config.public_full_name
                    self.logger.info(f"Primary repo failed, trying public fallback: {public_repo}")
                    file_content = self.github_service.get_file_content(public_repo, file_path, branch)
                    if file_content:
                        # Update github_url to use public repo for consistency
                        github_url = self.github_service.generate_github_url(public_repo, branch, file_path)
                        self.logger.info(f"Successfully fetched from public repo: {file_path}")

            if not file_content:
                self.logger.warning(f"Could not get file content for {file_path}, skipping file")
                # Mark page as skipped
                page = self._create_or_update_page(db_session, scan_id, github_url, file_path, file_sha, "")
                if page:
                    page.status = 'skipped_unreadable'
                    # Clear processing lock metadata
                    page.processing_started_at = None
                    page.processing_worker_id = None
                    page.processing_expires_at = None
                    db_session.commit()
                # Update scan progress
                self._update_scan_progress(db_session, scan_id)
                return True  # Return True to acknowledge message and move on
            
            # Check file size to avoid OOM issues
            file_size_mb = len(file_content.encode('utf-8')) / (1024 * 1024)
            if file_size_mb > 5:  # Skip files larger than 5MB
                self.logger.warning(f"File {file_path} is too large ({file_size_mb:.1f}MB), skipping to avoid memory issues")
                page = self._create_or_update_page(db_session, scan_id, github_url, file_path, file_sha, "")
                if page:
                    page.status = 'skipped_too_large'
                    # Clear processing lock metadata
                    page.processing_started_at = None
                    page.processing_worker_id = None
                    page.processing_expires_at = None
                    db_session.commit()
                # Update scan progress
                self._update_scan_progress(db_session, scan_id)
                return True
            
            # Skip Windows-focused content
            if self.github_service.is_windows_focused_content(file_content):
                self.logger.info(f"Skipping Windows-focused content: {file_path}")
                # Update page status to track the skip
                page = self._create_or_update_page(db_session, scan_id, github_url, file_path, file_sha, "")
                if page:
                    page.status = 'skipped_windows_focused'
                    # Clear processing lock metadata
                    page.processing_started_at = None
                    page.processing_worker_id = None
                    page.processing_expires_at = None
                    db_session.commit()
                # Update scan progress
                self._update_scan_progress(db_session, scan_id)
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
                return False
            
            # Process the document (extract code blocks, score, etc.)
            success = self._process_github_document(db_session, page, file_content, scan_id)
            
            if success:
                # Mark page as processed
                page.status = 'processed'
                page.processing_started_at = None
                page.processing_worker_id = None
                page.processing_expires_at = None
                db_session.commit()
                
                # Record successful processing in history
                history_service.record_processing_completion(
                    file_path, file_sha, scan_id, 'processed',
                    int(time.time() * 1000 - processing_start_time * 1000)
                )
                
                self.logger.info(f"Successfully processed file: {github_url}")
                
                # Record successful processing metrics
                self.metrics.record_file_change_processed(change_type, 'success', time.time() - processing_start_time)
                
                # Update scan progress
                self._update_scan_progress(db_session, scan_id)
                
                return True
            else:
                # Mark page as error
                page.status = 'error'
                page.last_error_at = datetime.datetime.now(datetime.timezone.utc)
                # Clear processing lock metadata
                page.processing_started_at = None
                page.processing_worker_id = None
                page.processing_expires_at = None
                db_session.commit()
                
                # Record failure in history
                history_service.record_processing_completion(
                    file_path, file_sha, scan_id, 'failed',
                    int(time.time() * 1000 - processing_start_time * 1000),
                    error_message="Failed to process document"
                )
                
                self.logger.error(f"Failed to process file: {github_url}")
                
                # Record failed processing metrics
                self.metrics.record_file_change_processed(change_type, 'error', time.time() - processing_start_time)
                
                return False
                
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


    def _process_github_document(self, db_session: Session, page: Page, file_content: str, scan_id: int) -> bool:
        """
        Process a GitHub document (extract code blocks, score, and holistic analysis)
        
        Args:
            db_session: Database session
            page: Page record
            file_content: File content to process
            scan_id: Scan ID
            
        Returns:
            True if successful, False otherwise
        """
        try:
            url = page.url
            
            if not file_content:
                self.logger.error(f"No file content provided for {url}")
                return False
                
            # Extract code blocks from markdown
            code_blocks = self.github_service.extract_code_blocks(file_content)
            all_snippets = []
            
            for code in code_blocks:
                snippet_obj = Snippet(
                    page_id=page.id,
                    context='',
                    code=code,
                    llm_score=None
                )
                db_session.add(snippet_obj)
                snippet_dict = {
                    'code': code,
                    'context': '',
                    'url': url,
                    'snippet_obj': snippet_obj
                }
                all_snippets.append(snippet_dict)
                
            db_session.commit()
            self.logger.info(f"Extracted {len(all_snippets)} code blocks from {url}")

            # Unified scoring: use heuristic filter to decide if LLM review is needed
            if page_has_windows_signals(file_content):
                # Page has Windows signals - publish to LLM queue (non-blocking)
                self.logger.info(f"Windows signals detected in {url}, queuing for LLM review")
                self.llm_queue_service.publish_task({
                    'scan_id': scan_id,
                    'page_id': page.id,
                    'page_url': url,
                    'page_content': file_content
                })
                page.mcp_holistic = {
                    'review_method': 'llm_pending',
                    'queued_at': datetime.datetime.now(datetime.timezone.utc).isoformat()
                }
                db_session.commit()
            else:
                # No Windows signals - skip LLM entirely
                self.logger.info(f"No Windows signals in {url}, skipping LLM review")
                page.mcp_holistic = {
                    'bias_types': [],
                    'summary': None,
                    'review_method': 'heuristic_skip',
                    'skip_reason': 'No Windows signals detected'
                }
                db_session.commit()

            return True
            
        except Exception as e:
            self.logger.error(f"Error processing GitHub document {page.url}: {e}", exc_info=True)
            return False


    def _extract_file_path_from_url(self, github_url: str) -> Optional[str]:
        """Extract file path from GitHub URL for history tracking"""
        try:
            # Example: https://github.com/owner/repo/blob/branch/path/to/file.md
            # Extract: path/to/file.md
            parts = github_url.split('/blob/')
            if len(parts) == 2:
                # Remove branch part
                path_with_branch = parts[1]
                path_parts = path_with_branch.split('/', 1)
                if len(path_parts) == 2:
                    return path_parts[1]
        except Exception as e:
            self.logger.error(f"Error extracting file path from URL {github_url}: {e}")
        return None
    
    def _check_bias_detected(self, db_session: Session, page_id: int) -> bool:
        """Check if bias was detected in any snippets for this page"""
        try:
            biased_snippets = db_session.query(Snippet).filter(
                Snippet.page_id == page_id,
                Snippet.llm_score.op('->>')('windows_biased').cast(Boolean) == True
            ).count()
            
            return biased_snippets > 0
        except Exception as e:
            self.logger.error(f"Error checking bias detection for page {page_id}: {e}")
            return False

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

    def _create_or_update_page(self, db_session: Session, scan_id: int, github_url: str, 
                               file_path: str, file_sha: str, file_content: str) -> Optional[Page]:
        """Create or update page record with file information"""
        try:
            # Calculate content hash
            content_hash = hashlib.sha256(file_content.encode()).hexdigest()
            
            # Get current timestamp and calculate expiration
            now = datetime.datetime.now(datetime.timezone.utc)
            expires_at = now + datetime.timedelta(minutes=30)
            
            # Check if page already exists
            page = db_session.query(Page).filter(
                Page.scan_id == scan_id,
                Page.url == github_url
            ).first()
            
            if page:
                # Update existing page
                page.content_hash = content_hash
                page.github_sha = file_sha
                page.last_scanned_at = now
                page.processing_state = 'discovered'
                page.status = 'processing'
                # Ensure doc_set is populated (backfill if missing)
                if not page.doc_set:
                    page.doc_set = extract_doc_set_from_url(github_url)
                # Set processing lock metadata
                page.processing_started_at = now
                page.processing_worker_id = self.worker_id
                page.processing_expires_at = expires_at
            else:
                # Create new page
                page = Page(
                    scan_id=scan_id,
                    url=github_url,
                    status='processing',
                    content_hash=content_hash,
                    github_sha=file_sha,
                    last_scanned_at=now,
                    processing_state='discovered',
                    doc_set=extract_doc_set_from_url(github_url),
                    # Set processing lock metadata
                    processing_started_at=now,
                    processing_worker_id=self.worker_id,
                    processing_expires_at=expires_at
                )
                db_session.add(page)
            
            db_session.commit()
            return page
            
        except Exception as e:
            self.logger.error(f"Error creating/updating page for {github_url}: {e}")
            return None

    def _handle_deleted_file(self, db_session: Session, scan_id: int, github_url: str, file_path: str) -> bool:
        """Handle deleted file by updating page status"""
        try:
            page = db_session.query(Page).filter(
                Page.scan_id == scan_id,
                Page.url == github_url
            ).first()
            
            if page:
                page.status = 'removed'
                page.processing_state = 'removed'
                db_session.commit()
                self.logger.info(f"Marked deleted file as removed: {github_url}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error handling deleted file {file_path}: {e}")
            return False

    def _update_scan_progress(self, db_session: Session, scan_id: int):
        """Update scan progress and check for completion"""
        try:
            scan = db_session.query(Scan).filter(Scan.id == scan_id).first()
            if not scan:
                return
            
            # Count completed files (including errors as they won't be retried)
            completed_count = db_session.query(Page).filter(
                Page.scan_id == scan_id,
                Page.status.in_(['processed', 'removed', 'skipped_locked', 'skipped_no_change', 
                               'skipped_unreadable', 'skipped_too_large', 'skipped_windows_focused', 'error'])
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

            # Check if any pages are still pending LLM scoring
            pending_llm = db_session.query(Page).filter(
                Page.scan_id == scan_id,
                Page.mcp_holistic['review_method'].astext == 'llm_pending'
            ).count()

            if pending_llm > 0:
                self.logger.info(f"Scan {scan_id} has {pending_llm} pages still pending LLM scoring, skipping finalization")
                return

            # Calculate metrics
            total_pages = db_session.query(Page).filter(Page.scan_id == scan.id).count()
            processed_pages = db_session.query(Page).filter(
                Page.scan_id == scan.id,
                Page.status == 'processed'
            ).count()
            error_pages = db_session.query(Page).filter(
                Page.scan_id == scan.id,
                Page.status == 'error'
            ).count()
            
            # Count biased pages (pages with bias detected)
            biased_pages_count = db_session.query(Page).filter(
                Page.scan_id == scan.id,
                Page.mcp_holistic.isnot(None)
            ).count()
            
            # Count flagged snippets
            flagged_snippets_count = db_session.query(Snippet).join(Page).filter(
                Page.scan_id == scan.id,
                Snippet.llm_score.isnot(None)
            ).count()
            
            # Mark scan as complete
            scan.status = 'completed'
            scan.finished_at = datetime.datetime.now(datetime.timezone.utc)
            scan.biased_pages_count = biased_pages_count
            scan.flagged_snippets_count = flagged_snippets_count
            
            # Set last_commit_sha for future incremental scans
            if scan.working_commit_sha:
                scan.last_commit_sha = scan.working_commit_sha
            
            db_session.commit()
            
            self.logger.info(f"Scan {scan_id} finalized successfully: {processed_pages} processed, {error_pages} errors, {biased_pages_count} biased pages, {flagged_snippets_count} flagged snippets")
            
            # Update bias snapshots after scan completion
            try:
                from shared.application.bias_snapshot_service import BiasSnapshotService
                snapshot_service = BiasSnapshotService(db_session)
                overall_snapshot, docset_snapshots = snapshot_service.calculate_and_save_today()
                if overall_snapshot:
                    self.logger.info(f"Updated bias snapshot for today: {overall_snapshot.bias_percentage}% bias ({overall_snapshot.biased_pages}/{overall_snapshot.total_pages} pages)")
                else:
                    self.logger.warning("Failed to create bias snapshot after scan completion")
            except Exception as e:
                self.logger.error(f"Error updating bias snapshot after scan {scan_id}: {e}", exc_info=True)
                # Don't fail the scan finalization if snapshot update fails
            
        except Exception as e:
            self.logger.error(f"Error finalizing scan {scan_id}: {e}")
    
    def start_consuming(self):
        """Start consuming document tasks from the queue"""
        self.logger.info("Document worker starting...")
        
        if not self.queue_service.connect():
            self.logger.error("Failed to connect to RabbitMQ")
            return
            
        try:
            self.logger.info("Starting to consume document tasks...")
            self.queue_service.consume_tasks(self.process_document_task, shutdown_event=self.shutdown_event)
            
        except Exception as e:
            self.logger.error(f"Error during document task consumption: {e}", exc_info=True)
            
        finally:
            self.logger.info("Document worker shutting down gracefully...")
            self.queue_service.disconnect()


def main():
    """Main entry point for the document worker"""
    logger = get_logger(__name__)
    try:
        logger.info("Starting document worker...")
        worker = DocumentWorker()
        worker.start_consuming()
        
    except Exception as e:
        logger.error(f"Fatal error in document worker: {e}", exc_info=True)


if __name__ == "__main__":
    main()