"""
ScanOrchestrator - Coordinates the complete scan workflow
This replaces the monolithic process_scan_task functionality
"""
import asyncio
import datetime
import time
from typing import Dict, List, Any, Optional
from sqlalchemy.orm import Session

from shared.models import Scan, Page, Snippet
from shared.config import config
from crawler_service import CrawlerService
from shared.infrastructure.github_service import GitHubService
from scoring_service import ScoringService
from shared.infrastructure.queue_service import QueueService
from shared.infrastructure.url_lock_service import url_lock_service
from shared.application.progress_tracker import progress_tracker
from shared.utils.metrics import get_metrics
from packages.extractor.parser import extract_code_snippets


class ScanOrchestrator:
    """Orchestrates the complete scan workflow for both web and GitHub scans"""
    
    def __init__(self, db_session: Session):
        self.db = db_session
        self.scoring_service = ScoringService()
        self.doc_queue_service = QueueService(queue_name='doc_processing')
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

    def process_web_scan(self, url: str, scan_id: int, force_rescan: bool = False) -> bool:
        """
        Process a web-based scan task
        
        Args:
            url: Starting URL for the scan
            scan_id: Database scan ID
            force_rescan: Whether to force rescan all documents regardless of changes
            
        Returns:
            True if successful, False otherwise
        """
        print(f"[DEBUG] Starting web scan pipeline for URL: {url}, scan_id: {scan_id}")
        
        # Record scan start
        self.metrics.record_scan_started('web', 'orchestrator')
        scan_start_time = time.time()
        
        # Get scan record
        scan = self.db.query(Scan).filter(Scan.id == scan_id).first()
        if not scan:
            print(f"[ERROR] Scan with ID {scan_id} not found")
            self.metrics.record_scan_completed('web', 'error', time.time() - scan_start_time)
            return False
            
        try:
            # Check for cancellation before starting
            if self._check_cancellation(scan_id):
                return False
                
            # Phase 1: Crawling and Document Discovery
            print(f"[INFO] Starting crawling phase for scan {scan_id}")
            progress_tracker.start_phase(self.db, scan_id, 'crawling', {
                'description': 'Discovering and crawling web pages',
                'target_url': url
            })
            
            crawled_results, page_objs = self._crawl_pages(url, scan, scan_id)
            if not crawled_results:
                progress_tracker.report_error(self.db, scan_id, "No pages crawled")
                self._mark_scan_error(scan, "No pages crawled")
                return False
                
            # Check for cancellation after crawling
            if self._check_cancellation(scan_id):
                return False
                
            progress_tracker.complete_phase(self.db, scan_id, 'crawling', {
                'pages_found': len(crawled_results),
                'pages_crawled': len(page_objs)
            })
                
            # Phase 2: Queue Documents for Processing
            print(f"[INFO] Starting document queuing phase for scan {scan_id}")
            progress_tracker.start_phase(self.db, scan_id, 'queuing', {
                'description': 'Queuing documents for parallel processing',
                'total_pages': len(crawled_results)
            })
            
            # Check for cancellation before queuing
            if self._check_cancellation(scan_id):
                return False
                
            queued_count, skipped_count = self._queue_web_documents(crawled_results, page_objs, scan_id, force_rescan)
            if queued_count == 0 and skipped_count == 0:
                # No documents found at all - this is an error
                progress_tracker.report_error(self.db, scan_id, "No documents queued for processing")
                self._mark_scan_error(scan, "No documents queued for processing")
                return False
            elif queued_count == 0 and skipped_count > 0:
                # All documents were skipped (no changes) - this is success
                print(f"[INFO] All {skipped_count} web documents were skipped (no changes detected). Scan completed successfully.")
                scan.status = 'done'
                scan.total_pages_found = skipped_count
                print(f"[DEBUG] Set total_pages_found to {skipped_count} (all skipped web documents)")
                scan.finished_at = datetime.datetime.now(datetime.timezone.utc)
                self.db.commit()
                
                progress_tracker.complete_phase(self.db, scan_id, 'queuing', {
                    'documents_queued': 0,
                    'documents_skipped': skipped_count,
                    'reason': 'no_changes_detected'
                })
                
                # Record successful scan completion
                self.metrics.record_scan_completed('web', 'completed_no_changes', time.time() - scan_start_time)
                return True
                
            progress_tracker.complete_phase(self.db, scan_id, 'queuing', {
                'documents_queued': queued_count,
                'documents_skipped': skipped_count
            })
            
            # Phase 3: Mark as queued for processing
            print(f"[INFO] Queued {queued_count} documents for processing. Scan will complete when all documents are processed.")
            scan.status = 'processing'
            scan.total_pages_found = queued_count
            print(f"[DEBUG] Set total_pages_found to {queued_count} (queued web documents)")
            self.db.commit()
            
            # Record successful scan initiation
            self.metrics.record_scan_completed('web', 'initiated', time.time() - scan_start_time)
            
            return True
            
        except Exception as e:
            print(f"[ERROR] Error during web scan: {e}")
            self._mark_scan_error(scan, f"Scan failed: {str(e)}")
            self.metrics.record_scan_completed('web', 'error', time.time() - scan_start_time)
            self.metrics.record_error('scan_orchestrator', type(e).__name__)
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
        self.metrics.record_scan_started('github', 'orchestrator')
        scan_start_time = time.time()
        
        # Get scan record
        scan = self.db.query(Scan).filter(Scan.id == scan_id).first()
        if not scan:
            print(f"[ERROR] Scan with ID {scan_id} not found")
            self.metrics.record_scan_completed('github', 'error', time.time() - scan_start_time)
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
                
            # Phase 1: GitHub File Discovery
            print(f"[INFO] Starting GitHub crawling phase for scan {scan_id}")
            progress_tracker.start_phase(self.db, scan_id, 'crawling', {
                'description': 'Fetching files from GitHub repository',
                'github_url': url
            })
            
            page_objs = self._discover_github_files(
                github_service, parsed_url, scan, scan_id
            )
            
            if not page_objs:
                progress_tracker.report_error(self.db, scan_id, "No files discovered from GitHub")
                return False
                
            # Check for cancellation after file discovery
            if self._check_cancellation(scan_id):
                return False
                
            progress_tracker.complete_phase(self.db, scan_id, 'crawling', {
                'files_discovered': len(page_objs)
            })
                
            # Phase 2: Queue Documents for Processing
            print(f"[INFO] Starting GitHub document queuing phase for scan {scan_id}")
            progress_tracker.start_phase(self.db, scan_id, 'queuing', {
                'description': 'Queuing GitHub documents for parallel processing',
                'total_files': len(page_objs)
            })
            
            # Check for cancellation before queuing
            if self._check_cancellation(scan_id):
                return False
            
            queued_count, skipped_count = self._queue_github_documents(
                github_service, parsed_url, page_objs, scan_id, force_rescan
            )
            
            if queued_count == 0 and skipped_count == 0:
                # No documents found at all - this is an error
                progress_tracker.report_error(self.db, scan_id, "No GitHub documents queued for processing")
                self._mark_scan_error(scan, "No GitHub documents queued for processing")
                return False
            elif queued_count == 0 and skipped_count > 0:
                # All documents were skipped (no changes) - this is success
                print(f"[INFO] All {skipped_count} GitHub documents were skipped (no changes detected). Scan completed successfully.")
                scan.status = 'done'
                scan.total_pages_found = skipped_count
                print(f"[DEBUG] Set total_pages_found to {skipped_count} (all skipped GitHub documents)")
                scan.finished_at = datetime.datetime.now(datetime.timezone.utc)
                self.db.commit()
                
                progress_tracker.complete_phase(self.db, scan_id, 'queuing', {
                    'documents_queued': 0,
                    'documents_skipped': skipped_count,
                    'reason': 'no_changes_detected'
                })
                
                # Record successful scan completion
                self.metrics.record_scan_completed('github', 'completed_no_changes', time.time() - scan_start_time)
                return True
                
            progress_tracker.complete_phase(self.db, scan_id, 'queuing', {
                'documents_queued': queued_count,
                'documents_skipped': skipped_count
            })
            
            # Phase 3: Mark as queued for processing
            print(f"[INFO] Queued {queued_count} GitHub documents for processing. Scan will complete when all documents are processed.")
            scan.status = 'processing'
            scan.total_pages_found = queued_count
            print(f"[DEBUG] Set total_pages_found to {queued_count} (queued GitHub documents)")
            self.db.commit()
            
            # Record successful scan initiation
            self.metrics.record_scan_completed('github', 'initiated', time.time() - scan_start_time)
            
            return True
            
        except Exception as e:
            print(f"[ERROR] Error during GitHub scan: {e}")
            self._mark_scan_error(scan, f"GitHub scan failed: {str(e)}")
            self.metrics.record_scan_completed('github', 'error', time.time() - scan_start_time)
            self.metrics.record_error('scan_orchestrator', type(e).__name__)
            return False

    def _crawl_pages(self, url: str, scan: Scan, scan_id: int) -> tuple:
        """Crawl web pages and create page records with progress reporting"""
        crawler = CrawlerService(url)
        # Run async crawl method in sync context
        crawled_results = asyncio.run(crawler.crawl(config.application.max_pages))
        
        page_objs = {}
        processed_count = 0
        total_pages = len(crawled_results)
        
        for page_url, html in crawled_results.items():
            page_obj = Page(scan_id=scan.id, url=page_url, status='crawled')
            self.db.add(page_obj)
            self.db.commit()
            page_objs[page_url] = page_obj
            
            processed_count += 1
            # Report progress for each page processed
            progress_tracker.update_phase_progress(
                self.db, scan_id, 
                items_processed=processed_count,
                items_total=total_pages,
                current_item=page_url,
                details={'phase': 'crawling'}
            )
            
        print(f"[INFO] Crawled {len(crawled_results)} pages.")
        return crawled_results, page_objs

    def _queue_web_documents(self, crawled_results: Dict, page_objs: Dict, scan_id: int, force_rescan: bool = False) -> int:
        """Queue web documents for processing by DocumentWorkers with change detection"""
        if not self.doc_queue_service.connect():
            print(f"[ERROR] Failed to connect to document processing queue")
            return 0
            
        crawler = CrawlerService(base_url="")  # We don't need base_url for change detection
        queued_count = 0
        skipped_count = 0
        processed_count = 0
        total_pages = len(crawled_results)
        
        try:
            for page_url, html_content in crawled_results.items():
                page_obj = page_objs.get(page_url)
                if not page_obj:
                    continue
                
                # Check if document needs processing (change detection)
                should_process = force_rescan
                
                if not force_rescan:
                    # Check for existing page with same URL from previous scans
                    existing_page = self.db.query(Page).filter(
                        Page.url == page_url,
                        Page.scan_id != scan_id,
                        Page.content_hash.isnot(None)
                    ).order_by(Page.last_scanned_at.desc()).first()
                    
                    if existing_page:
                        # Compare content hashes
                        new_hash = crawler.calculate_content_hash(html_content)
                        if existing_page.content_hash != new_hash:
                            should_process = True
                            print(f"[DEBUG] Content changed for {page_url}, will process")
                        else:
                            print(f"[DEBUG] No change detected for {page_url}, skipping")
                            skipped_count += 1
                    else:
                        # New page, always process
                        should_process = True
                        print(f"[DEBUG] New page {page_url}, will process")
                
                if should_process:
                    # Update page with change detection metadata
                    import datetime
                    page_obj.content_hash = crawler.calculate_content_hash(html_content)
                    page_obj.last_scanned_at = datetime.datetime.now(datetime.timezone.utc)
                    
                    # Try to acquire URL processing lock
                    lock_acquired, lock_reason = url_lock_service.acquire_url_lock(
                        self.db, page_url, page_obj.content_hash, scan_id
                    )
                    
                    if lock_acquired:
                        # Create document processing task
                        task_data = {
                            'page_id': page_obj.id,
                            'scan_id': scan_id,
                            'url': page_url,
                            'source': 'web',
                            'html_content': html_content
                        }
                        
                        # Queue the document for processing
                        if self.doc_queue_service.publish_task(task_data):
                            queued_count += 1
                            page_obj.status = 'queued'
                            self.db.commit()
                            
                            # Record queue metrics
                            self.metrics.record_queue_task_published('doc_processing')
                        else:
                            # Failed to queue, release the lock
                            url_lock_service.release_url_lock(
                                self.db, page_url, page_obj.content_hash, scan_id, success=False
                            )
                            page_obj.status = 'queue_failed'
                            self.db.commit()
                    else:
                        # Could not acquire lock, mark as skipped
                        page_obj.status = 'skipped_locked'
                        skipped_count += 1
                        self.db.commit()
                        print(f"[DEBUG] Skipping {page_url}: {lock_reason}")
                else:
                    # Mark as skipped due to no changes
                    page_obj.status = 'skipped_no_change'
                    self.db.commit()
                    
                processed_count += 1
                # Report progress for each page processed
                progress_tracker.update_phase_progress(
                    self.db, scan_id,
                    items_processed=processed_count,
                    items_total=total_pages,
                    current_item=page_url,
                    details={
                        'phase': 'queuing', 
                        'queued_count': queued_count, 
                        'skipped_count': skipped_count,
                        'force_rescan': force_rescan
                    }
                )
                
        except Exception as e:
            print(f"[ERROR] Error queuing documents: {e}")
            
        finally:
            self.doc_queue_service.disconnect()
            
        print(f"[INFO] Queued {queued_count} documents for processing, skipped {skipped_count} unchanged documents.")
        return queued_count, skipped_count

    def _discover_github_files(
        self, github_service: GitHubService, parsed_url: Dict, scan: Scan, scan_id: int
    ) -> Dict:
        """Discover GitHub markdown files and create Page records"""
        repo_full_name = parsed_url['repo_full_name']
        branch = parsed_url['branch']
        path = parsed_url['path']
        
        # Get markdown files
        progress_file = f"github_scan_progress_{scan_id}.json"
        md_files = github_service.list_markdown_files(
            repo_full_name, path, branch, 
            max_files=config.application.max_pages,
            progress_file=progress_file
        )
        
        print(f"[INFO] Found {len(md_files)} markdown files in repo.")
        
        page_objs = {}
        processed_count = 0
        
        for md_file in md_files:
            page_url = github_service.generate_github_url(
                repo_full_name, branch, md_file['path']
            )
            
            if github_service.is_windows_focused_url(page_url):
                print(f"[DEBUG] Skipping Windows-focused file: {page_url}")
                continue
                
            # Create page record
            page_obj = Page(scan_id=scan.id, url=page_url, status='discovered')
            self.db.add(page_obj)
            self.db.commit()
            page_objs[md_file['path']] = page_obj
            
            processed_count += 1
            # Report progress for each file discovered
            progress_tracker.update_phase_progress(
                self.db, scan_id,
                items_processed=processed_count,
                items_total=len(md_files),
                current_item=page_url,
                details={'phase': 'crawling', 'files_discovered': len(page_objs)}
            )
            
        return page_objs

    def _queue_github_documents(
        self, github_service: GitHubService, parsed_url: Dict, page_objs: Dict, scan_id: int, force_rescan: bool = False
    ) -> int:
        """Queue GitHub documents for processing by DocumentWorkers with change detection"""
        repo_full_name = parsed_url['repo_full_name']
        branch = parsed_url['branch']
        
        if not self.doc_queue_service.connect():
            print(f"[ERROR] Failed to connect to document processing queue")
            return 0
            
        queued_count = 0
        skipped_count = 0
        processed_count = 0
        total_files = len(page_objs)
        
        try:
            for file_path, page_obj in page_objs.items():
                # Get file content
                file_content = github_service.get_file_content(
                    repo_full_name, file_path, branch
                )
                
                if not file_content:
                    continue
                    
                if github_service.is_windows_focused_content(file_content):
                    continue
                
                # Check if document needs processing (change detection)
                should_process = force_rescan
                
                if not force_rescan:
                    # Get file metadata for change detection
                    file_metadata = github_service.get_file_metadata(repo_full_name, file_path, branch)
                    if file_metadata:
                        # Check for existing page with same URL from previous scans
                        existing_page = self.db.query(Page).filter(
                            Page.url == page_obj.url,
                            Page.scan_id != scan_id,
                            Page.github_sha.isnot(None)
                        ).order_by(Page.last_scanned_at.desc()).first()
                        
                        if existing_page:
                            # Compare GitHub file SHAs
                            if existing_page.github_sha != file_metadata['sha']:
                                should_process = True
                                print(f"[DEBUG] GitHub file changed for {page_obj.url}, will process")
                            else:
                                print(f"[DEBUG] No change detected for {page_obj.url}, skipping")
                                skipped_count += 1
                        else:
                            # New file, always process
                            should_process = True
                            print(f"[DEBUG] New GitHub file {page_obj.url}, will process")
                    else:
                        # Could not get metadata, process to be safe
                        should_process = True
                        print(f"[DEBUG] Could not get metadata for {page_obj.url}, will process")
                
                if should_process:
                    # Update page with change detection metadata
                    import datetime
                    import hashlib
                    file_metadata = github_service.get_file_metadata(repo_full_name, file_path, branch)
                    if file_metadata:
                        page_obj.github_sha = file_metadata['sha']
                        if file_metadata.get('last_modified'):
                            from datetime import datetime as dt
                            page_obj.last_modified = dt.fromisoformat(file_metadata['last_modified'].replace('Z', '+00:00'))
                    
                    # Calculate content hash for file content
                    page_obj.content_hash = hashlib.sha256(file_content.encode('utf-8')).hexdigest()
                    page_obj.last_scanned_at = datetime.datetime.now(datetime.timezone.utc)
                    
                    # Try to acquire URL processing lock
                    lock_acquired, lock_reason = url_lock_service.acquire_url_lock(
                        self.db, page_obj.url, page_obj.content_hash, scan_id
                    )
                    
                    if lock_acquired:
                        # Create document processing task
                        task_data = {
                            'page_id': page_obj.id,
                            'scan_id': scan_id,
                            'url': page_obj.url,
                            'source': 'github',
                            'file_content': file_content
                        }
                        
                        # Queue the document for processing
                        if self.doc_queue_service.publish_task(task_data):
                            queued_count += 1
                            page_obj.status = 'queued'
                            self.db.commit()
                            
                            # Record queue metrics
                            self.metrics.record_queue_task_published('doc_processing')
                        else:
                            # Failed to queue, release the lock
                            url_lock_service.release_url_lock(
                                self.db, page_obj.url, page_obj.content_hash, scan_id, success=False
                            )
                            page_obj.status = 'queue_failed'
                            self.db.commit()
                    else:
                        # Could not acquire lock, mark as skipped
                        page_obj.status = 'skipped_locked'
                        skipped_count += 1
                        self.db.commit()
                        print(f"[DEBUG] Skipping {page_obj.url}: {lock_reason}")
                else:
                    # Mark as skipped due to no changes
                    page_obj.status = 'skipped_no_change'
                    self.db.commit()
                    
                processed_count += 1
                # Report progress for each file processed
                progress_tracker.update_phase_progress(
                    self.db, scan_id,
                    items_processed=processed_count,
                    items_total=total_files,
                    current_item=page_obj.url,
                    details={
                        'phase': 'queuing', 
                        'queued_count': queued_count, 
                        'skipped_count': skipped_count,
                        'force_rescan': force_rescan
                    }
                )
                
        except Exception as e:
            print(f"[ERROR] Error queuing GitHub documents: {e}")
            
        finally:
            self.doc_queue_service.disconnect()
            
        print(f"[INFO] Queued {queued_count} GitHub documents for processing, skipped {skipped_count} unchanged documents.")
        return queued_count, skipped_count

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

    def _process_github_files(
        self, github_service: GitHubService, parsed_url: Dict, scan: Scan, scan_id: int
    ) -> tuple:
        """Process GitHub markdown files and extract snippets"""
        repo_full_name = parsed_url['repo_full_name']
        branch = parsed_url['branch']
        path = parsed_url['path']
        
        # Get markdown files
        progress_file = f"github_scan_progress_{scan_id}.json"
        md_files = github_service.list_markdown_files(
            repo_full_name, path, branch, 
            max_files=config.application.max_pages,
            progress_file=progress_file
        )
        
        print(f"[INFO] Found {len(md_files)} markdown files in repo.")
        
        page_objs = {}
        all_snippets = []
        processed_count = 0
        
        for md_file in md_files:
            page_url = github_service.generate_github_url(
                repo_full_name, branch, md_file['path']
            )
            
            if github_service.is_windows_focused_url(page_url):
                print(f"[DEBUG] Skipping Windows-focused file: {page_url}")
                continue
                
            # Get file content
            file_content = github_service.get_file_content(
                repo_full_name, md_file['path'], branch
            )
            
            if not file_content:
                continue
                
            if github_service.is_windows_focused_content(file_content):
                continue
                
            # Create page record
            page_obj = Page(scan_id=scan.id, url=page_url, status='crawled')
            self.db.add(page_obj)
            self.db.commit()
            page_objs[md_file['path']] = page_obj
            
            # Extract code blocks
            code_blocks = github_service.extract_code_blocks(file_content)
            print(f"[DEBUG] {md_file['path']}: {len(code_blocks)} code blocks extracted.")
            
            for code in code_blocks:
                snippet = Snippet(
                    page_id=page_obj.id,
                    context='',
                    code=code,
                    llm_score=None
                )
                self.db.add(snippet)
                all_snippets.append({
                    'code': code,
                    'context': '',
                    'url': page_url,
                    'snippet_obj': snippet
                })
                
            self.db.commit()
            
            processed_count += 1
            # Report progress for each file processed
            progress_tracker.update_phase_progress(
                self.db, scan_id,
                items_processed=processed_count,
                items_total=len(md_files),
                current_item=page_url,
                details={'phase': 'crawling', 'snippets_in_file': len(code_blocks)}
            )
            
        return page_objs, all_snippets

    def _score_github_snippets(self, scan_id: int, snippets: List[Dict]):
        """Score GitHub snippets with LLM and progress reporting"""
        scored_snippets = self.scoring_service.apply_llm_scoring(snippets)
        
        processed_count = 0
        for snip in scored_snippets:
            snippet_obj = snip.get('snippet_obj')
            if snippet_obj and 'llm_score' in snip:
                snippet_obj.llm_score = snip['llm_score']
                self.db.commit()
                
                processed_count += 1
                # Report progress for snippet scoring
                progress_tracker.update_phase_progress(
                    self.db, scan_id,
                    items_processed=processed_count,
                    items_total=len(snippets),
                    current_item=f"Scoring snippet from {snippet_obj.page.url if snippet_obj.page else 'unknown'}",
                    details={'phase': 'scoring'}
                )

    def _score_github_pages_holistically(
        self, scan_id: int, github_service: GitHubService, parsed_url: Dict, page_objs: Dict
    ):
        """Apply holistic MCP scoring to GitHub pages"""
        repo_full_name = parsed_url['repo_full_name']
        branch = parsed_url['branch']
        
        for file_path, page_obj in page_objs.items():
            file_content = github_service.get_file_content(
                repo_full_name, file_path, branch
            )
            
            if file_content:
                page_url = github_service.generate_github_url(
                    repo_full_name, branch, file_path
                )
                mcp_result = self.scoring_service.apply_mcp_holistic_scoring(
                    file_content, page_url
                )
                
                if mcp_result and page_obj:
                    page_obj.mcp_holistic = mcp_result
                    self.db.commit()

    def _finalize_scan(self, scan: Scan, snippets: List[Dict]):
        """Finalize web scan with metrics"""
        metrics = self.scoring_service.get_bias_metrics(snippets)
        
        scan.status = 'done'
        scan.finished_at = datetime.datetime.utcnow()
        scan.biased_pages_count = metrics['biased_pages_count']
        scan.flagged_snippets_count = metrics['flagged_snippets_count']
        self.db.commit()
        
        print(f"[INFO] Web scan completed. Metrics: {metrics}")

    def _finalize_github_scan(self, scan: Scan, snippets: List[Dict]):
        """Finalize GitHub scan with metrics"""
        # Convert snippet objects to format expected by get_bias_metrics
        snippet_dicts = []
        for snip in snippets:
            snippet_obj = snip.get('snippet_obj')
            if snippet_obj and snippet_obj.llm_score:
                snippet_dicts.append({
                    'url': snip['url'],
                    'llm_score': snippet_obj.llm_score
                })
                
        metrics = self.scoring_service.get_bias_metrics(snippet_dicts)
        
        scan.status = 'done'
        scan.finished_at = datetime.datetime.now(datetime.timezone.utc)
        scan.biased_pages_count = metrics['biased_pages_count']
        scan.flagged_snippets_count = metrics['flagged_snippets_count']
        self.db.commit()
        
        print(f"[INFO] GitHub scan completed. Metrics: {metrics}")

    def _mark_scan_error(self, scan: Scan, error_message: str):
        """Mark scan as failed with error message"""
        scan.status = 'error'
        scan.finished_at = datetime.datetime.utcnow()
        self.db.commit()
        print(f"[ERROR] {error_message}")