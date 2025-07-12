"""
GitHubDiscoveryService - Optimized file discovery using GitHub APIs exclusively

This service replaces the inefficient file-by-file discovery approach with:
- GitHub Compare API for incremental scans (1 API call vs 10,000+)
- GitHub Trees API for initial scans (1-3 API calls vs 10,000+)
- Baseline management for recovery scenarios
"""
import time
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum

from shared.infrastructure.github_service import GitHubService
from shared.infrastructure.queue_service import QueueService
from shared.utils.logging import get_logger
from shared.utils.metrics import get_metrics
from shared.models import Scan, Page, FileProcessingHistory
from shared.application.processing_history_service import ProcessingHistoryService
from sqlalchemy.orm import Session


class BaselineType(Enum):
    """Types of baselines for incremental scanning"""
    COMPLETE = "complete"
    PARTIAL = "partial"
    NONE = "none"


@dataclass
class BaselineInfo:
    """Information about a baseline for incremental scanning"""
    type: BaselineType
    commit_sha: Optional[str] = None
    scan_id: Optional[int] = None
    file_map: Optional[Dict[str, str]] = None  # file_path -> sha
    scan_ids: Optional[List[int]] = None
    reason: Optional[str] = None
    coverage: float = 0.0
    age: Optional[timedelta] = None


class GitHubDiscoveryService:
    """Optimized file discovery using GitHub APIs exclusively"""
    
    def __init__(self, db_session: Session):
        self.db = db_session
        self.github_service = GitHubService()
        self.queue_service = QueueService(queue_name='changed_files')
        self.baseline_manager = BaselineManager(db_session)
        self.logger = get_logger(__name__)
        self.metrics = get_metrics()
        
    def discover_changes(self, repo_url: str, scan_id: int, force_full_scan: bool = False) -> int:
        """
        Main entry point for GitHub file discovery
        
        Args:
            repo_url: GitHub repository URL
            scan_id: Database scan ID
            force_full_scan: Force full scan regardless of baseline availability
            
        Returns:
            Number of files queued for processing
        """
        self.logger.info(f"Starting GitHub discovery for {repo_url}, scan_id: {scan_id}")
        
        # Parse GitHub URL
        parsed_url = self.github_service.parse_github_url(repo_url)
        if not parsed_url:
            self.logger.error(f"Could not parse GitHub URL: {repo_url}")
            return 0
            
        # Get optimal baseline for incremental scanning
        baseline = self.baseline_manager.get_optimal_baseline(repo_url) if not force_full_scan else BaselineInfo(type=BaselineType.NONE, reason="Forced full scan")
        
        self.logger.info(f"Using baseline type: {baseline.type.value}, reason: {baseline.reason}")
        
        # Track discovery start time
        discovery_start = time.time()
        
        try:
            if baseline.type == BaselineType.COMPLETE:
                files_queued = self.incremental_discovery(parsed_url, scan_id, baseline)
                discovery_type = "incremental"
            elif baseline.type == BaselineType.PARTIAL:
                files_queued = self.recovery_discovery(parsed_url, scan_id, baseline)
                discovery_type = "recovery"
            else:  # NONE
                files_queued = self.initial_discovery(parsed_url, scan_id)
                discovery_type = "initial"
                
            # Record discovery metrics
            discovery_duration = time.time() - discovery_start
            self.metrics.record_discovery_completed(discovery_type, files_queued, discovery_duration)
            
            self.logger.info(f"Discovery completed: {files_queued} files queued in {discovery_duration:.2f}s")
            return files_queued
            
        except Exception as e:
            self.logger.error(f"Error during GitHub discovery: {e}", exc_info=True)
            self.metrics.record_error('github_discovery', type(e).__name__)
            return 0
    
    def incremental_discovery(self, parsed_url: Dict, scan_id: int, baseline: BaselineInfo) -> int:
        """
        Use GitHub Compare API for instant change detection
        
        Args:
            parsed_url: Parsed GitHub URL components
            scan_id: Database scan ID
            baseline: Baseline information for comparison
            
        Returns:
            Number of files queued for processing
        """
        repo_full_name = parsed_url['repo_full_name']
        branch = parsed_url['branch']
        
        self.logger.info(f"Starting incremental discovery for {repo_full_name} from commit {baseline.commit_sha}")
        
        # Get current HEAD commit
        current_commit = self.github_service.get_head_commit(repo_full_name, branch)
        if not current_commit:
            self.logger.error(f"Could not get HEAD commit for {repo_full_name}:{branch}")
            return 0
            
        # Update scan with current working commit
        scan = self.db.query(Scan).filter(Scan.id == scan_id).first()
        if scan:
            scan.working_commit_sha = current_commit
            scan.baseline_type = BaselineType.COMPLETE.value
            self.db.commit()
        
        # If already up to date, no changes needed
        if current_commit == baseline.commit_sha:
            self.logger.info(f"Repository is up to date at {current_commit}")
            return 0
            
        # Single API call to get all changes
        try:
            comparison = self.github_service.compare_commits(repo_full_name, baseline.commit_sha, current_commit)
            if not comparison:
                self.logger.error(f"Could not compare commits {baseline.commit_sha}...{current_commit}")
                return 0
                
            self.logger.info(f"Found {len(comparison.files)} changed files between {baseline.commit_sha[:8]}...{current_commit[:8]}")
            
            # Queue only changed markdown files
            files_queued = 0
            for file_change in comparison.files:
                if self._should_process_file(file_change):
                    self._queue_file_for_processing(scan_id, file_change, parsed_url)
                    files_queued += 1
                    
            return files_queued
            
        except Exception as e:
            self.logger.error(f"Error during incremental discovery: {e}", exc_info=True)
            return 0
    
    def initial_discovery(self, parsed_url: Dict, scan_id: int) -> int:
        """
        Use GitHub Trees API for efficient full discovery
        
        Args:
            parsed_url: Parsed GitHub URL components
            scan_id: Database scan ID
            
        Returns:
            Number of files queued for processing
        """
        repo_full_name = parsed_url['repo_full_name']
        branch = parsed_url['branch']
        path = parsed_url.get('path', '')
        
        self.logger.info(f"Starting initial discovery for {repo_full_name}:{branch} at path '{path}'")
        
        # Get current HEAD commit
        current_commit = self.github_service.get_head_commit(repo_full_name, branch)
        if not current_commit:
            self.logger.error(f"Could not get HEAD commit for {repo_full_name}:{branch}")
            return 0
            
        # Update scan with current working commit
        scan = self.db.query(Scan).filter(Scan.id == scan_id).first()
        if scan:
            scan.working_commit_sha = current_commit
            scan.baseline_type = BaselineType.NONE.value
            self.db.commit()
        
        # Get entire repository tree in one API call
        try:
            tree = self.github_service.get_tree(repo_full_name, current_commit, path, recursive=True)
            if not tree:
                self.logger.error(f"Could not get repository tree for {repo_full_name}:{current_commit}")
                return 0
                
            # Filter markdown files
            md_files = [f for f in tree.tree if f.path.endswith('.md') and f.type == 'blob']
            self.logger.info(f"Found {len(md_files)} markdown files in repository")
            
            # Batch queue for efficiency
            files_queued = 0
            batch_size = 100
            
            for i in range(0, len(md_files), batch_size):
                batch = md_files[i:i + batch_size]
                batch_messages = []
                
                for file_obj in batch:
                    if self._should_process_file_path(file_obj.path):
                        # Construct full path from repository root
                        full_path = file_obj.path
                        if path and not file_obj.path.startswith(path):
                            full_path = f"{path.rstrip('/')}/{file_obj.path}"
                        
                        message = {
                            'scan_id': scan_id,
                            'path': full_path,
                            'sha': file_obj.sha,
                            'change_type': 'added',
                            'commit_sha': current_commit
                        }
                        batch_messages.append(message)
                        files_queued += 1
                        
                # Batch publish messages
                if batch_messages:
                    if self.queue_service.connect():
                        self.queue_service.publish_batch('changed_files', batch_messages)
                        self.queue_service.disconnect()
                    else:
                        self.logger.error(f"Failed to connect to queue for batch publishing")
                        return 0
                    
            return files_queued
            
        except Exception as e:
            self.logger.error(f"Error during initial discovery: {e}", exc_info=True)
            return 0
    
    def recovery_discovery(self, parsed_url: Dict, scan_id: int, baseline: BaselineInfo) -> int:
        """
        Recover from partial baselines using file processing history
        
        Args:
            parsed_url: Parsed GitHub URL components
            scan_id: Database scan ID
            baseline: Partial baseline information
            
        Returns:
            Number of files queued for processing
        """
        repo_full_name = parsed_url['repo_full_name']
        branch = parsed_url['branch']
        
        self.logger.info(f"Starting recovery discovery for {repo_full_name}, baseline coverage: {baseline.coverage:.1%}")
        
        # Get current HEAD commit
        current_commit = self.github_service.get_head_commit(repo_full_name, branch)
        if not current_commit:
            self.logger.error(f"Could not get HEAD commit for {repo_full_name}:{branch}")
            return 0
            
        # Update scan with current working commit
        scan = self.db.query(Scan).filter(Scan.id == scan_id).first()
        if scan:
            scan.working_commit_sha = current_commit
            scan.baseline_type = BaselineType.PARTIAL.value
            self.db.commit()
        
        # Get current repository state
        tree = self.github_service.get_tree(repo_full_name, current_commit, recursive=True)
        if not tree:
            self.logger.error(f"Could not get repository tree for {repo_full_name}:{current_commit}")
            return 0
            
        # Find files that need processing
        md_files = [f for f in tree.tree if f.path.endswith('.md') and f.type == 'blob']
        files_queued = 0
        
        for file_obj in md_files:
            if self._should_process_file_path(file_obj.path):
                # Check if we have this file in our baseline
                baseline_sha = baseline.file_map.get(file_obj.path) if baseline.file_map else None
                
                if baseline_sha != file_obj.sha:
                    # File changed or is new, queue for processing
                    change_type = 'modified' if baseline_sha else 'added'
                    
                    message = {
                        'scan_id': scan_id,
                        'path': file_obj.path,
                        'sha': file_obj.sha,
                        'change_type': change_type,
                        'commit_sha': current_commit
                    }
                    
                    if self.queue_service.connect():
                        if self.queue_service.publish('changed_files', message):
                            files_queued += 1
                        self.queue_service.disconnect()
                    else:
                        self.logger.error(f"Failed to connect to queue for publishing file: {file_obj.path}")
                        
        return files_queued
    
    def _should_process_file(self, file_change) -> bool:
        """Check if a file change should be processed"""
        # Only process markdown files
        if not file_change.filename.endswith('.md'):
            return False
            
        # Skip deleted files
        if file_change.status == 'removed':
            return False
            
        # Skip files in excluded directories
        if self._is_excluded_path(file_change.filename):
            return False
            
        return True
    
    def _should_process_file_path(self, file_path: str) -> bool:
        """Check if a file path should be processed"""
        # Skip files in excluded directories
        if self._is_excluded_path(file_path):
            return False
            
        # Skip Windows-focused files
        if self.github_service.is_windows_focused_url(file_path):
            return False
            
        return True
    
    def _is_excluded_path(self, file_path: str) -> bool:
        """Check if a file path should be excluded from processing"""
        excluded_patterns = [
            '/media/',
            '/.github/',
            '/node_modules/',
            '/archive/',
            '/deprecated/',
        ]
        
        file_path_lower = file_path.lower()
        return any(pattern in file_path_lower for pattern in excluded_patterns)
    
    def _queue_file_for_processing(self, scan_id: int, file_change, parsed_url: Dict):
        """Queue a single file for processing"""
        message = {
            'scan_id': scan_id,
            'path': file_change.filename,
            'sha': file_change.sha,
            'change_type': file_change.status,
            'commit_sha': parsed_url.get('commit_sha')
        }
        
        if self.queue_service.connect():
            self.queue_service.publish('changed_files', message)
            self.queue_service.disconnect()
        else:
            self.logger.error(f"Failed to connect to queue for publishing file: {file_change.filename}")


class BaselineManager:
    """Handles baseline selection for incremental scans"""
    
    def __init__(self, db_session: Session):
        self.db = db_session
        self.logger = get_logger(__name__)
        
    def get_optimal_baseline(self, repo_url: str) -> BaselineInfo:
        """
        Find the best baseline for incremental scanning
        
        Args:
            repo_url: GitHub repository URL
            
        Returns:
            BaselineInfo with optimal baseline strategy
        """
        # Option 1: Last complete scan
        complete_baseline = self._get_last_complete_scan(repo_url)
        
        # Option 2: Partial baselines from incomplete scans
        partial_baselines = self._analyze_partial_scans(repo_url)
        
        # Choose optimal strategy
        if complete_baseline and complete_baseline.age < timedelta(days=7):
            return complete_baseline
        elif partial_baselines.coverage > 0.8:
            return partial_baselines
        else:
            return BaselineInfo(type=BaselineType.NONE, reason="No suitable baseline found")
    
    def _get_last_complete_scan(self, repo_url: str) -> Optional[BaselineInfo]:
        """Get the last complete scan for a repository"""
        try:
            last_scan = self.db.query(Scan).filter(
                Scan.url == repo_url,
                Scan.status == 'done',
                Scan.last_commit_sha.isnot(None)
            ).order_by(Scan.finished_at.desc()).first()
            
            if last_scan:
                age = datetime.utcnow() - last_scan.finished_at if last_scan.finished_at else timedelta(days=999)
                return BaselineInfo(
                    type=BaselineType.COMPLETE,
                    commit_sha=last_scan.last_commit_sha,
                    scan_id=last_scan.id,
                    age=age,
                    reason=f"Last complete scan from {last_scan.finished_at}"
                )
                
        except Exception as e:
            self.logger.error(f"Error getting last complete scan: {e}")
            
        return None
    
    def _analyze_partial_scans(self, repo_url: str) -> BaselineInfo:
        """Analyze partial scans to build a composite baseline using processing history"""
        try:
            # Use processing history service to get processed files map
            history_service = ProcessingHistoryService(self.db)
            file_map = history_service.get_processed_files_map(repo_url, max_age_days=30)
            
            if not file_map:
                return BaselineInfo(type=BaselineType.NONE, reason="No processing history found")
            
            # Get scan IDs from recent processing history
            recent_scans = self.db.query(Scan).filter(
                Scan.url == repo_url,
                Scan.started_at >= datetime.utcnow() - timedelta(days=30)
            ).order_by(Scan.started_at.desc()).limit(5).all()
            
            scan_ids = [scan.id for scan in recent_scans]
            
            # Calculate coverage (rough estimate based on typical repo size)
            coverage = min(len(file_map) / 1000, 1.0)  # Assume ~1000 files max
            
            if coverage > 0.5:
                return BaselineInfo(
                    type=BaselineType.PARTIAL,
                    file_map=file_map,
                    scan_ids=scan_ids,
                    coverage=coverage,
                    reason=f"Partial baseline from processing history, {len(file_map)} files, {coverage:.1%} coverage"
                )
                
        except Exception as e:
            self.logger.error(f"Error analyzing partial scans: {e}")
            
        return BaselineInfo(type=BaselineType.NONE, reason="No viable partial baseline")
    
    def _extract_file_path_from_url(self, github_url: str) -> Optional[str]:
        """Extract file path from GitHub URL"""
        # Example: https://github.com/owner/repo/blob/branch/path/to/file.md
        # Extract: path/to/file.md
        parts = github_url.split('/blob/')
        if len(parts) == 2:
            # Remove branch part
            path_with_branch = parts[1]
            path_parts = path_with_branch.split('/', 1)
            if len(path_parts) == 2:
                return path_parts[1]
        return None