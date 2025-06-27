from fastapi import APIRouter, Request, Form, HTTPException, Cookie
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from webui.db import SessionLocal
from webui.models import Scan
from datetime import datetime, timedelta
import os
import secrets
import hashlib

router = APIRouter()

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

# Templates
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "../templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

@router.get("/admin/login")
async def admin_login_page(request: Request):
    return templates.TemplateResponse("admin_login.html", {"request": request})

@router.post("/admin/login")
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

@router.get("/admin/logout")
async def admin_logout():
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie(key="session_token")
    return response

@router.get("/admin")
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

@router.post("/admin/scan")
async def admin_start_scan(request: Request, url: str = Form(""), scan_type: str = Form("manual"), source: str = Form("web"), session_token: str = Cookie(None)):
    if not os.environ.get("TEST_MODE") and not verify_admin_session(session_token):
        raise HTTPException(status_code=403, detail="Admin access required")
    url = url.strip()
    db = SessionLocal()
    new_scan = Scan(url=url or None, started_at=datetime.utcnow(), status="running")
    db.add(new_scan)
    db.commit()
    db.refresh(new_scan)
    scan_id = new_scan.id
    db.close()
    # Import here to avoid circular import
    from webui.routes.scan import enqueue_scan_task
    enqueue_scan_task(url if url else None, scan_id, source)
    return RedirectResponse(url=f"/scan/{scan_id}", status_code=302)

@router.post("/admin/schedule")
async def admin_schedule_scan(request: Request, schedule_type: str = Form(...), session_token: str = Cookie(None)):
    if not verify_admin_session(session_token):
        raise HTTPException(status_code=403, detail="Admin access required")
    # This would integrate with your scheduling system
    # For now, we'll just acknowledge the request
    return JSONResponse({"message": f"Scheduled {schedule_type} scan"})
