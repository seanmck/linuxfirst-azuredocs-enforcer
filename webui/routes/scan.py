from fastapi import APIRouter, Request, HTTPException, Cookie
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from webui.db import SessionLocal
from webui.models import Scan, Page, Snippet
from datetime import datetime
import os
import requests
import pprint
import pika
import json

router = APIRouter()

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "../templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

def get_priority_label_and_score(mcp_holistic):
    if not mcp_holistic:
        return ("Low", 1)
    bias_types = mcp_holistic.get('bias_types')
    if isinstance(bias_types, str):
        bias_types = [bias_types]
    if not bias_types or not isinstance(bias_types, list):
        return ("Low", 1)
    n_bias = len(bias_types)
    if n_bias >= 3:
        return ("High", 3)
    elif n_bias == 2:
        return ("Medium", 2)
    elif n_bias == 1:
        return ("Low", 1)
    else:
        return ("Low", 1)

@router.get("/scan/{scan_id}")
async def scan_details(scan_id: int, request: Request):
    db = SessionLocal()
    scan = db.query(Scan).filter(Scan.id == scan_id).first()
    if not scan:
        db.close()
        raise HTTPException(status_code=404, detail="Scan not found")
    pages = db.query(Page).filter(Page.scan_id == scan.id).all()
    scanned_count = len(pages)
    flagged_pages = [p for p in pages if p.mcp_holistic and p.mcp_holistic.get('bias_types')]
    flagged_count = len(flagged_pages)
    percent_flagged = (flagged_count / scanned_count * 100) if scanned_count else 0
    pages_with_holistic = []
    import json
    for page in pages:
        mcp_holistic = page.mcp_holistic
        if isinstance(mcp_holistic, str):
            try:
                mcp_holistic = json.loads(mcp_holistic)
            except Exception:
                mcp_holistic = None
        priority_label, priority_score = get_priority_label_and_score(mcp_holistic)
        pages_with_holistic.append({
            'id': page.id,
            'url': page.url,
            'status': page.status,
            'mcp_holistic': mcp_holistic,
            'priority_label': priority_label,
            'priority_score': priority_score
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
        "percent_flagged": round(percent_flagged, 1),
        "bias_icon_map": bias_icon_map
    })

@router.get("/scan/{scan_id}/json")
async def scan_details_json(scan_id: int, request: Request):
    db = SessionLocal()
    scan = db.query(Scan).filter(Scan.id == scan_id).first()
    if not scan:
        db.close()
        raise HTTPException(status_code=404, detail="Scan not found")
    pages = db.query(Page).filter(Page.scan_id == scan.id).all()
    scanned_count = len(pages)
    flagged_pages = [p for p in pages if p.mcp_holistic and (p.mcp_holistic.get('bias_types') if isinstance(p.mcp_holistic, dict) else False)]
    flagged_count = len(flagged_pages)
    percent_flagged = (flagged_count / scanned_count * 100) if scanned_count else 0
    import json
    pages_with_holistic = []
    for page in pages:
        mcp_holistic = page.mcp_holistic
        if isinstance(mcp_holistic, str):
            try:
                mcp_holistic = json.loads(mcp_holistic)
            except Exception:
                mcp_holistic = None
        priority_label, priority_score = get_priority_label_and_score(mcp_holistic)
        pages_with_holistic.append({
            'id': page.id,
            'url': page.url,
            'status': page.status,
            'mcp_holistic': mcp_holistic,
            'priority_label': priority_label,
            'priority_score': priority_score
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
        "percent_flagged": round(percent_flagged, 1),
        "bias_icon_map": bias_icon_map
    })
    return JSONResponse({
        "html": html,
        "status": scan.status
    })

def enqueue_scan_task(url, scan_id, source):
    RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
    print(f"[DEBUG] scan.py using RABBITMQ_HOST={RABBITMQ_HOST} for scan_tasks queue")
    connection = pika.BlockingConnection(pika.ConnectionParameters(RABBITMQ_HOST))
    channel = connection.channel()
    channel.queue_declare(queue='scan_tasks')
    task_data = {
        "url": url,
        "scan_id": scan_id,
        "source": source
    }
    message = json.dumps(task_data)
    print(f"[DEBUG] Enqueuing scan task: url={url}, scan_id={scan_id}, source={source}")
    channel.basic_publish(exchange='', routing_key='scan_tasks', body=message)
    queue_state = channel.queue_declare(queue='scan_tasks', passive=True)
    print(f"[DEBUG] scan_tasks queue message count after publish: {queue_state.method.message_count}")
    connection.close()
