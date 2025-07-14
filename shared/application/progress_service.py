"""
ProgressService - Manages real-time WebSocket broadcasting for scan progress
"""
import asyncio
import json
import datetime
import time
from typing import Dict, List, Set, Optional, Any
from fastapi import WebSocket
from sqlalchemy.orm import Session

from shared.models import Scan
from shared.utils.logging import get_logger
from shared.application.progress_tracker import progress_tracker

logger = get_logger(__name__)


class ProgressService:
    """Service for managing real-time WebSocket broadcasting of scan progress"""
    
    def __init__(self):
        # WebSocket connections keyed by scan_id
        self.connections: Dict[int, Set[WebSocket]] = {}
        
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
        progress_data['timestamp'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
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
        """Start a phase using the progress tracker and broadcast to WebSockets"""
        # Use the progress tracker for database operations
        progress_tracker.start_phase(db, scan_id, phase, details)
        
        # Get scan status for broadcasting
        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        scan_status = scan.status if scan else None
        
        # Broadcast phase start (handle async/sync context)
        self._safe_broadcast(scan_id, {
            'type': 'phase_start',
            'phase': phase,
            'details': details,
            'scan_status': scan_status
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
        """Update phase progress using the progress tracker and broadcast to WebSockets"""
        # Use the progress tracker for database operations
        progress_tracker.update_phase_progress(
            db, scan_id, items_processed, items_total, current_item, details
        )
        
        # Get current scan state for broadcasting
        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        if not scan or not scan.current_phase:
            return
            
        phase = scan.current_phase
        progress_percentage = 0
        if scan.phase_progress and phase in scan.phase_progress:
            progress_percentage = scan.phase_progress[phase].get('progress_percentage', 0)
        
        # Calculate page-based overall progress
        overall_progress = 0
        if scan.total_pages_found and scan.total_pages_found > 0:
            overall_progress = (scan.pages_processed / scan.total_pages_found) * 100
        elif scan.status == 'completed':
            overall_progress = 100
        
        # Broadcast progress update (handle async/sync context)
        self._safe_broadcast(scan_id, {
            'type': 'progress_update',
            'phase': phase,
            'items_processed': items_processed,
            'items_total': items_total or 0,
            'current_item': current_item,
            'progress_percentage': progress_percentage,
            'overall_progress': overall_progress,
            'total_pages_found': scan.total_pages_found,
            'pages_processed': scan.pages_processed,
            'estimated_completion': scan.estimated_completion.isoformat() if scan.estimated_completion else None,
            'details': details
        })
        
    def complete_phase(self, db: Session, scan_id: int, phase: str, summary: Optional[Dict] = None):
        """Complete a phase using the progress tracker and broadcast to WebSockets"""
        # Use the progress tracker for database operations
        progress_tracker.complete_phase(db, scan_id, phase, summary)
        
        # Broadcast phase completion (handle async/sync context)
        self._safe_broadcast(scan_id, {
            'type': 'phase_complete',
            'phase': phase,
            'summary': summary
        })
        
    def report_error(self, db: Session, scan_id: int, error_message: str, details: Optional[Dict] = None):
        """Report an error using the progress tracker and broadcast to WebSockets"""
        # Use the progress tracker for database operations
        progress_tracker.report_error(db, scan_id, error_message, details)
        
        # Get current scan state for broadcasting
        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        current_phase = scan.current_phase if scan else None
        
        # Broadcast error (handle async/sync context)
        self._safe_broadcast(scan_id, {
            'type': 'error',
            'message': error_message,
            'phase': current_phase,
            'details': details
        })
        
    def report_page_result(self, db: Session, scan_id: int, page_url: str, has_bias: bool, bias_details: Optional[Dict] = None):
        """Report page result using the progress tracker and broadcast to WebSockets"""
        # Use the progress tracker for database operations
        progress_tracker.report_page_result(db, scan_id, page_url, has_bias, bias_details)
        
        if has_bias:
            # Broadcast new biased page result (handle async/sync context)
            self._safe_broadcast(scan_id, {
                'type': 'page_result',
                'page_url': page_url,
                'has_bias': has_bias,
                'bias_details': bias_details
            })
    
    def _safe_broadcast(self, scan_id: int, progress_data: Dict[str, Any]):
        """Safely broadcast progress updates, handling async/sync contexts"""
        logger.info(f"Progress update for scan {scan_id}: {progress_data.get('type', 'unknown')} - {progress_data.get('phase', 'N/A')}")
        
        # Try to broadcast to WebSocket connections
        if scan_id in self.connections and self.connections[scan_id]:
            try:
                # Get the current event loop or create a new one if needed
                try:
                    loop = asyncio.get_running_loop()
                    # If we're in an async context, schedule the broadcast
                    loop.create_task(self.broadcast_progress(scan_id, progress_data))
                except RuntimeError:
                    # We're in a sync context, try to run in a new thread
                    import threading
                    def run_broadcast():
                        try:
                            asyncio.run(self.broadcast_progress(scan_id, progress_data))
                        except Exception as e:
                            logger.warning(f"Failed to broadcast in thread: {e}")
                    
                    thread = threading.Thread(target=run_broadcast)
                    thread.daemon = True
                    thread.start()
            except Exception as e:
                logger.warning(f"Failed to broadcast progress update: {e}")
        else:
            logger.debug(f"No WebSocket connections for scan {scan_id}, skipping broadcast")
    
    async def _send_initial_progress(self, scan_id: int, websocket: WebSocket):
        """Send initial progress state to a newly connected WebSocket"""
        try:
            from shared.utils.database import SessionLocal
            db = SessionLocal()
            try:
                scan = db.query(Scan).filter(Scan.id == scan_id).first()
                if scan:
                    # Calculate page-based overall progress
                    overall_progress = 0
                    if scan.total_pages_found and scan.total_pages_found > 0:
                        overall_progress = (scan.pages_processed / scan.total_pages_found) * 100
                    elif scan.status == 'completed':
                        overall_progress = 100
                    
                    await websocket.send_json({
                        'type': 'initial_progress',
                        'scan_id': scan_id,
                        'status': scan.status,
                        'current_phase': scan.current_phase,
                        'overall_progress': overall_progress,
                        'total_pages_found': scan.total_pages_found,
                        'pages_processed': scan.pages_processed,
                        'current_page_url': scan.current_page_url
                    })
                else:
                    await websocket.send_json({
                        'type': 'connected',
                        'scan_id': scan_id,
                        'message': 'Connected to scan progress updates'
                    })
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"Failed to send initial progress: {e}")


# Global progress service instance
progress_service = ProgressService()