from fastapi import FastAPI, Request, Form, BackgroundTasks, HTTPException, Depends, Cookie, Body, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
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
import httpx
from markdown import markdown as md_lib
from webui.routes import admin, scan, llm
from webui.routes.scan import enqueue_scan_task
from webui.jinja_env import templates

app = FastAPI()

# Ensure the static directory path is absolute
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Register markdown filter for Jinja2

def markdown_filter(text):
    return md_lib(text or "")

templates.env.filters['markdown'] = markdown_filter

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
    # Prepare data for bias rate chart
    try:
        import jinja2
    except ImportError:
        jinja2 = None
    bias_chart_data = []
    for scan in reversed(scan_summaries):
        started_at = scan.get("started_at")
        percent_flagged = scan.get("percent_flagged")
        scanned_count = scan.get("scanned_count")
        status = scan.get("status")
        if status == "done" and scanned_count and started_at is not None and percent_flagged is not None:
            if jinja2 and (isinstance(started_at, getattr(jinja2, 'Undefined', type(None))) or isinstance(percent_flagged, getattr(jinja2, 'Undefined', type(None)))):
                print(f"[DEBUG] Skipping scan {scan.get('id')} due to Undefined value.")
                continue
            if not hasattr(started_at, 'strftime'):
                print(f"[DEBUG] Skipping scan {scan.get('id')} due to started_at not being datetime.")
                continue
            try:
                bias_chart_data.append({
                    "date": started_at.strftime("%Y-%m-%d %H:%M"),
                    "percent_flagged": float(percent_flagged)
                })
            except Exception as e:
                print(f"[WARN] Skipping scan {scan.get('id')} in chart data due to error: {e}")
        else:
            print(f"[DEBUG] Skipping scan {scan.get('id')} for chart: status={status}, scanned_count={scanned_count}, started_at={started_at}, percent_flagged={percent_flagged}")
    if not bias_chart_data or any([d is None for d in bias_chart_data]):
        bias_chart_data = []
    # Use the Scan ORM object for scan_id and last_url, not the dict
    scan_obj = next((s for s in scans if hasattr(s, 'status') and s.status == "done"), None)
    
    # Fetch Azure Docs directories from GitHub API
    azure_dirs = []
    try:
        resp = requests.get(
            "https://api.github.com/repos/MicrosoftDocs/azure-docs/contents/articles",
            headers={"User-Agent": "linuxfirst-azuredocs-enforcer-dashboard"}
        )
        print(f"[DEBUG] GitHub API status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(f"[DEBUG] GitHub API returned {len(data)} items")
            # Only include directories
            azure_dirs = [item for item in data if item.get('type') == 'dir']
            print(f"[DEBUG] azure_dirs: {[d['name'] for d in azure_dirs]}")
        else:
            print(f"[WARN] Failed to fetch Azure Docs directories: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"[WARN] Exception fetching Azure Docs directories: {e}")
        # Fallback for testing
        azure_dirs = [
            {"name": "test-dir-1", "html_url": "https://github.com/MicrosoftDocs/azure-docs/tree/main/articles/test-dir-1"},
            {"name": "test-dir-2", "html_url": "https://github.com/MicrosoftDocs/azure-docs/tree/main/articles/test-dir-2"}
        ]

    return templates.TemplateResponse("index.html", {
        "request": request,
        "last_result": last_result,
        "scan_status": scan_status,
        "last_url": getattr(scan_obj, 'url', None) if scan_obj else None,
        "all_scans": scan_summaries,
        "scan_id": getattr(scan_obj, 'id', None) if scan_obj else None,
        "recent_flagged_snippets": formatted_snippets,
        "bias_chart_data": bias_chart_data,
        "azure_dirs": azure_dirs
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
    enqueue_scan_task(None, scan_id, "scheduler")

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

app.include_router(admin.router)
app.include_router(scan.router)
app.include_router(llm.router)
