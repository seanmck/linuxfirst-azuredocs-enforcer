from fastapi import FastAPI, Request, Form, BackgroundTasks, HTTPException, Depends, Cookie, Body
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.concurrency import run_in_threadpool
from webui.db import SessionLocal
from webui.models import Scan, Page, Snippet
from fastapi.staticfiles import StaticFiles
import os
import asyncio
import json
import subprocess
import sys
import secrets
import hashlib
from collections import defaultdict
from datetime import datetime, timedelta
import schedule
import threading
import time
import pika
from scorer.llm_client import LLMClient
import requests
import re

app = FastAPI()

# Ensure the static directory path is absolute
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Ensure the templates directory path is absolute
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Simple admin authentication
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")  # Change this in production
ADMIN_SESSION_SECRET = os.getenv("ADMIN_SESSION_SECRET", secrets.token_hex(32))

# Store active admin sessions (in production, use Redis)
admin_sessions = {}

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def verify_admin_session(session_token: str = Cookie(None)) -> bool:
    if not session_token:
        return False
    return session_token in admin_sessions

def create_admin_session() -> str:
    session_token = secrets.token_hex(32)
    admin_sessions[session_token] = datetime.utcnow()
    return session_token

def cleanup_expired_sessions():
    """Remove sessions older than 24 hours"""
    cutoff = datetime.utcnow() - timedelta(hours=24)
    expired = [token for token, created in admin_sessions.items() if created < cutoff]
    for token in expired:
        del admin_sessions[token]

# Dependency for FastAPI endpoints
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def enqueue_scan_task(url, scan_id, source):
    RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
    print(f"[DEBUG] main.py using RABBITMQ_HOST={RABBITMQ_HOST} for scan_tasks queue")
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
    # Debug: show number of messages in the queue after publish
    queue_state = channel.queue_declare(queue='scan_tasks', passive=True)
    print(f"[DEBUG] scan_tasks queue message count after publish: {queue_state.method.message_count}")
    connection.close()

def build_flagged_tree(flagged):
    tree = {}
    for snip in flagged:
        url = snip['url']
        relpath = url.replace('https://learn.microsoft.com/en-us/azure/', '')
        path_parts = relpath.split('/')
        node = tree
        for i, segment in enumerate(path_parts):
            if i == len(path_parts) - 1:
                node.setdefault('__snippets__', []).append(snip)
            else:
                node = node.setdefault(segment, {})
    return tree

# Admin authentication endpoints
@app.get("/admin/login")
async def admin_login_page(request: Request):
    return templates.TemplateResponse("admin_login.html", {"request": request})

@app.post("/admin/login")
async def admin_login(request: Request, password: str = Form(...)):
    if hash_password(password) == hash_password(ADMIN_PASSWORD):
        session_token = create_admin_session()
        response = RedirectResponse(url="/admin", status_code=302)
        response.set_cookie(key="session_token", value=session_token, httponly=True, max_age=86400)
        return response
    else:
        return templates.TemplateResponse("admin_login.html", {
            "request": request, 
            "error": "Invalid password"
        })

@app.get("/admin/logout")
async def admin_logout():
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie(key="session_token")
    return response

@app.get("/admin")
async def admin_dashboard(request: Request, session_token: str = Cookie(None)):
    if not verify_admin_session(session_token):
        return RedirectResponse(url="/admin/login", status_code=302)
    
    cleanup_expired_sessions()
    
    db = SessionLocal()
    scans = db.query(Scan).order_by(Scan.started_at.desc()).limit(20).all()
    db.close()
    
    return templates.TemplateResponse("admin_dashboard.html", {
        "request": request,
        "scans": scans
    })

@app.post("/admin/scan")
async def admin_start_scan(request: Request, url: str = Form(""), scan_type: str = Form("manual"), source: str = Form("web"), session_token: str = Cookie(None)):
    print(f"[DEBUG] TEST_MODE={os.environ.get('TEST_MODE')}")
    # Allow unauthenticated access if TEST_MODE is set
    if not os.environ.get("TEST_MODE") and not verify_admin_session(session_token):
        raise HTTPException(status_code=403, detail="Admin access required")
    print(f"[DEBUG] /admin/scan API called: url={url}, scan_type={scan_type}, source={source}")
    url = url.strip()
    db = SessionLocal()
    new_scan = Scan(url=url or None, started_at=datetime.utcnow(), status="running")
    db.add(new_scan)
    db.commit()
    db.refresh(new_scan)
    scan_id = new_scan.id
    db.close()
    enqueue_scan_task(url if url else None, scan_id, source)
    return RedirectResponse(url=f"/scan/{scan_id}", status_code=302)

@app.post("/admin/schedule")
async def admin_schedule_scan(request: Request, schedule_type: str = Form(...), session_token: str = Cookie(None)):
    if not verify_admin_session(session_token):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    # This would integrate with your scheduling system
    # For now, we'll just acknowledge the request
    return JSONResponse({"message": f"Scheduled {schedule_type} scan"})

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    db = SessionLocal()
    # List all scans, most recent first
    scans = db.query(Scan).order_by(Scan.started_at.desc()).all()
    scan_summaries = []
    for scan in scans:
        # Get all pages for this scan
        pages = db.query(Page).filter(Page.scan_id == scan.id).all()
        scanned_count = len(pages)
        flagged_count = 0
        if scanned_count > 0:
            flagged_count = db.query(Page).join(Snippet).filter(Page.scan_id == scan.id, Snippet.llm_score["windows_biased"].as_boolean() == True).distinct(Page.id).count()
        percent_flagged = (flagged_count / scanned_count * 100) if scanned_count else 0
        scan_summaries.append({
            "id": scan.id,
            "url": scan.url,
            "started_at": scan.started_at,
            "status": scan.status,
            "percent_flagged": round(percent_flagged, 1),
            "scanned_count": scanned_count,
            "flagged_count": flagged_count
        })
    
    # Get the most recent flagged snippets across all scans
    recent_flagged_snippets = (
        db.query(Snippet)
        .join(Page)
        .join(Scan)
        .filter(Snippet.llm_score["windows_biased"].as_boolean() == True)
        .order_by(Scan.started_at.desc())
        .limit(10)
        .all()
    )
    
    # Format the flagged snippets for display
    formatted_snippets = []
    for snippet in recent_flagged_snippets:
        formatted_snippets.append({
            "scan_id": snippet.page.scan.id,
            "scan_started": snippet.page.scan.started_at,
            "page_url": snippet.page.url,
            "context": snippet.context,
            "code": snippet.code,
            "llm_score": snippet.llm_score
        })
    
    # Show the most recent completed scan's results by default
    scan = next((s for s in scans if s.status == "done"), None)
    last_result = None
    scan_status = False
    last_url = None
    if scan:
        scan_status = scan.status != "done"
        last_url = scan.url
        if scan.status == "done":
            snippets = (
                db.query(Snippet)
                .join(Page)
                .filter(Page.scan_id == scan.id)
                .all()
            )
            last_result = [
                {
                    "url": snip.page.url,
                    "context": snip.context,
                    "code": snip.code,
                    "llm_score": snip.llm_score
                }
                for snip in snippets
            ]
    db.close()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "last_result": last_result,
        "scan_status": scan_status,
        "last_url": last_url,
        "all_scans": scan_summaries,
        "scan_id": scan.id if scan else None,
        "recent_flagged_snippets": formatted_snippets
    })

@app.get("/status")
async def status():
    # Use scan_progress.json to determine if a scan is running
    progress_path = os.path.join("results", "scan_progress.json")
    running = False
    if os.path.exists(progress_path):
        with open(progress_path) as f:
            prog = json.load(f)
        # If the stage is not 'done', consider it running
        running = prog.get("stage") != "done"
    return JSONResponse({"running": running})

@app.get("/progress")
async def progress():
    db = SessionLocal()
    # Get the most recent scan (by started_at)
    scan = db.query(Scan).order_by(Scan.started_at.desc()).first()
    if not scan:
        db.close()
        return JSONResponse({"running": False, "flagged_snippets": []})
    
    running = scan.status != "done"
    
    # Get all pages for this scan
    pages = db.query(Page).filter(Page.scan_id == scan.id).all()
    scanned_urls = [p.url for p in pages]
    scanned_count = len(scanned_urls)
    
    # Get all snippets for this scan
    all_snippets = db.query(Snippet).join(Page).filter(Page.scan_id == scan.id).all()
    total_snippets = len(all_snippets)
    
    # Get flagged snippets (windows_biased==True) for this scan
    flagged_snippets = (
        db.query(Snippet)
        .join(Page)
        .filter(Page.scan_id == scan.id)
        .filter(Snippet.llm_score["windows_biased"].as_boolean() == True)
        .all()
    )
    flagged_count = len(flagged_snippets)
    flagged_pages = len(set(s.page.url for s in flagged_snippets))
    percent_flagged = (flagged_pages / scanned_count * 100) if scanned_count else 0
    
    # Serialize flagged snippets for JSON
    flagged_serialized = []
    for snip in flagged_snippets:
        flagged_serialized.append({
            "url": snip.page.url,
            "context": snip.context,
            "code": snip.code,
            "llm_score": snip.llm_score
        })
    
    # Find the most recent page being processed (if any)
    current_url = None
    if running:
        # Try to find the last page with status not 'done'
        in_progress = db.query(Page).filter(Page.scan_id == scan.id, Page.status != 'done').order_by(Page.id.desc()).first()
        if in_progress:
            current_url = in_progress.url
        elif scanned_urls:
            current_url = scanned_urls[-1]
    
    db.close()
    
    return JSONResponse({
        "running": running,
        "stage": scan.status,
        "scanned": scanned_count,
        "total_snippets": total_snippets,
        "flagged": flagged_count,
        "flagged_pages": flagged_pages,
        "percent_flagged": round(percent_flagged, 1),
        "scanned_urls": scanned_urls,
        "flagged_snippets": flagged_serialized,
        "current_url": current_url
    })

# Background scheduler for automated scans
def run_scheduled_scan():
    """Run a scheduled scan of the full Azure docs"""
    print(f"[SCHEDULER] Starting scheduled scan at {datetime.utcnow()}")
    # Create a new scan in the DB and enqueue it
    db = SessionLocal()
    new_scan = Scan(url=None, started_at=datetime.utcnow(), status="running")
    db.add(new_scan)
    db.commit()
    db.refresh(new_scan)
    scan_id = new_scan.id
    db.close()
    enqueue_scan_task(None, scan_id)

def start_scheduler():
    """Start the background scheduler"""
    # Schedule daily scan at 2 AM UTC
    schedule.every().day.at("02:00").do(run_scheduled_scan)
    
    while True:
        schedule.run_pending()
        time.sleep(60)

# Start scheduler in background thread
scheduler_thread = threading.Thread(target=start_scheduler, daemon=True)
scheduler_thread.start()

@app.get("/scan/{scan_id}")
async def scan_details(scan_id: int, request: Request):
    """Endpoint to display details of a specific scan."""
    db = SessionLocal()
    scan = db.query(Scan).filter(Scan.id == scan_id).first()
    
    if not scan:
        db.close()
        raise HTTPException(status_code=404, detail="Scan not found")

    # Get all snippets for this scan
    snippets = (
        db.query(Snippet)
        .join(Page)
        .filter(Page.scan_id == scan.id)
        .all()
    )
    
    # Get flagged snippets (windows_biased==True)
    flagged_snippets = (
        db.query(Snippet)
        .join(Page)
        .filter(Page.scan_id == scan.id)
        .filter(Snippet.llm_score["windows_biased"].as_boolean() == True)
        .all()
    )
    
    # Get all pages for this scan
    pages = db.query(Page).filter(Page.scan_id == scan.id).all()
    scanned_count = len(pages)
    flagged_count = len(flagged_snippets)
    flagged_pages = len(set(s.page.url for s in flagged_snippets))
    percent_flagged = (flagged_pages / scanned_count * 100) if scanned_count else 0
    
    # Organize snippets by page for the template
    pages_with_snippets = []
    for page in pages:
        page_snippets = [s for s in snippets if s.page_id == page.id]
        flagged_page_snippets = [s for s in flagged_snippets if s.page_id == page.id]
        pages_with_snippets.append({
            'url': page.url,
            'status': page.status,
            'snippets': page_snippets,
            'flagged_snippets': flagged_page_snippets,
            'has_flagged': len(flagged_page_snippets) > 0
        })
    
    db.close()
    
    return templates.TemplateResponse("scan_details.html", {
        "request": request,
        "scan": scan,
        "pages": pages_with_snippets,
        "flagged_snippets": flagged_snippets,
        "scanned_count": scanned_count,
        "flagged_count": flagged_count,
        "flagged_pages": flagged_pages,
        "percent_flagged": round(percent_flagged, 1)
    })

@app.get("/scan/{scan_id}/json")
async def scan_details_json(scan_id: int, request: Request):
    """Endpoint to provide scan details as HTML partial for AJAX polling."""
    db = SessionLocal()
    scan = db.query(Scan).filter(Scan.id == scan_id).first()
    if not scan:
        db.close()
        raise HTTPException(status_code=404, detail="Scan not found")

    snippets = (
        db.query(Snippet)
        .join(Page)
        .filter(Page.scan_id == scan.id)
        .all()
    )
    flagged_snippets = (
        db.query(Snippet)
        .join(Page)
        .filter(Page.scan_id == scan.id)
        .filter(Snippet.llm_score["windows_biased"].as_boolean() == True)
        .all()
    )
    pages = db.query(Page).filter(Page.scan_id == scan.id).all()
    scanned_count = len(pages)
    flagged_count = len(flagged_snippets)
    flagged_pages = len(set(s.page.url for s in flagged_snippets))
    percent_flagged = (flagged_pages / scanned_count * 100) if scanned_count else 0
    pages_with_snippets = []
    for page in pages:
        page_snippets = [s for s in snippets if s.page_id == page.id]
        flagged_page_snippets = [s for s in flagged_snippets if s.page_id == page.id]
        pages_with_snippets.append({
            'url': page.url,
            'status': page.status,
            'snippets': page_snippets,
            'flagged_snippets': flagged_page_snippets,
            'has_flagged': len(flagged_page_snippets) > 0
        })
    db.close()
    html = templates.get_template("scan_details_partial.html").render({
        "request": request,
        "scan": scan,
        "pages": pages_with_snippets,
        "flagged_snippets": flagged_snippets,
        "scanned_count": scanned_count,
        "flagged_count": flagged_count,
        "flagged_pages": flagged_pages,
        "percent_flagged": round(percent_flagged, 1)
    })
    return JSONResponse({
        "html": html,
        "status": scan.status
    })

@app.post("/suggest_linux_pr")
async def suggest_linux_pr(request: Request, body: dict = Body(...)):
    url = body.get('url')
    print(f"[DEBUG] /suggest_linux_pr called with url: {url}")
    if not url:
        print("[DEBUG] No URL provided in request body.")
        return JSONResponse({"error": "Missing URL"}, status_code=400)
    # Fetch the full doc content
    doc_content = None
    try:
        if 'github.com' in url and '/blob/' in url:
            raw_url = url.replace('github.com', 'raw.githubusercontent.com').replace('/blob/', '/')
            print(f"[DEBUG] Fetching raw markdown from: {raw_url}")
            resp = requests.get(raw_url)
            if resp.status_code == 200:
                doc_content = resp.text
            else:
                print(f"[DEBUG] Failed to fetch raw markdown: {resp.status_code}")
        else:
            print(f"[DEBUG] Fetching HTML from: {url}")
            resp = requests.get(url)
            if resp.status_code == 200:
                doc_content = resp.text
            else:
                print(f"[DEBUG] Failed to fetch HTML: {resp.status_code}")
    except Exception as e:
        print(f"[DEBUG] Exception during doc fetch: {e}")
    if not doc_content:
        return JSONResponse({"error": "Failed to fetch document content."}, status_code=500)

    # Preprocess: Move YAML frontmatter to the end (if present)
    frontmatter_match = re.match(r'(?s)^---\n(.*?)\n---\n(.*)', doc_content)
    if frontmatter_match:
        frontmatter = frontmatter_match.group(1)
        markdown_body = frontmatter_match.group(2)
        processed_content = f"# The following is the full markdown page (YAML frontmatter moved to end):\n\n{markdown_body}\n\n---\n{frontmatter}\n---"
        print("[DEBUG] YAML frontmatter detected and moved to end.")
    else:
        processed_content = f"# The following is the full markdown page:\n\n{doc_content}"
        print("[DEBUG] No YAML frontmatter detected.")

    # Stricter, longer prompt with realistic example
    prompt = (
        "You are an expert in cross-platform technical documentation.\n"
        "\n"
        "TASK: Rewrite the following documentation page to make it Linux-first.\n"
        "- Add or improve Linux/az CLI/bash examples.\n"
        "- Clarify platform-specific instructions.\n"
        "- Ensure parity between Windows and Linux instructions.\n"
        "- DO NOT provide any advice, explanation, or summary.\n"
        "- DO NOT output anything except the full revised page in markdown.\n"
        "- DO NOT output analysis or meta-comments.\n"
        "- Output ONLY the full revised page, wrapped in triple backticks (```).\n"
        "\n"
        "EXAMPLE:\n"
        "Original:\n"
        "---\n"
        "title: 'Create a resource group'\n"
        "ms.date: 01/01/2024\n"
        "---\n"
        "\n"
        "# Create a resource group (PowerShell)\n"
        "$rg = New-AzResourceGroup -Name 'myResourceGroup' -Location 'eastus'\n"
        "\n"
        "Revised:\n"
        "```\n"
        "---\n"
        "title: 'Create a resource group'\n"
        "ms.date: 01/01/2024\n"
        "---\n"
        "\n"
        "# Create a resource group (PowerShell)\n"
        "$rg = New-AzResourceGroup -Name 'myResourceGroup' -Location 'eastus'\n"
        "\n"
        "# Create a resource group (Azure CLI)\n"
        "az group create --name myResourceGroup --location eastus\n"
        "```\n"
        "\n"
        "Now, here is the page to revise:\n"
        f"{processed_content}"
    )
    llm = LLMClient()
    try:
        print(f"[DEBUG] Sending prompt to LLM (length: {len(prompt)} chars)")
        suggestion = llm.score_snippet({'code': prompt, 'context': ''})
        raw_response = suggestion.get('suggested_linux_alternative') or suggestion.get('explanation') or str(suggestion)
        match = re.search(r'```(?:markdown)?\n([\s\S]+?)```', raw_response)
        if match:
            proposed = match.group(1).strip()
            print(f"[DEBUG] Extracted markdown content from LLM response (length: {len(proposed)} chars)")
        else:
            proposed = raw_response
            print(f"[DEBUG] No code block found in LLM response; using full response (length: {len(proposed)} chars)")
    except Exception as e:
        proposed = f"Error generating suggestion: {e}"
        print(f"[DEBUG] Exception during LLM call: {e}")
    return JSONResponse({"original": doc_content, "proposed": proposed})

@app.get("/proposed_change", response_class=HTMLResponse)
async def proposed_change(request: Request):
    """Render the diff view for a proposed Linux-first doc change."""
    return templates.TemplateResponse("proposed_change.html", {"request": request})
