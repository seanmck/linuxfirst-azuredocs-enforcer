"""
ScanOrchestrator - Coordinates the complete scan workflow
This replaces the monolithic process_scan_task functionality
"""
import datetime
import time
from typing import Dict, List, Any, Optional
from sqlalchemy.orm import Session

from shared.models import Scan, Page, Snippet
from shared.config import config
from shared.infrastructure.github_service import GitHubService
from github_discovery_service import GitHubDiscoveryService
from scoring_service import ScoringService
from shared.infrastructure.queue_service import QueueService
from shared.infrastructure.url_lock_service import url_lock_service
from shared.application.progress_tracker import progress_tracker
from shared.utils.metrics import get_metrics
from packages.extractor.parser import extract_code_snippets


class ScanOrchestrator:
    """Orchestrates the complete scan workflow for GitHub scans"""
    
    def __init__(self, db_session: Session):
        self.db = db_session
        self.scoring_service = ScoringService()
        self.doc_queue_service = QueueService(queue_name='doc_processing')
        self.discovery_service = GitHubDiscoveryService(db_session)
        # Note: Using progress_tracker directly instead of progress_service to avoid FastAPI dependency
        self.metrics = get_metrics()

    def _check_cancellation(self, scan_id: int) -> bool:
        """
        Check if scan has been cancelled
        
        Args:
            scan_id: The scan ID to check
            
        Returns:
            True if scan is cancelled, False otherwise
        """
        try:
            scan = self.db.query(Scan).filter(Scan.id == scan_id).first()
            if scan and scan.cancellation_requested:
                print(f"[INFO] Scan {scan_id} has been cancelled, stopping processing")
                return True
            return False
        except Exception as e:
            print(f"[ERROR] Error checking cancellation status: {e}")
            return False


    def process_github_scan(self, url: str, scan_id: int, force_rescan: bool = False) -> bool:
        """
        Process a GitHub repository scan task
        
        Args:
            url: GitHub repository URL
            scan_id: Database scan ID
            force_rescan: Whether to force rescan all documents regardless of changes
            
        Returns:
            True if successful, False otherwise
        """
        print(f"[DEBUG] Starting GitHub scan pipeline for repo: {url}, scan_id: {scan_id}")
        
        # Record scan start
        self.metrics.record_scan_started('orchestrator')
        scan_start_time = time.time()
        
        # Get scan record
        scan = self.db.query(Scan).filter(Scan.id == scan_id).first()
        if not scan:
            print(f"[ERROR] Scan with ID {scan_id} not found")
            self.metrics.record_scan_completed('error', time.time() - scan_start_time)
            return False
            
        try:
            # Check for cancellation before starting
            if self._check_cancellation(scan_id):
                return False
                
            github_service = GitHubService()
            
            # Parse GitHub URL
            parsed_url = github_service.parse_github_url(url)
            if not parsed_url:
                self._mark_scan_error(scan, f"Could not parse GitHub repo from URL: {url}")
                return False
                
            # Phase 1: GitHub File Discovery using optimized discovery service
            print(f"[INFO] Starting GitHub discovery phase for scan {scan_id}")
            progress_tracker.start_phase(self.db, scan_id, 'discovery', {
                'description': 'Discovering changed files using GitHub APIs',
                'github_url': url
            })
            
            files_queued = self.discovery_service.discover_changes(url, scan_id, force_rescan)
            
            if files_queued == 0:
                # No files queued - could be no changes or error
                # Check if this is a "no changes" scenario
                if not force_rescan:
                    print(f"[INFO] No files queued for processing - likely no changes detected since last scan")
                    scan.status = 'completed'
                    scan.total_files_discovered = 0
                    scan.total_files_queued = 0
                    scan.total_files_completed = 0
                    scan.finished_at = datetime.datetime.now(datetime.timezone.utc)
                    self.db.commit()
                    
                    progress_tracker.complete_phase(self.db, scan_id, 'discovery', {
                        'files_discovered': 0,
                        'files_queued': 0,
                        'reason': 'no_changes_detected'
                    })
                    
                    # Record successful scan completion
                    self.metrics.record_scan_completed('completed_no_changes', time.time() - scan_start_time)
                    return True
                else:
                    # Forced rescan but no files found - this is an error
                    progress_tracker.report_error(self.db, scan_id, "No files discovered from GitHub repository")
                    self._mark_scan_error(scan, "No files discovered from GitHub repository")
                    return False
                    
            # Check for cancellation after discovery
            if self._check_cancellation(scan_id):
                return False
                
            progress_tracker.complete_phase(self.db, scan_id, 'discovery', {
                'files_discovered': files_queued,
                'files_queued': files_queued
            })
            
            # Phase 2: Mark as queued for processing
            print(f"[INFO] Queued {files_queued} GitHub files for processing. Scan will complete when all files are processed.")
            scan.total_files_discovered = files_queued
            scan.total_files_queued = files_queued
            scan.total_files_completed = 0
            self.db.commit()
            
            # Record successful scan initiation
            self.metrics.record_scan_completed('initiated', time.time() - scan_start_time)
            
            return True
            
        except Exception as e:
            print(f"[ERROR] Error during GitHub scan: {e}")
            self._mark_scan_error(scan, f"GitHub scan failed: {str(e)}")
            self.metrics.record_scan_completed('error', time.time() - scan_start_time)
            self.metrics.record_error('scan_orchestrator', type(e).__name__)
            return False





    def _extract_snippets_from_pages(self, crawled_results: Dict, page_objs: Dict, scan_id: int) -> List[Dict]:
        """Extract code snippets from crawled pages with progress reporting"""
        all_snippets = []
        processed_count = 0
        total_pages = len(crawled_results)
        
        for page_url, html in crawled_results.items():
            snippets = extract_code_snippets(html)
            page_obj = page_objs.get(page_url)
            
            for snip in snippets:
                snip['url'] = page_url
                snippet_obj = Snippet(
                    page_id=page_obj.id,
                    context=snip['context'],
                    code=snip['code']
                )
                self.db.add(snippet_obj)
                self.db.commit()
                all_snippets.append(snip)
                
            processed_count += 1
            # Report progress for each page processed
            progress_tracker.update_phase_progress(
                self.db, scan_id,
                items_processed=processed_count,
                items_total=total_pages,
                current_item=page_url,
                details={
                    'phase': 'extracting',
                    'snippets_found': len(snippets),
                    'total_snippets_so_far': len(all_snippets)
                }
            )
                
        print(f"[INFO] Extracted {len(all_snippets)} code snippets.")
        return all_snippets

    def _score_snippets(self, snippets: List[Dict], scan_id: int):
        """Apply scoring to snippets and update database with progress reporting"""
        processed_count = 0
        total_snippets = len(snippets)
        
        # Apply heuristic filtering first
        flagged_snippets = self.scoring_service.apply_heuristic_scoring(snippets)
        if not flagged_snippets:
            flagged_snippets = snippets  # If no heuristic flags, score all
            
        # Score each snippet individually to report progress
        for snip in flagged_snippets:
            # Score the snippet
            snip['llm_score'] = self.scoring_service.llm_client.score_snippet(snip)
            
            # Update database
            snippet_obj = self.db.query(Snippet).join(Page).filter(
                Page.url == snip['url'],
                Snippet.code == snip['code']
            ).first()
            
            if snippet_obj:
                snippet_obj.llm_score = snip['llm_score']
                self.db.commit()
                
                # Check if bias was detected and report result
                if snip['llm_score'].get('windows_biased'):
                    progress_tracker.report_page_result(
                        self.db, scan_id, snip['url'], True, snip['llm_score']
                    )
            
            processed_count += 1
            # Report progress
            progress_tracker.update_phase_progress(
                self.db, scan_id,
                items_processed=processed_count,
                items_total=len(flagged_snippets),
                current_item=f"Snippet from {snip['url']}",
                details={
                    'phase': 'scoring',
                    'total_snippets': total_snippets,
                    'flagged_snippets': len(flagged_snippets)
                }
            )

    def _score_pages_holistically(self, crawled_results: Dict, page_objs: Dict, scan_id: int):
        """Apply holistic MCP scoring to pages with progress reporting"""
        processed_count = 0
        total_pages = len(page_objs)
        
        for page_url, page_obj in page_objs.items():
            html = crawled_results.get(page_url)
            if html:
                mcp_result = self.scoring_service.apply_mcp_holistic_scoring(html, page_url)
                if mcp_result and page_obj:
                    page_obj.mcp_holistic = mcp_result
                    self.db.commit()
                    
                    # Check if bias was detected and report result
                    if mcp_result.get('bias_types'):
                        progress_tracker.report_page_result(
                            self.db, scan_id, page_url, True, mcp_result
                        )
            
            processed_count += 1
            # Report progress
            progress_tracker.update_phase_progress(
                self.db, scan_id,
                items_processed=processed_count,
                items_total=total_pages,
                current_item=page_url,
                details={
                    'phase': 'mcp_holistic',
                    'pages_analyzed': processed_count
                }
            )






    def _mark_scan_error(self, scan: Scan, error_message: str):
        """Mark scan as failed with error message"""
        scan.status = 'error'
        scan.finished_at = datetime.datetime.now(datetime.timezone.utc)
        self.db.commit()
        print(f"[ERROR] {error_message}")