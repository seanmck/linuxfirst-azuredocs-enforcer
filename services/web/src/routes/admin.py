from fastapi import APIRouter, Request, Form, HTTPException, Cookie, Query
from fastapi.responses import RedirectResponse, JSONResponse
from jinja_env import templates
from shared.utils.database import SessionLocal
from shared.models import Scan, Page, Snippet, UserFeedback, User, RewrittenDocument
from sqlalchemy import text, func, case, or_
from sqlalchemy.orm import joinedload
from datetime import datetime, timedelta
from typing import Optional
import os
import secrets
import hashlib
import pika
import json
import logging

router = APIRouter()

# Simple admin authentication
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")  # Change this in production
ADMIN_SESSION_SECRET = os.getenv("ADMIN_SESSION_SECRET", secrets.token_hex(32))

# Store active admin sessions using Redis for K8s HA setup
import redis
import json

def get_redis_client():
    """Get Redis client - try to connect to Redis, fallback to in-memory if not available"""
    try:
        redis_host = os.getenv("REDIS_HOST", "redis")
        redis_port = int(os.getenv("REDIS_PORT", "6379"))
        redis_password = os.getenv("REDIS_PASSWORD", None)
        
        # Try different hostnames in case of DNS issues
        hostnames_to_try = [
            redis_host,
            f"{redis_host}.azuredocs-app.svc.cluster.local",
            f"{redis_host}.azuredocs-app"
        ]
        
        for hostname in hostnames_to_try:
            try:
                logging.info(f"Attempting to connect to Redis at {hostname}:{redis_port}")
                client = redis.Redis(
                    host=hostname, 
                    port=redis_port, 
                    password=redis_password,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                    retry_on_timeout=True,
                    retry_on_error=[ConnectionError, TimeoutError]
                )
                # Test connection
                client.ping()
                logging.info(f"Successfully connected to Redis at {hostname}:{redis_port}")
                return client
            except Exception as e:
                logging.warning(f"Failed to connect to Redis at {hostname}: {e}")
                continue
        
        raise Exception("Could not connect to Redis with any hostname")
    except Exception as e:
        logging.warning(f"Redis not available ({e}), using in-memory sessions")
        return None

redis_client = get_redis_client()
logging.info(f"Redis client initialized: {redis_client is not None}")
if redis_client:
    logging.info("Successfully connected to Redis for session storage")
else:
    logging.warning("Redis not available - using in-memory session storage (will not work with multiple pods!)")

class SessionStorage:
    def __init__(self):
        self.memory_sessions = {}  # Fallback for when Redis is not available
        
    def set_session(self, token: str, created_at: datetime):
        if redis_client:
            try:
                # Store in Redis with 24 hour expiration
                redis_client.setex(
                    f"admin_session:{token}", 
                    86400,  # 24 hours in seconds
                    created_at.isoformat()
                )
                logging.info(f"Stored session {token[:16]}... in Redis")
                return
            except Exception as e:
                logging.error(f"Failed to store session in Redis: {e}")
        
        # Fallback to memory
        self.memory_sessions[token] = created_at
        logging.info(f"Stored session {token[:16]}... in memory (fallback)")
    
    def get_session(self, token: str):
        if redis_client:
            try:
                result = redis_client.get(f"admin_session:{token}")
                if result:
                    return datetime.fromisoformat(result)
                return None
            except Exception as e:
                logging.error(f"Failed to get session from Redis: {e}")
        
        # Fallback to memory
        return self.memory_sessions.get(token)
    
    def delete_session(self, token: str):
        if redis_client:
            try:
                redis_client.delete(f"admin_session:{token}")
                logging.info(f"Deleted session {token[:16]}... from Redis")
                return
            except Exception as e:
                logging.error(f"Failed to delete session from Redis: {e}")
        
        # Fallback to memory
        if token in self.memory_sessions:
            del self.memory_sessions[token]
            logging.info(f"Deleted session {token[:16]}... from memory")
    
    def get_all_sessions(self) -> dict:
        if redis_client:
            try:
                keys = redis_client.keys("admin_session:*")
                sessions = {}
                for key in keys:
                    token = key.replace("admin_session:", "")
                    created_at = redis_client.get(key)
                    if created_at:
                        sessions[token] = datetime.fromisoformat(created_at)
                return sessions
            except Exception as e:
                logging.error(f"Failed to get all sessions from Redis: {e}")
        
        # Fallback to memory
        return self.memory_sessions.copy()

session_storage = SessionStorage()

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def verify_admin_session(session_token: str = Cookie(None)) -> bool:
    if not session_token:
        logging.info("Session verification failed - no session token provided")
        all_sessions = session_storage.get_all_sessions()
        logging.info(f"All active sessions: {[k[:16] + '...' for k in all_sessions.keys()]}")
        return False
    
    session_time = session_storage.get_session(session_token)
    is_valid = session_time is not None
    logging.info(f"Session verification - token: {session_token[:16]}..., valid: {is_valid}")
    
    if is_valid:
        # Check if session is expired (Redis handles expiration automatically, but check for memory fallback)
        if datetime.utcnow() - session_time > timedelta(hours=24):
            logging.info(f"Session expired - removing token: {session_token[:16]}...")
            session_storage.delete_session(session_token)
            return False
    
    return is_valid

def create_admin_session() -> str:
    session_token = secrets.token_hex(32)
    created_at = datetime.utcnow()
    session_storage.set_session(session_token, created_at)
    
    logging.info(f"Created session {session_token[:16]}... at {created_at}")
    all_sessions = session_storage.get_all_sessions()
    logging.info(f"Session storage now contains: {len(all_sessions)} sessions")
    logging.info(f"Session keys: {[k[:16] + '...' for k in all_sessions.keys()]}")
    return session_token

def cleanup_expired_sessions():
    """Remove sessions older than 24 hours (Redis handles this automatically)"""
    if not redis_client:
        # Only need manual cleanup for memory fallback
        cutoff = datetime.utcnow() - timedelta(hours=24)
        all_sessions = session_storage.get_all_sessions()
        expired = [token for token, created in all_sessions.items() if created < cutoff]
        logging.info(f"Cleanup: Found {len(expired)} expired sessions out of {len(all_sessions)} total")
        for token in expired:
            logging.info(f"Removing expired session: {token[:16]}...")
            session_storage.delete_session(token)
        logging.info(f"Cleanup complete")
    else:
        logging.info("Redis handles session expiration automatically")

@router.get("/admin/login")
async def admin_login_page(request: Request):
    return templates.TemplateResponse("admin_login.html", {"request": request})

@router.get("/admin/debug")
async def admin_debug(request: Request, session_token: str = Cookie(None)):
    """Debug endpoint to check session status"""
    all_sessions = session_storage.get_all_sessions()
    
    return JSONResponse({
        "session_token": session_token,
        "session_token_length": len(session_token) if session_token else 0,
        "session_token_preview": session_token[:16] + "..." if session_token else None,
        "active_sessions_count": len(all_sessions),
        "active_sessions": [k[:16] + "..." for k in all_sessions.keys()],
        "session_valid": session_token in all_sessions if session_token else False,
        "redis_available": redis_client is not None,
        "storage_type": "Redis" if redis_client else "Memory",
        "all_cookies": dict(request.cookies)
    })

@router.post("/admin/login")
async def admin_login(request: Request, password: str = Form(...)):
    logging.info(f"Admin login attempt - Password length: {len(password)}")
    logging.info(f"Environment ADMIN_PASSWORD: '{ADMIN_PASSWORD}' (length: {len(ADMIN_PASSWORD)})")
    
    submitted_hash = hash_password(password)
    expected_hash = hash_password(ADMIN_PASSWORD)
    
    logging.info(f"Submitted password hash: {submitted_hash}")
    logging.info(f"Expected password hash: {expected_hash}")
    logging.info(f"Hash comparison result: {submitted_hash == expected_hash}")
    
    if submitted_hash == expected_hash:
        all_sessions_before = session_storage.get_all_sessions()
        logging.info(f"Before session creation - sessions count: {len(all_sessions_before)}")
        
        session_token = create_admin_session()
        
        all_sessions_after = session_storage.get_all_sessions()
        logging.info(f"After session creation - sessions count: {len(all_sessions_after)}")
        logging.info(f"Login successful, created session token: {session_token[:16]}...")
        logging.info(f"Session stored: {session_token in all_sessions_after}")
        logging.info(f"Storage type: {'Redis' if redis_client else 'Memory'}")
        
        # Verify the session was actually saved
        session_time = session_storage.get_session(session_token)
        logging.info(f"Session retrieval test: {session_time is not None}")
        
        # Create response with explicit redirect headers
        response = RedirectResponse(url="/admin", status_code=302)
        response.set_cookie(
            key="session_token", 
            value=session_token, 
            httponly=True, 
            max_age=86400,
            secure=False,  # Set to False for local development
            samesite="lax",  # Allow cross-site requests
            path="/"  # Make sure cookie is available on all paths
        )
        logging.info("Setting session cookie and redirecting to /admin")
        logging.info(f"Cookie details: session_token={session_token[:16]}..., httponly=True, max_age=86400")
        logging.info(f"Response status: {response.status_code}")
        logging.info(f"Response headers: {response.headers}")
        return response
    else:
        logging.warning("Login failed - password mismatch")
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
    logging.info(f"Admin dashboard access attempt - session token: {session_token[:16] if session_token else 'None'}...")
    all_sessions = session_storage.get_all_sessions()
    logging.info(f"Active sessions count: {len(all_sessions)}")
    logging.info(f"Storage type: {'Redis' if redis_client else 'Memory'}")
    logging.info(f"Request cookies: {dict(request.cookies)}")
    
    if session_token:
        logging.info(f"Session token received: {session_token[:16]}...")
        session_time = session_storage.get_session(session_token)
        logging.info(f"Session found in storage: {session_time is not None}")
        if session_time:
            age = datetime.utcnow() - session_time
            logging.info(f"Session age: {age.total_seconds()} seconds")
    
    if not verify_admin_session(session_token):
        logging.warning("Admin dashboard access denied - invalid or missing session")
        return RedirectResponse(url="/admin/login", status_code=302)
    
    logging.info("Admin dashboard access granted")
    cleanup_expired_sessions()
    db = SessionLocal()
    scans = db.query(Scan).order_by(Scan.started_at.desc()).limit(20).all()
    db.close()
    return templates.TemplateResponse("admin_dashboard.html", {
        "request": request,
        "scans": scans
    })

@router.post("/admin/scan")
async def admin_start_scan(request: Request, url: str = Form(""), scan_type: str = Form("manual"), force_rescan: bool = Form(False), session_token: str = Cookie(None)):
    if not os.environ.get("TEST_MODE") and not verify_admin_session(session_token):
        raise HTTPException(status_code=403, detail="Admin access required")
    url = url.strip()
    
    # Auto-detect source from URL
    from shared.utils.url_utils import detect_url_source
    source = detect_url_source(url) if url else "ms-learn"
    
    db = SessionLocal()
    new_scan = Scan(url=url or None, started_at=datetime.utcnow(), status="in_progress")
    db.add(new_scan)
    db.commit()
    db.refresh(new_scan)
    scan_id = new_scan.id
    db.close()
    # Import here to avoid circular import
    from .scan import enqueue_scan_task
    enqueue_scan_task(url if url else None, scan_id, source, force_rescan)
    return RedirectResponse(url=f"/scan/{scan_id}", status_code=302)

@router.post("/admin/schedule")
async def admin_schedule_scan(request: Request, schedule_type: str = Form(...), session_token: str = Cookie(None)):
    if not verify_admin_session(session_token):
        raise HTTPException(status_code=403, detail="Admin access required")
    # This would integrate with your scheduling system
    # For now, we'll just acknowledge the request
    return JSONResponse({"message": f"Scheduled {schedule_type} scan"})

@router.post("/admin/scan/{scan_id}/stop")
async def admin_stop_scan(scan_id: int, session_token: str = Cookie(None)):
    if not os.environ.get("TEST_MODE") and not verify_admin_session(session_token):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    db = SessionLocal()
    try:
        # Get the scan
        scan = db.query(Scan).filter(Scan.id == scan_id).first()
        if not scan:
            raise HTTPException(status_code=404, detail="Scan not found")
        
        # Check if scan can be stopped (must be in progress)
        if scan.status != 'in_progress':
            raise HTTPException(status_code=400, detail=f"Cannot stop scan with status '{scan.status}'")
        
        # Mark scan as cancelled in database
        scan.cancellation_requested = True
        scan.cancellation_requested_at = datetime.utcnow()
        scan.cancellation_reason = "Manually stopped by admin"
        scan.status = 'cancelled'
        db.commit()
        
        # Try to purge pending tasks from RabbitMQ queue
        try:
            # Get RabbitMQ connection details
            RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
            RABBITMQ_USERNAME = os.getenv("RABBITMQ_USERNAME", "guest")
            RABBITMQ_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "guest")
            
            credentials = pika.PlainCredentials(RABBITMQ_USERNAME, RABBITMQ_PASSWORD)
            connection = pika.BlockingConnection(pika.ConnectionParameters(
                host=RABBITMQ_HOST,
                credentials=credentials
            ))
            channel = connection.channel()
            
            # Purge tasks from both scan_tasks and doc_processing queues
            purged_scan_tasks_method = channel.queue_purge(queue='scan_tasks')
            purged_scan_tasks = purged_scan_tasks_method.method.message_count if hasattr(purged_scan_tasks_method, 'method') else 0
            
            purged_doc_tasks = 0
            try:
                purged_doc_tasks_method = channel.queue_purge(queue='doc_processing')
                purged_doc_tasks = purged_doc_tasks_method.method.message_count if hasattr(purged_doc_tasks_method, 'method') else 0
            except:
                pass  # Queue might not exist yet
            
            connection.close()
            
            return JSONResponse({
                "success": True,
                "message": f"Scan {scan_id} stopped successfully",
                "purged_tasks": {
                    "scan_tasks": purged_scan_tasks,
                    "doc_processing": purged_doc_tasks
                }
            })
        except Exception as queue_error:
            # Even if queue purging fails, the scan is still marked as cancelled
            return JSONResponse({
                "success": True,
                "message": f"Scan {scan_id} stopped (queue purging failed: {str(queue_error)})",
                "warning": "Some queued tasks may still be processed"
            })
            
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error stopping scan: {str(e)}")
    finally:
        db.close()

@router.post("/admin/wipe-database")
async def admin_wipe_database(request: Request, confirmation: str = Form(...), session_token: str = Cookie(None)):
    """
    Wipe all data from the database while preserving schema structure.
    Requires admin authentication and explicit confirmation.
    """
    if not os.environ.get("TEST_MODE") and not verify_admin_session(session_token):
        raise HTTPException(status_code=403, detail="Admin access required")
    
    # Require exact confirmation text
    if confirmation != "DELETE ALL DATA":
        raise HTTPException(status_code=400, detail="Invalid confirmation text")
    
    db = SessionLocal()
    try:
        # Log the database wipe action
        logging.warning(f"Database wipe initiated by admin at {datetime.utcnow()}")
        
        # Truncate tables in correct order (respecting foreign key constraints)
        # Start with child tables first, then parent tables
        db.execute(text("TRUNCATE TABLE snippets CASCADE"))
        db.execute(text("TRUNCATE TABLE pages CASCADE"))
        db.execute(text("TRUNCATE TABLE scans CASCADE"))
        
        # Reset any auto-increment sequences
        db.execute(text("ALTER SEQUENCE snippets_id_seq RESTART WITH 1"))
        db.execute(text("ALTER SEQUENCE pages_id_seq RESTART WITH 1"))
        db.execute(text("ALTER SEQUENCE scans_id_seq RESTART WITH 1"))
        
        db.commit()
        
        logging.info("Database successfully wiped - all data deleted, schema preserved")
        
        return JSONResponse({
            "success": True,
            "message": "Database wiped successfully. All data has been deleted while preserving the schema structure.",
            "timestamp": datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        db.rollback()
        logging.error(f"Database wipe failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database wipe failed: {str(e)}")
    finally:
        db.close()


def get_admin_feedback(
    db,
    page: int = 1,
    per_page: int = 25,
    target_type: Optional[str] = None,
    rating: Optional[str] = None,
    has_comment: Optional[str] = None,
    sort_by: str = "date",
    sort_order: str = "desc"
):
    """
    Query feedback with server-side pagination, filtering, and sorting.

    Args:
        db: Database session.
        page: Page number (1-indexed).
        per_page: Items per page (max 100).
        target_type: Filter by target type (``"snippet"``, ``"page"``, ``"rewritten"``).
        rating: Filter by rating (``"up"``, ``"down"``).
        has_comment: Filter by comment presence (``"yes"``, ``"no"``).
        sort_by: Sort field (e.g. ``"date"``, ``"rating"``).
        sort_order: Sort direction (``"asc"``, ``"desc"``).

    Returns:
        dict: A dictionary containing the feedback data and metadata with at least
            the following keys:

            - ``"items"``: A list of feedback records for the current page.
            - ``"pagination"``: A dictionary with pagination metadata, including:

                - ``"page"``: The current page number (1-indexed).
                - ``"per_page"``: The number of items per page.
                - ``"total_items"``: The total number of feedback records matching
                  the current filters.
                - ``"total_pages"``: The total number of pages available for the
                  current filters and ``per_page``.

            - ``"stats"``: A dictionary with aggregate statistics, including:

                - ``"total"``: Total number of feedback records matching the filters.
                - ``"up"``: Number of positive (up) ratings.
                - ``"down"``: Number of negative (down) ratings.
                - ``"with_comment"``: Number of feedback records that include a
                  non-empty comment.
    """
    # Validate and cap per_page
    per_page = min(max(1, per_page), 100)
    page = max(1, page)

    # Build base query with filters (to be shared by main query and stats query)
    base_query = db.query(UserFeedback)

    # Apply filters to base query
    if target_type:
        if target_type == "snippet":
            base_query = base_query.filter(UserFeedback.snippet_id.isnot(None))
        elif target_type == "page":
            base_query = base_query.filter(UserFeedback.page_id.isnot(None))
        elif target_type == "rewritten":
            base_query = base_query.filter(UserFeedback.rewritten_document_id.isnot(None))

    if rating:
        if rating == "up":
            base_query = base_query.filter(UserFeedback.rating.is_(True))
        elif rating == "down":
            base_query = base_query.filter(UserFeedback.rating.is_(False))

    if has_comment:
        if has_comment == "yes":
            base_query = base_query.filter(
                UserFeedback.comment.isnot(None),
                func.length(func.trim(UserFeedback.comment)) > 0
            )
        elif has_comment == "no":
            base_query = base_query.filter(
                or_(
                    UserFeedback.comment.is_(None),
                    func.length(func.trim(UserFeedback.comment)) == 0
                )
            )

    # Create main query from base query with eager loading
    query = base_query.options(
        joinedload(UserFeedback.user),
        joinedload(UserFeedback.snippet),
        joinedload(UserFeedback.page),
        joinedload(UserFeedback.rewritten_document)
    )

    # Apply sorting
    if sort_by == "rating":
        order_col = UserFeedback.rating
    else:  # default to date
        order_col = UserFeedback.created_at

    if sort_order == "asc":
        query = query.order_by(order_col.asc())
    else:
        query = query.order_by(order_col.desc())

    # Get total count (before pagination)
    total = query.count()
    total_pages = (total + per_page - 1) // per_page if total > 0 else 1

    # Apply pagination
    offset = (page - 1) * per_page
    feedback_items = query.offset(offset).limit(per_page).all()

    # Get stats using aggregation with the same filters applied via base_query
    stats_query = base_query.with_entities(
        func.count(UserFeedback.id).label('total'),
        func.sum(case((UserFeedback.rating.is_(True), 1), else_=0)).label('thumbs_up'),
        func.sum(case((UserFeedback.rating.is_(False), 1), else_=0)).label('thumbs_down'),
        func.sum(case((func.coalesce(func.length(func.trim(UserFeedback.comment)), 0) > 0, 1), else_=0)).label('has_comments')
    ).first()

    stats = {
        'total': stats_query.total or 0,
        'thumbs_up': stats_query.thumbs_up or 0,
        'thumbs_down': stats_query.thumbs_down or 0,
        'has_comments': stats_query.has_comments or 0
    }

    return {
        'items': feedback_items,
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total': total,
            'total_pages': total_pages,
            'has_prev': page > 1,
            'has_next': page < total_pages,
            'start_idx': offset + 1 if total > 0 else 0,
            'end_idx': min(offset + per_page, total)
        },
        'stats': stats
    }


@router.get("/admin/feedback")
async def admin_feedback_page(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    target_type: Optional[str] = Query(None),
    rating: Optional[str] = Query(None),
    has_comment: Optional[str] = Query(None),
    sort_by: str = Query("date"),
    sort_order: str = Query("desc"),
    session_token: str = Cookie(None)
):
    """Admin feedback viewer with filtering, sorting, and pagination."""
    if not verify_admin_session(session_token):
        return RedirectResponse(url="/admin/login", status_code=302)

    db = SessionLocal()
    try:
        result = get_admin_feedback(
            db=db,
            page=page,
            per_page=per_page,
            target_type=target_type,
            rating=rating,
            has_comment=has_comment,
            sort_by=sort_by,
            sort_order=sort_order
        )

        return templates.TemplateResponse("admin_feedback.html", {
            "request": request,
            "feedback_items": result['items'],
            "pagination": result['pagination'],
            "stats": result['stats'],
            "filters": {
                "target_type": target_type,
                "rating": rating,
                "has_comment": has_comment,
                "sort_by": sort_by,
                "sort_order": sort_order
            }
        })
    finally:
        db.close()
