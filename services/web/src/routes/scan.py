from fastapi import APIRouter, Request, HTTPException, Cookie, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from shared.utils.database import SessionLocal
from shared.models import Scan, Page, Snippet, User
from datetime import datetime
from typing import Optional
import os
import requests
import pprint
import pika
import json
from shared.utils.bias_utils import is_page_biased, get_page_priority
from shared.utils.url_utils import format_doc_set_name
from routes.auth import get_current_user
from jinja_env import templates

router = APIRouter()


@router.get("/scan/{scan_id}")
async def scan_details(scan_id: int, request: Request, current_user: Optional[User] = Depends(get_current_user)):
    db = SessionLocal()
    scan = db.query(Scan).filter(Scan.id == scan_id).first()
    if not scan:
        db.close()
        raise HTTPException(status_code=404, detail="Scan not found")
    pages = db.query(Page).filter(Page.scan_id == scan.id).all()
    scanned_count = len(pages)
    flagged_pages = [p for p in pages if is_page_biased(p)]
    flagged_count = len(flagged_pages)
    percent_flagged = (flagged_count / scanned_count * 100) if scanned_count else 0
    
    # Calculate initial progress for the UI (using file-based counters for GitHub scans)
    initial_progress = 0
    if scan.total_files_queued and scan.total_files_queued > 0:
        initial_progress = (scan.total_files_completed / scan.total_files_queued) * 100
    elif scan.status == 'completed':
        initial_progress = 100
    
    # Calculate changed pages count
    changed_pages_count = 0
    try:
        # For now, let's use a simpler heuristic: count pages that were scanned in this scan
        # This gives us "freshly reviewed" pages which is useful for the user
        if pages:
            # Count all pages in this scan as "changed" since they're being freshly reviewed
            # In the future, we can enhance this with proper change detection
            changed_pages_count = len([p for p in pages if p.last_scanned_at])
            
        # Debug information
        print(f"[DEBUG] scan_details: scanned_count={scanned_count}, changed_pages_count={changed_pages_count}")
        print(f"[DEBUG] scan.started_at={scan.started_at}")
        if pages:
            print(f"[DEBUG] Sample page fields: last_scanned_at={pages[0].last_scanned_at}, last_modified={pages[0].last_modified}")
    except Exception as e:
        print(f"[DEBUG] Error calculating changed_pages_count: {e}")
        changed_pages_count = 0
    
    pages_with_holistic = []
    import json
    for page in pages:
        mcp_holistic = page.mcp_holistic
        if isinstance(mcp_holistic, str):
            try:
                mcp_holistic = json.loads(mcp_holistic)
            except Exception:
                mcp_holistic = None
        priority_label, priority_score = get_page_priority(page)
        pages_with_holistic.append({
            'id': page.id,
            'url': page.url,
            'status': page.status,
            'mcp_holistic': mcp_holistic,
            'priority_label': priority_label,
            'priority_score': priority_score,
            'doc_set_display': format_doc_set_name(page.doc_set)
        })
    pages_with_holistic.sort(key=lambda p: p['priority_score'], reverse=True)
    db.close()
    print("[DEBUG] pages_with_holistic:")
    pprint.pprint(pages_with_holistic)
    print(f"[DEBUG] scanned_count: {scanned_count}, flagged_count: {flagged_count}")
    bias_icon_map = {
        "Platform Bias": "💻",
        "Language Bias": "🗣️",
        "Geography Bias": "🌍",
        "Vendor Bias": "🏢",
        "OS Bias": "🐧",
        "Cloud Bias": "☁️",
    }
    return templates.TemplateResponse("scan_details.html", {
        "request": request,
        "scan": scan,
        "pages": pages_with_holistic,
        "scanned_count": scanned_count,
        "flagged_count": flagged_count,
        "flagged_pages": flagged_count,
        "changed_pages_count": changed_pages_count,
        "percent_flagged": round(percent_flagged, 1),
        "initial_progress": round(initial_progress, 1),
        "bias_icon_map": bias_icon_map,
        "user": current_user
    })

@router.get("/scan/{scan_id}/json")
async def scan_details_json(scan_id: int, request: Request, current_user: Optional[User] = Depends(get_current_user)):
    db = SessionLocal()
    scan = db.query(Scan).filter(Scan.id == scan_id).first()
    if not scan:
        db.close()
        raise HTTPException(status_code=404, detail="Scan not found")
    pages = db.query(Page).filter(Page.scan_id == scan.id).all()
    scanned_count = len(pages)
    flagged_pages = [p for p in pages if is_page_biased(p)]
    flagged_count = len(flagged_pages)
    percent_flagged = (flagged_count / scanned_count * 100) if scanned_count else 0
    
    # Calculate initial progress for the UI (using file-based counters for GitHub scans)
    initial_progress = 0
    if scan.total_files_queued and scan.total_files_queued > 0:
        initial_progress = (scan.total_files_completed / scan.total_files_queued) * 100
    elif scan.status == 'completed':
        initial_progress = 100
    
    # Calculate changed pages count
    changed_pages_count = 0
    try:
        # For now, let's use a simpler heuristic: count pages that were scanned in this scan
        # This gives us "freshly reviewed" pages which is useful for the user
        if pages:
            # Count all pages in this scan as "changed" since they're being freshly reviewed
            # In the future, we can enhance this with proper change detection
            changed_pages_count = len([p for p in pages if p.last_scanned_at])
            
        # Debug information
        print(f"[DEBUG] scan_details_json: scanned_count={scanned_count}, changed_pages_count={changed_pages_count}")
    except Exception as e:
        print(f"[DEBUG] Error calculating changed_pages_count in JSON: {e}")
        changed_pages_count = 0
    
    import json
    pages_with_holistic = []
    for page in pages:
        mcp_holistic = page.mcp_holistic
        if isinstance(mcp_holistic, str):
            try:
                mcp_holistic = json.loads(mcp_holistic)
            except Exception:
                mcp_holistic = None
        priority_label, priority_score = get_page_priority(page)
        pages_with_holistic.append({
            'id': page.id,
            'url': page.url,
            'status': page.status,
            'mcp_holistic': mcp_holistic,
            'priority_label': priority_label,
            'priority_score': priority_score,
            'doc_set_display': format_doc_set_name(page.doc_set)
        })
    pages_with_holistic.sort(key=lambda p: p['priority_score'], reverse=True)
    db.close()
    print(f"[DEBUG] pages_with_holistic for JSON: {pages_with_holistic}")
    bias_icon_map = {
        "Platform Bias": "💻",
        "Language Bias": "🗣️",
        "Geography Bias": "🌍",
        "Vendor Bias": "🏢",
        "OS Bias": "🐧",
        "Cloud Bias": "☁️",
    }
    html = templates.get_template("scan_details_partial.html").render({
        "request": request,
        "scan": scan,
        "pages": pages_with_holistic,
        "scanned_count": scanned_count,
        "flagged_count": flagged_count,
        "flagged_pages": flagged_count,
        "changed_pages_count": changed_pages_count,
        "percent_flagged": round(percent_flagged, 1),
        "initial_progress": round(initial_progress, 1),
        "bias_icon_map": bias_icon_map,
        "user": current_user
    })
    return JSONResponse({
        "html": html,
        "status": scan.status
    })

def enqueue_scan_task(url, scan_id, source, force_rescan=False):
    RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
    RABBITMQ_USERNAME = os.getenv("RABBITMQ_USERNAME", "guest")
    RABBITMQ_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "guest")
    print(f"[DEBUG] scan.py using RABBITMQ_HOST={RABBITMQ_HOST} for scan_tasks queue")
    
    credentials = pika.PlainCredentials(RABBITMQ_USERNAME, RABBITMQ_PASSWORD)
    connection = pika.BlockingConnection(pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        credentials=credentials
    ))
    channel = connection.channel()
    channel.queue_declare(queue='scan_tasks', durable=True)
    task_data = {
        "url": url,
        "scan_id": scan_id,
        "source": source,
        "force_rescan": force_rescan
    }
    message = json.dumps(task_data)
    print(f"[DEBUG] Enqueuing scan task: url={url}, scan_id={scan_id}, source={source}, force_rescan={force_rescan}")
    channel.basic_publish(
        exchange='',
        routing_key='scan_tasks',
        body=message,
        properties=pika.BasicProperties(delivery_mode=2)  # Persistent
    )
    queue_state = channel.queue_declare(queue='scan_tasks', passive=True)
    print(f"[DEBUG] scan_tasks queue message count after publish: {queue_state.method.message_count}")
    connection.close()
