from fastapi import FastAPI, Request, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
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

app = FastAPI()
app.mount("/static", StaticFiles(directory="webui/static"), name="static")
templates = Jinja2Templates(directory="webui/templates")

# Dependency for FastAPI endpoints
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def run_orchestrator_sync(url=None):
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    cmd = [sys.executable, "orchestrator.py"]
    if url:
        cmd.append(url)
    # Ensure results/ directory exists before starting scan
    results_dir = os.path.join(project_root, "results")
    os.makedirs(results_dir, exist_ok=True)
    # Remove old scan_progress.json so UI doesn't see stale progress
    progress_path = os.path.join(results_dir, "scan_progress.json")
    if os.path.exists(progress_path):
        os.remove(progress_path)
    # Set environment so orchestrator.py always writes to the correct results/ dir
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"  # Ensure immediate file writes
    subprocess.Popen(cmd, cwd=project_root, env=env)

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    db = SessionLocal()
    # Get the most recent completed scan
    scan = db.query(Scan).order_by(Scan.started_at.desc()).first()
    last_result = None
    scan_status = False
    if scan:
        scan_status = scan.status != "done"
        if scan.status == "done":
            # Get all snippets for this scan
            snippets = (
                db.query(Snippet)
                .join(Page)
                .filter(Page.scan_id == scan.id)
                .all()
            )
            # Serialize for template
            last_result = [
                {
                    "url": snip.page.url,
                    "context": snip.context,
                    "code": snip.code,
                    "llm_score": snip.llm_score
                }
                for snip in snippets
            ]
        else:
            last_result = None  # Hide results if scan is running
    db.close()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "last_result": last_result,
        "scan_status": scan_status
    })

@app.post("/scan")
async def scan(url: str = Form("")):
    url = url.strip()
    run_orchestrator_sync(url if url else None)
    return HTMLResponse('<meta http-equiv="refresh" content="0; url=/">')

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
    # Get all flagged snippets (windows_biased==True) for this scan
    flagged_snippets = (
        db.query(Snippet)
        .join(Page)
        .filter(Page.scan_id == scan.id)
        .filter(Snippet.llm_score["windows_biased"].as_boolean() == True)
        .all()
    )
    flagged_count = len(set(s.page.url for s in flagged_snippets))
    percent_flagged = (flagged_count / scanned_count * 100) if scanned_count else 0
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
        "flagged": flagged_count,
        "percent_flagged": round(percent_flagged, 1),
        "scanned_urls": scanned_urls,
        "flagged_snippets": flagged_serialized,
        "current_url": current_url
    })
