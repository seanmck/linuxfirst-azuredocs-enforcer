"""
DocumentWorker - Handles processing of individual documents from the doc_processing queue
This enables horizontal scaling based on document count rather than scan task count
"""
import sys
import os
import time
from typing import Dict, Any, List, Optional

# Add the project root to the Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, project_root)

from sqlalchemy.orm import Session
from src.shared.models import Scan, Page, Snippet
from src.shared.config import config
from src.infrastructure.queue_service import QueueService
from src.infrastructure.scoring_service import ScoringService
from src.infrastructure.github_service import GitHubService
from src.application.progress_service import progress_service
from src.shared.utils.database import SessionLocal
from src.shared.utils.logging import get_logger
from src.shared.utils.metrics import get_metrics
from extractor.parser import extract_code_snippets


class DocumentWorker:
    """Worker that processes individual documents from the doc_processing queue"""
    
    def __init__(self):
        self.queue_service = QueueService(queue_name='doc_processing')
        self.scoring_service = ScoringService()
        self.github_service = GitHubService()
        self.logger = get_logger(__name__)
        self.metrics = get_metrics()

    def process_document_task(self, task_data: Dict[str, Any]) -> bool:
        """
        Process a single document task from the queue
        
        Args:
            task_data: Dictionary containing document processing information
            
        Returns:
            True if successful, False otherwise
        """
        page_id = task_data.get('page_id')
        scan_id = task_data.get('scan_id')
        url = task_data.get('url')
        source = task_data.get('source', 'web')
        
        self.logger.info(f"Processing document: {url} (page_id: {page_id}, scan_id: {scan_id}, source: {source})")
        
        # Record queue task processing start
        processing_start_time = time.time()
        
        # Create database session
        db_session = SessionLocal()
        
        try:
            # Get page record
            page = db_session.query(Page).filter(Page.id == page_id).first()
            if not page:
                self.logger.error(f"Page with ID {page_id} not found")
                return False
                
            # Process based on source type
            if source == 'github':
                success = self._process_github_document(db_session, page, task_data)
            else:
                success = self._process_web_document(db_session, page, task_data)
                
            if success:
                # Mark page as processed
                page.status = 'processed'
                db_session.commit()
                self.logger.info(f"Successfully processed document: {url}")
                
                # Record successful processing metrics
                self.metrics.record_queue_task_processed('doc_processing', 'success', time.time() - processing_start_time)
                
                # Check if all documents for this scan are complete
                self._check_scan_completion(db_session, scan_id)
            else:
                page.status = 'error'
                db_session.commit()
                self.logger.error(f"Failed to process document: {url}")
                
                # Record failed processing metrics
                self.metrics.record_queue_task_processed('doc_processing', 'error', time.time() - processing_start_time)
                
            return success
            
        except Exception as e:
            self.logger.error(f"Unexpected error processing document {url}: {e}", exc_info=True)
            return False
            
        finally:
            db_session.close()

    def _process_web_document(self, db_session: Session, page: Page, task_data: Dict[str, Any]) -> bool:
        """
        Process a web document (extract snippets, score, and holistic analysis)
        
        Args:
            db_session: Database session
            page: Page record
            task_data: Task data containing HTML content
            
        Returns:
            True if successful, False otherwise
        """
        try:
            html_content = task_data.get('html_content')
            scan_id = task_data.get('scan_id')
            url = page.url
            
            if not html_content:
                self.logger.error(f"No HTML content provided for {url}")
                return False
                
            # Extract code snippets
            snippets = extract_code_snippets(html_content)
            all_snippets = []
            
            for snip in snippets:
                snip['url'] = url
                snippet_obj = Snippet(
                    page_id=page.id,
                    context=snip['context'],
                    code=snip['code']
                )
                db_session.add(snippet_obj)
                db_session.commit()
                all_snippets.append(snip)
                
            self.logger.info(f"Extracted {len(all_snippets)} snippets from {url}")
            
            # Score snippets if any found
            if all_snippets:
                # Record snippet analysis metrics
                for _ in all_snippets:
                    self.metrics.record_snippet_analyzed('heuristic')
                    
                self._score_snippets(db_session, all_snippets, scan_id)
                
            # Apply holistic MCP scoring
            self._apply_holistic_scoring(db_session, page, html_content, scan_id)
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error processing web document {page.url}: {e}", exc_info=True)
            return False

    def _process_github_document(self, db_session: Session, page: Page, task_data: Dict[str, Any]) -> bool:
        """
        Process a GitHub document (extract code blocks, score, and holistic analysis)
        
        Args:
            db_session: Database session
            page: Page record
            task_data: Task data containing GitHub file information
            
        Returns:
            True if successful, False otherwise
        """
        try:
            file_content = task_data.get('file_content')
            scan_id = task_data.get('scan_id')
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
            
            # Score snippets if any found
            if all_snippets:
                self._score_github_snippets(db_session, all_snippets, scan_id)
                
            # Apply holistic MCP scoring
            self._apply_holistic_scoring(db_session, page, file_content, scan_id)
            
            return True
            
        except Exception as e:
            self.logger.error(f"Error processing GitHub document {page.url}: {e}", exc_info=True)
            return False

    def _score_snippets(self, db_session: Session, snippets: List[Dict], scan_id: int):
        """Score web snippets using heuristic and LLM scoring"""
        try:
            # Apply heuristic filtering first
            flagged_snippets = self.scoring_service.apply_heuristic_scoring(snippets)
            if not flagged_snippets:
                flagged_snippets = snippets  # If no heuristic flags, score all
                
            # Score each snippet
            for snip in flagged_snippets:
                # Record that we're analyzing with LLM
                self.metrics.record_snippet_analyzed('llm')
                
                snip['llm_score'] = self.scoring_service.llm_client.score_snippet(snip)
                
                # Update database
                snippet_obj = db_session.query(Snippet).join(Page).filter(
                    Page.url == snip['url'],
                    Snippet.code == snip['code']
                ).first()
                
                if snippet_obj:
                    snippet_obj.llm_score = snip['llm_score']
                    db_session.commit()
                    
                    # Check if bias was detected and report result
                    if snip['llm_score'].get('windows_biased'):
                        # Record bias detection
                        self.metrics.record_bias_detected('llm', 'windows')
                        
                        progress_service.report_page_result(
                            db_session, scan_id, snip['url'], True, snip['llm_score']
                        )
                        
        except Exception as e:
            self.logger.error(f"Error scoring snippets: {e}", exc_info=True)

    def _score_github_snippets(self, db_session: Session, snippets: List[Dict], scan_id: int):
        """Score GitHub snippets using LLM scoring"""
        try:
            scored_snippets = self.scoring_service.apply_llm_scoring(snippets)
            
            for snip in scored_snippets:
                snippet_obj = snip.get('snippet_obj')
                if snippet_obj and 'llm_score' in snip:
                    snippet_obj.llm_score = snip['llm_score']
                    db_session.commit()
                    
        except Exception as e:
            self.logger.error(f"Error scoring GitHub snippets: {e}", exc_info=True)

    def _apply_holistic_scoring(self, db_session: Session, page: Page, content: str, scan_id: int):
        """Apply holistic MCP scoring to the page"""
        try:
            mcp_result = self.scoring_service.apply_mcp_holistic_scoring(content, page.url)
            if mcp_result:
                page.mcp_holistic = mcp_result
                db_session.commit()
                
                # Check if bias was detected and report result
                if mcp_result.get('bias_types'):
                    progress_service.report_page_result(
                        db_session, scan_id, page.url, True, mcp_result
                    )
                    
        except Exception as e:
            self.logger.error(f"Error applying holistic scoring to {page.url}: {e}", exc_info=True)

    def _check_scan_completion(self, db_session: Session, scan_id: int):
        """Check if all documents for a scan have been processed and finalize if complete"""
        try:
            # Get scan record
            scan = db_session.query(Scan).filter(Scan.id == scan_id).first()
            if not scan or scan.status != 'processing':
                return
                
            # Count processed and error pages
            processed_count = db_session.query(Page).filter(
                Page.scan_id == scan_id,
                Page.status.in_(['processed', 'error'])
            ).count()
            
            # Check if all expected pages are processed
            if processed_count >= scan.total_pages_found:
                self._finalize_scan(db_session, scan)
                self.logger.info(f"Scan {scan_id} completed with {processed_count} documents processed")
                
        except Exception as e:
            self.logger.error(f"Error checking scan completion for scan {scan_id}: {e}", exc_info=True)

    def _finalize_scan(self, db_session: Session, scan: Scan):
        """Finalize a completed scan with metrics"""
        try:
            import datetime
            
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
            
            # Update scan record
            scan.status = 'done'
            scan.finished_at = datetime.datetime.now(datetime.timezone.utc)
            scan.biased_pages_count = biased_pages_count
            scan.flagged_snippets_count = flagged_snippets_count
            db_session.commit()
            
            self.logger.info(f"Finalized scan {scan.id}: {processed_pages} processed, {error_pages} errors, {biased_pages_count} biased pages, {flagged_snippets_count} flagged snippets")
            
        except Exception as e:
            self.logger.error(f"Error finalizing scan {scan.id}: {e}", exc_info=True)

    def start_consuming(self):
        """Start consuming document tasks from the queue"""
        self.logger.info("Document worker starting...")
        
        if not self.queue_service.connect():
            self.logger.error("Failed to connect to RabbitMQ")
            return
            
        try:
            self.logger.info("Starting to consume document tasks...")
            self.queue_service.consume_tasks(self.process_document_task)
            
        except Exception as e:
            self.logger.error(f"Error during document task consumption: {e}", exc_info=True)
            
        finally:
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