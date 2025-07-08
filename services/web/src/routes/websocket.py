"""
WebSocket routes for real-time scan progress updates
"""
import sys
import os

# Add the project root to the Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, project_root)

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from shared.utils.database import SessionLocal
from shared.models import Scan
from shared.application.progress_service import progress_service

router = APIRouter()


@router.websocket("/ws/scan/{scan_id}")
async def websocket_scan_progress(websocket: WebSocket, scan_id: int):
    """
    WebSocket endpoint for real-time scan progress updates
    
    Clients can connect to this endpoint to receive live updates about:
    - Phase transitions (crawling -> extracting -> scoring -> done)
    - Progress within each phase (items processed, current item)
    - Error notifications
    - Live results as problematic pages are discovered
    - Performance metrics and ETA calculations
    """
    # Verify scan exists
    db = SessionLocal()
    try:
        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        if not scan:
            await websocket.close(code=4004, reason="Scan not found")
            return
    finally:
        db.close()
    
    # Accept WebSocket connection
    await websocket.accept()
    
    # Register connection with progress service
    await progress_service.connect_websocket(scan_id, websocket)
    
    try:
        # Keep connection alive and handle any client messages
        while True:
            # Wait for any message from client (ping, etc.)
            data = await websocket.receive_text()
            
            # Handle client messages if needed
            if data == "ping":
                await websocket.send_text("pong")
            
    except WebSocketDisconnect:
        # Client disconnected normally
        pass
    except Exception as e:
        print(f"[ERROR] WebSocket error for scan {scan_id}: {e}")
    finally:
        # Unregister connection
        await progress_service.disconnect_websocket(scan_id, websocket)


@router.get("/api/scan/{scan_id}/progress")
async def get_scan_progress(scan_id: int):
    """
    HTTP endpoint for getting current scan progress (fallback for non-WebSocket clients)
    
    Returns detailed progress information including:
    - Current phase and progress percentage
    - Phase timestamps and performance metrics
    - Error log and current status
    - Estimated completion time
    """
    db = SessionLocal()
    try:
        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        if not scan:
            raise HTTPException(status_code=404, detail="Scan not found")
        
        # Calculate overall progress
        total_phases = 4  # crawling, extracting, scoring, mcp_holistic
        completed_phases = 0
        
        if scan.phase_progress:
            for phase_data in scan.phase_progress.values():
                if phase_data.get('completed', False):
                    completed_phases += 1
        
        overall_progress = (completed_phases / total_phases) * 100
        
        # Get current phase progress
        current_phase_progress = 0
        if scan.current_phase and scan.phase_progress and scan.current_phase in scan.phase_progress:
            current_phase_progress = scan.phase_progress[scan.current_phase].get('progress_percentage', 0)
        
        return {
            'scan_id': scan_id,
            'status': scan.status,
            'current_phase': scan.current_phase,
            'current_page_url': scan.current_page_url,
            'overall_progress': overall_progress,
            'current_phase_progress': current_phase_progress,
            'total_pages_found': scan.total_pages_found,
            'pages_processed': scan.pages_processed,
            'snippets_processed': scan.snippets_processed,
            'estimated_completion': scan.estimated_completion.isoformat() if scan.estimated_completion else None,
            'phase_progress': scan.phase_progress or {},
            'phase_timestamps': scan.phase_timestamps or {},
            'performance_metrics': scan.performance_metrics or {},
            'error_log': scan.error_log or [],
            'started_at': scan.started_at.isoformat(),
            'finished_at': scan.finished_at.isoformat() if scan.finished_at else None,
            'cancellation_requested': scan.cancellation_requested,
            'cancellation_requested_at': scan.cancellation_requested_at.isoformat() if scan.cancellation_requested_at else None,
            'cancellation_reason': scan.cancellation_reason
        }
        
    finally:
        db.close()


@router.get("/api/scan/{scan_id}/results")
async def get_scan_results(scan_id: int, limit: int = 50, offset: int = 0):
    """
    HTTP endpoint for getting scan results with pagination
    
    Returns paginated list of pages with bias detection results.
    Useful for loading results incrementally as they become available.
    """
    db = SessionLocal()
    try:
        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        if not scan:
            raise HTTPException(status_code=404, detail="Scan not found")
        
        # Get pages with results, prioritizing those with bias detected
        from shared.models import Page
        pages_query = db.query(Page).filter(Page.scan_id == scan_id)
        
        # Order by bias detection (pages with bias first) then by ID
        pages = pages_query.offset(offset).limit(limit).all()
        
        results = []
        for page in pages:
            page_data = {
                'id': page.id,
                'url': page.url,
                'status': page.status,
                'has_bias': bool(page.mcp_holistic and page.mcp_holistic.get('bias_types')),
                'mcp_holistic': page.mcp_holistic
            }
            
            # Add bias summary if available
            if page_data['has_bias']:
                page_data['bias_summary'] = {
                    'bias_types': page.mcp_holistic.get('bias_types', []),
                    'summary': page.mcp_holistic.get('summary', ''),
                    'recommendations': page.mcp_holistic.get('recommendations', [])
                }
            
            results.append(page_data)
        
        total_pages = db.query(Page).filter(Page.scan_id == scan_id).count()
        
        return {
            'scan_id': scan_id,
            'results': results,
            'pagination': {
                'offset': offset,
                'limit': limit,
                'total': total_pages,
                'has_more': offset + limit < total_pages
            }
        }
        
    finally:
        db.close()