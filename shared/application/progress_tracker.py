"""
ProgressTracker - Database-only progress tracking without WebSocket dependencies
"""
import datetime
import time
from typing import Dict, Optional, Any
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from shared.models import Scan, Page, Snippet
from shared.utils.logging import get_logger
from shared.utils.error_handling import safe_execute
from shared.utils.database import safe_commit

logger = get_logger(__name__)


class ProgressTracker:
    """Service for managing scan progress tracking in the database only"""
    
    def __init__(self):
        self.phase_start_times: Dict[int, Dict[str, datetime.datetime]] = {}
        
    def start_phase(self, db: Session, scan_id: int, phase: str, details: Optional[Dict] = None):
        """Mark the start of a scan phase and update database"""
        logger.info(f"Scan {scan_id}: Starting phase '{phase}'")
        
        # Update scan record
        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        if not scan:
            logger.error(f"Scan {scan_id} not found")
            return
            
        # Initialize progress structures if needed
        if not scan.phase_timestamps:
            scan.phase_timestamps = {}
        if not scan.phase_progress:
            scan.phase_progress = {}
            
        # Record phase start time
        now = datetime.datetime.now(datetime.timezone.utc)
        scan.current_phase = phase
        scan.phase_timestamps[phase] = {
            'started': now.isoformat(),
            'finished': None
        }
        
        # Initialize phase progress
        scan.phase_progress[phase] = {
            'started': True,
            'completed': False,
            'progress_percentage': 0,
            'items_processed': 0,
            'items_total': 0,
            'current_item': None,
            'details': details or {}
        }
        
        # Track phase start time for ETA calculations
        if scan_id not in self.phase_start_times:
            self.phase_start_times[scan_id] = {}
        self.phase_start_times[scan_id][phase] = now
        
        # Mark JSON fields as modified for SQLAlchemy
        flag_modified(scan, 'phase_timestamps')
        flag_modified(scan, 'phase_progress')
        
        safe_commit(db)
        
    def update_phase_progress(
        self, 
        db: Session, 
        scan_id: int, 
        items_processed: int, 
        items_total: Optional[int] = None,
        current_item: Optional[str] = None,
        details: Optional[Dict] = None
    ):
        """Update progress within the current phase"""
        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        if not scan or not scan.current_phase:
            return
            
        phase = scan.current_phase
        
        # Update phase progress
        if scan.phase_progress and phase in scan.phase_progress:
            progress = scan.phase_progress[phase]
            progress['items_processed'] = items_processed
            
            if items_total is not None:
                progress['items_total'] = items_total
                
                # Update total_pages_found if it's increasing (discovery is finding more pages)
                # or if it hasn't been set yet, or if we're in discovery-related phases
                if (scan.total_pages_found == 0 or 
                    items_total > scan.total_pages_found or 
                    phase in ['crawling', 'discovery', 'discovering', 'file_discovery']):
                    old_total = scan.total_pages_found
                    scan.total_pages_found = items_total
                    if old_total != items_total:
                        logger.info(f"Scan {scan_id}: Updated total_pages_found from {old_total} to {items_total} during phase '{phase}'")
                else:
                    logger.debug(f"Scan {scan_id}: Skipping total_pages_found update ({scan.total_pages_found} -> {items_total}) during phase '{phase}'")
                
            if progress['items_total'] > 0:
                progress['progress_percentage'] = (items_processed / progress['items_total']) * 100
                
            if current_item is not None:
                progress['current_item'] = current_item
                scan.current_page_url = current_item
                
            if details:
                progress['details'].update(details)
                
        # Update scan-level counters
        scan.pages_processed = items_processed
        
        # Calculate ETA
        self._update_eta(scan, scan_id, phase, items_processed, items_total)
        
        # Mark JSON fields as modified for SQLAlchemy
        flag_modified(scan, 'phase_progress')
        if scan.performance_metrics:
            flag_modified(scan, 'performance_metrics')
        
        safe_commit(db)
        
    def complete_phase(self, db: Session, scan_id: int, phase: str, summary: Optional[Dict] = None):
        """Mark a phase as completed"""
        logger.info(f"Scan {scan_id}: Completing phase '{phase}'")
        
        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        if not scan:
            return
            
        # Update phase completion
        if scan.phase_timestamps and phase in scan.phase_timestamps:
            scan.phase_timestamps[phase]['finished'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            
        if scan.phase_progress and phase in scan.phase_progress:
            scan.phase_progress[phase]['completed'] = True
            scan.phase_progress[phase]['progress_percentage'] = 100
            if summary:
                scan.phase_progress[phase]['summary'] = summary
        
        # Mark JSON fields as modified for SQLAlchemy        
        flag_modified(scan, 'phase_timestamps')
        flag_modified(scan, 'phase_progress')
                
        safe_commit(db)
        
    def report_error(self, db: Session, scan_id: int, error_message: str, details: Optional[Dict] = None):
        """Report an error during scan processing"""
        logger.error(f"Scan {scan_id} error: {error_message}")
        
        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        if not scan:
            return
            
        # Initialize error log if needed
        if not scan.error_log:
            scan.error_log = []
            
        # Add error to log
        error_entry = {
            'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'message': error_message,
            'phase': scan.current_phase,
            'current_item': scan.current_page_url,
            'details': details or {}
        }
        scan.error_log.append(error_entry)
        
        # Mark JSON field as modified for SQLAlchemy
        flag_modified(scan, 'error_log')
        
        safe_commit(db)
        
    def report_page_result(self, db: Session, scan_id: int, page_url: str, has_bias: bool, bias_details: Optional[Dict] = None):
        """Report when a page result is available (for database logging)"""
        if has_bias:
            logger.info(f"Scan {scan_id}: Bias detected on page {page_url}")
    
    def _update_eta(self, scan: Scan, scan_id: int, phase: str, items_processed: int, items_total: Optional[int]):
        """Calculate and update estimated time of completion"""
        if not items_total or items_processed == 0:
            return
            
        # Get phase start time
        if scan_id not in self.phase_start_times or phase not in self.phase_start_times[scan_id]:
            return
            
        start_time = self.phase_start_times[scan_id][phase]
        elapsed = datetime.datetime.now(datetime.timezone.utc) - start_time
        
        # Calculate processing rate
        processing_rate = items_processed / elapsed.total_seconds()  # items per second
        
        if processing_rate > 0:
            remaining_items = items_total - items_processed
            remaining_seconds = remaining_items / processing_rate
            scan.estimated_completion = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=remaining_seconds)
            
            # Update performance metrics
            if not scan.performance_metrics:
                scan.performance_metrics = {}
            scan.performance_metrics[phase] = {
                'processing_rate': processing_rate,
                'elapsed_seconds': elapsed.total_seconds(),
                'items_per_second': processing_rate
            }


# Global progress tracker instance
progress_tracker = ProgressTracker()