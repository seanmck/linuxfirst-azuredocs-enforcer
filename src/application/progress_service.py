"""
ProgressService - Manages real-time scan progress tracking and WebSocket broadcasting
"""
import asyncio
import json
import datetime
import time
from typing import Dict, List, Set, Optional, Any
from fastapi import WebSocket
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from src.shared.models import Scan, Page, Snippet
from src.shared.utils.logging import get_logger
from src.shared.utils.error_handling import safe_execute
from src.shared.utils.database import safe_commit

logger = get_logger(__name__)


class ProgressService:
    """Service for managing real-time scan progress tracking and broadcasting"""
    
    def __init__(self):
        # WebSocket connections keyed by scan_id
        self.connections: Dict[int, Set[WebSocket]] = {}
        self.phase_start_times: Dict[int, Dict[str, datetime.datetime]] = {}
        
    async def connect_websocket(self, scan_id: int, websocket: WebSocket):
        """Add a WebSocket connection for a specific scan"""
        if scan_id not in self.connections:
            self.connections[scan_id] = set()
        
        self.connections[scan_id].add(websocket)
        logger.info(f"WebSocket connected for scan {scan_id}. Total connections: {len(self.connections[scan_id])}")
        
        # Send initial progress state
        await self._send_initial_progress(scan_id, websocket)
        
    async def disconnect_websocket(self, scan_id: int, websocket: WebSocket):
        """Remove a WebSocket connection"""
        if scan_id in self.connections:
            self.connections[scan_id].discard(websocket)
            if not self.connections[scan_id]:
                del self.connections[scan_id]
                
        logger.info(f"WebSocket disconnected for scan {scan_id}")
        
    async def broadcast_progress(self, scan_id: int, progress_data: Dict[str, Any]):
        """Broadcast progress update to all connected WebSockets for a scan"""
        if scan_id not in self.connections:
            return
            
        # Add timestamp to progress data
        progress_data['timestamp'] = datetime.datetime.utcnow().isoformat()
        
        disconnected = set()
        for websocket in self.connections[scan_id]:
            try:
                await websocket.send_json(progress_data)
            except Exception as e:
                logger.warning(f"Failed to send progress to WebSocket: {e}")
                disconnected.add(websocket)
                
        # Clean up disconnected sockets
        for websocket in disconnected:
            self.connections[scan_id].discard(websocket)
            
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
        now = datetime.datetime.utcnow()
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
        
        # Broadcast phase start (handle async/sync context)
        self._safe_broadcast(scan_id, {
            'type': 'phase_start',
            'phase': phase,
            'details': details,
            'scan_status': scan.status
        })
        
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
                scan.total_pages_found = items_total
                
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
        
        # Broadcast progress update (handle async/sync context)
        self._safe_broadcast(scan_id, {
            'type': 'progress_update',
            'phase': phase,
            'items_processed': items_processed,
            'items_total': items_total or 0,
            'current_item': current_item,
            'progress_percentage': scan.phase_progress.get(phase, {}).get('progress_percentage', 0) if scan.phase_progress else 0,
            'estimated_completion': scan.estimated_completion.isoformat() if scan.estimated_completion else None,
            'details': details
        })
        
    def complete_phase(self, db: Session, scan_id: int, phase: str, summary: Optional[Dict] = None):
        """Mark a phase as completed"""
        logger.info(f"Scan {scan_id}: Completing phase '{phase}'")
        
        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        if not scan:
            return
            
        # Update phase completion
        if scan.phase_timestamps and phase in scan.phase_timestamps:
            scan.phase_timestamps[phase]['finished'] = datetime.datetime.utcnow().isoformat()
            
        if scan.phase_progress and phase in scan.phase_progress:
            scan.phase_progress[phase]['completed'] = True
            scan.phase_progress[phase]['progress_percentage'] = 100
            if summary:
                scan.phase_progress[phase]['summary'] = summary
        
        # Mark JSON fields as modified for SQLAlchemy        
        flag_modified(scan, 'phase_timestamps')
        flag_modified(scan, 'phase_progress')
                
        safe_commit(db)
        
        # Broadcast phase completion (handle async/sync context)
        self._safe_broadcast(scan_id, {
            'type': 'phase_complete',
            'phase': phase,
            'summary': summary
        })
        
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
            'timestamp': datetime.datetime.utcnow().isoformat(),
            'message': error_message,
            'phase': scan.current_phase,
            'current_item': scan.current_page_url,
            'details': details or {}
        }
        scan.error_log.append(error_entry)
        
        # Mark JSON field as modified for SQLAlchemy
        flag_modified(scan, 'error_log')
        
        safe_commit(db)
        
        # Broadcast error (handle async/sync context)
        self._safe_broadcast(scan_id, {
            'type': 'error',
            'message': error_message,
            'phase': scan.current_phase,
            'details': details
        })
        
    def report_page_result(self, db: Session, scan_id: int, page_url: str, has_bias: bool, bias_details: Optional[Dict] = None):
        """Report when a page result is available (for live streaming of results)"""
        if has_bias:
            logger.info(f"Scan {scan_id}: Bias detected on page {page_url}")
            
            # Broadcast new biased page result (handle async/sync context)
            self._safe_broadcast(scan_id, {
                'type': 'page_result',
                'page_url': page_url,
                'has_bias': has_bias,
                'bias_details': bias_details
            })
    
    def _update_eta(self, scan: Scan, scan_id: int, phase: str, items_processed: int, items_total: Optional[int]):
        """Calculate and update estimated time of completion"""
        if not items_total or items_processed == 0:
            return
            
        # Get phase start time
        if scan_id not in self.phase_start_times or phase not in self.phase_start_times[scan_id]:
            return
            
        start_time = self.phase_start_times[scan_id][phase]
        elapsed = datetime.datetime.utcnow() - start_time
        
        # Calculate processing rate
        processing_rate = items_processed / elapsed.total_seconds()  # items per second
        
        if processing_rate > 0:
            remaining_items = items_total - items_processed
            remaining_seconds = remaining_items / processing_rate
            scan.estimated_completion = datetime.datetime.utcnow() + datetime.timedelta(seconds=remaining_seconds)
            
            # Update performance metrics
            if not scan.performance_metrics:
                scan.performance_metrics = {}
            scan.performance_metrics[phase] = {
                'processing_rate': processing_rate,
                'elapsed_seconds': elapsed.total_seconds(),
                'items_per_second': processing_rate
            }
    
    def _safe_broadcast(self, scan_id: int, progress_data: Dict[str, Any]):
        """Safely broadcast progress updates, handling async/sync contexts"""
        # Skip WebSocket broadcasting from sync context for now
        # The frontend can use HTTP polling via /api/scan/{scan_id}/progress
        logger.info(f"Progress update for scan {scan_id}: {progress_data.get('type', 'unknown')} - {progress_data.get('phase', 'N/A')}")
        
        # For now, just log that we would broadcast this
        # WebSocket broadcasting from sync worker context is complex
        # The HTTP API endpoint provides the same data
    
    async def _send_initial_progress(self, scan_id: int, websocket: WebSocket):
        """Send initial progress state to a newly connected WebSocket"""
        # This would typically fetch current scan state from database
        # and send it to the new connection
        try:
            await websocket.send_json({
                'type': 'connected',
                'scan_id': scan_id,
                'message': 'Connected to scan progress updates'
            })
        except Exception as e:
            logger.warning(f"Failed to send initial progress: {e}")


# Global progress service instance
progress_service = ProgressService()