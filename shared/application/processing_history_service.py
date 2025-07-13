"""
ProcessingHistoryService - Tracks file processing history for audit and recovery

This service provides comprehensive tracking of file processing across scans,
enabling recovery scenarios and audit trails as outlined in the resilient
scanning architecture.
"""
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc

from shared.models import FileProcessingHistory, Scan, Page
from shared.utils.logging import get_logger


class ProcessingHistoryService:
    """Service for tracking and querying file processing history"""
    
    def __init__(self, db_session: Session):
        self.db = db_session
        self.logger = get_logger(__name__)
        
    def record_processing_start(self, file_path: str, github_sha: str, scan_id: int, 
                               worker_id: str, commit_sha: Optional[str] = None) -> Optional[int]:
        """
        Record the start of file processing
        
        Args:
            file_path: Path to the file being processed
            github_sha: GitHub SHA of the file
            scan_id: Scan ID
            worker_id: ID of the worker processing the file
            commit_sha: Commit SHA being processed
            
        Returns:
            Processing history record ID or None if failed
        """
        try:
            # Check if record already exists
            existing = self.db.query(FileProcessingHistory).filter(
                and_(
                    FileProcessingHistory.file_path == file_path,
                    FileProcessingHistory.github_sha == github_sha,
                    FileProcessingHistory.scan_id == scan_id
                )
            ).first()
            
            if existing:
                # Update existing record
                existing.processed_at = datetime.now(timezone.utc)
                existing.worker_id = worker_id
                existing.commit_sha = commit_sha
                existing.processing_result = 'processing'
                self.db.commit()
                return existing.id
            else:
                # Create new record
                history_record = FileProcessingHistory(
                    file_path=file_path,
                    github_sha=github_sha,
                    scan_id=scan_id,
                    processed_at=datetime.now(timezone.utc),
                    processing_result='processing',
                    worker_id=worker_id,
                    commit_sha=commit_sha
                )
                self.db.add(history_record)
                self.db.commit()
                return history_record.id
                
        except Exception as e:
            self.logger.error(f"Error recording processing start for {file_path}: {e}")
            return None
    
    def record_processing_completion(self, file_path: str, github_sha: str, scan_id: int,
                                   result: str, duration_ms: int, snippets_found: int = 0,
                                   bias_detected: bool = False, error_message: str = None):
        """
        Record the completion of file processing
        
        Args:
            file_path: Path to the file that was processed
            github_sha: GitHub SHA of the file
            scan_id: Scan ID
            result: Processing result (completed, failed, skipped)
            duration_ms: Processing duration in milliseconds
            snippets_found: Number of code snippets found
            bias_detected: Whether bias was detected
            error_message: Error message if processing failed
        """
        try:
            # Find the existing record
            history_record = self.db.query(FileProcessingHistory).filter(
                and_(
                    FileProcessingHistory.file_path == file_path,
                    FileProcessingHistory.github_sha == github_sha,
                    FileProcessingHistory.scan_id == scan_id
                )
            ).first()
            
            if history_record:
                # Update the record
                history_record.processing_result = result
                history_record.processing_duration_ms = duration_ms
                history_record.snippets_found = snippets_found
                history_record.bias_detected = bias_detected
                history_record.error_message = error_message
                history_record.processed_at = datetime.now(timezone.utc)
                
                self.db.commit()
                self.logger.debug(f"Updated processing history for {file_path}: {result}")
            else:
                self.logger.warning(f"No processing history record found for {file_path}")
                
        except Exception as e:
            self.logger.error(f"Error recording processing completion for {file_path}: {e}")
    
    def get_processing_history(self, file_path: str, github_sha: str = None, 
                             limit: int = 10) -> List[FileProcessingHistory]:
        """
        Get processing history for a file
        
        Args:
            file_path: Path to the file
            github_sha: Optional GitHub SHA to filter by
            limit: Maximum number of records to return
            
        Returns:
            List of processing history records
        """
        try:
            query = self.db.query(FileProcessingHistory).filter(
                FileProcessingHistory.file_path == file_path
            )
            
            if github_sha:
                query = query.filter(FileProcessingHistory.github_sha == github_sha)
            
            return query.order_by(desc(FileProcessingHistory.processed_at)).limit(limit).all()
            
        except Exception as e:
            self.logger.error(f"Error getting processing history for {file_path}: {e}")
            return []
    
    def get_scan_processing_summary(self, scan_id: int) -> Dict[str, int]:
        """
        Get processing summary for a scan
        
        Args:
            scan_id: Scan ID
            
        Returns:
            Dictionary with processing result counts
        """
        try:
            from sqlalchemy import func
            
            results = self.db.query(
                FileProcessingHistory.processing_result,
                func.count(FileProcessingHistory.id).label('count')
            ).filter(
                FileProcessingHistory.scan_id == scan_id
            ).group_by(
                FileProcessingHistory.processing_result
            ).all()
            
            return {result: count for result, count in results}
            
        except Exception as e:
            self.logger.error(f"Error getting processing summary for scan {scan_id}: {e}")
            return {}
    
    def get_processed_files_map(self, repo_url: str, max_age_days: int = 30) -> Dict[str, str]:
        """
        Get a map of processed files for a repository for baseline building
        
        Args:
            repo_url: Repository URL
            max_age_days: Maximum age of processing records to consider
            
        Returns:
            Dictionary mapping file_path to github_sha for successfully processed files
        """
        try:
            from sqlalchemy import and_
            from datetime import timedelta
            
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=max_age_days)
            
            # Get successfully processed files from recent scans
            results = self.db.query(
                FileProcessingHistory.file_path,
                FileProcessingHistory.github_sha
            ).join(
                Scan, FileProcessingHistory.scan_id == Scan.id
            ).filter(
                and_(
                    Scan.url == repo_url,
                    FileProcessingHistory.processing_result == 'processed',
                    FileProcessingHistory.processed_at >= cutoff_date
                )
            ).distinct().all()
            
            return {file_path: github_sha for file_path, github_sha in results}
            
        except Exception as e:
            self.logger.error(f"Error getting processed files map for {repo_url}: {e}")
            return {}
    
    def get_failed_files(self, scan_id: int) -> List[Dict[str, str]]:
        """
        Get files that failed processing in a scan
        
        Args:
            scan_id: Scan ID
            
        Returns:
            List of failed file information
        """
        try:
            failed_files = self.db.query(FileProcessingHistory).filter(
                and_(
                    FileProcessingHistory.scan_id == scan_id,
                    FileProcessingHistory.processing_result == 'failed'
                )
            ).all()
            
            return [
                {
                    'file_path': record.file_path,
                    'github_sha': record.github_sha,
                    'error_message': record.error_message,
                    'processed_at': record.processed_at.isoformat() if record.processed_at else None
                }
                for record in failed_files
            ]
            
        except Exception as e:
            self.logger.error(f"Error getting failed files for scan {scan_id}: {e}")
            return []
    
    def cleanup_old_history(self, days_to_keep: int = 90) -> int:
        """
        Clean up old processing history records
        
        Args:
            days_to_keep: Number of days of history to keep
            
        Returns:
            Number of records deleted
        """
        try:
            from datetime import timedelta
            
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
            
            deleted_count = self.db.query(FileProcessingHistory).filter(
                FileProcessingHistory.processed_at < cutoff_date
            ).delete()
            
            self.db.commit()
            
            self.logger.info(f"Cleaned up {deleted_count} old processing history records")
            return deleted_count
            
        except Exception as e:
            self.logger.error(f"Error cleaning up old history: {e}")
            return 0
    
    def get_processing_stats(self, scan_id: int) -> Dict[str, any]:
        """
        Get comprehensive processing statistics for a scan
        
        Args:
            scan_id: Scan ID
            
        Returns:
            Dictionary with processing statistics
        """
        try:
            from sqlalchemy import func
            
            # Get basic counts
            summary = self.get_scan_processing_summary(scan_id)
            
            # Get timing statistics
            timing_stats = self.db.query(
                func.avg(FileProcessingHistory.processing_duration_ms).label('avg_duration'),
                func.min(FileProcessingHistory.processing_duration_ms).label('min_duration'),
                func.max(FileProcessingHistory.processing_duration_ms).label('max_duration'),
                func.count(FileProcessingHistory.id).label('total_processed')
            ).filter(
                and_(
                    FileProcessingHistory.scan_id == scan_id,
                    FileProcessingHistory.processing_duration_ms.isnot(None)
                )
            ).first()
            
            # Get bias detection stats
            bias_stats = self.db.query(
                func.count(FileProcessingHistory.id).label('files_with_bias'),
                func.sum(FileProcessingHistory.snippets_found).label('total_snippets')
            ).filter(
                and_(
                    FileProcessingHistory.scan_id == scan_id,
                    FileProcessingHistory.bias_detected == True
                )
            ).first()
            
            return {
                'result_summary': summary,
                'timing': {
                    'avg_duration_ms': float(timing_stats.avg_duration) if timing_stats.avg_duration else 0,
                    'min_duration_ms': timing_stats.min_duration or 0,
                    'max_duration_ms': timing_stats.max_duration or 0,
                    'total_processed': timing_stats.total_processed or 0
                },
                'bias_detection': {
                    'files_with_bias': bias_stats.files_with_bias or 0,
                    'total_snippets': bias_stats.total_snippets or 0
                }
            }
            
        except Exception as e:
            self.logger.error(f"Error getting processing stats for scan {scan_id}: {e}")
            return {}