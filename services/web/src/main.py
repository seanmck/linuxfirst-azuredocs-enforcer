from fastapi import FastAPI, Request, Form, BackgroundTasks, HTTPException, Depends, Cookie, Body, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import text
from shared.utils.database import SessionLocal
from shared.models import Scan, Page, Snippet, BiasSnapshot
from fastapi.staticfiles import StaticFiles
import os
import asyncio
import json
import subprocess
import sys
import secrets
import hashlib
from collections import defaultdict
from datetime import datetime, timedelta, date
import time
import pika
from packages.scorer.llm_client import LLMClient
import requests
import httpx
from functools import lru_cache
from routes import admin, scan, llm, websocket, docset, auth, feedback, docpage
from routes.scan import enqueue_scan_task
from shared.utils.url_utils import extract_doc_set_from_url, format_doc_set_name
from shared.config import AZURE_DOCS_REPOS
from jinja_env import templates
from middleware.metrics import PrometheusMiddleware, create_metrics_endpoint
from middleware.security import SecurityMiddleware
from middleware.correlation import CorrelationMiddleware
from shared.utils.metrics import get_metrics
from shared.utils.tracing import setup_tracing
from shared.utils.database import engine
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()


# Middleware is processed in reverse order of addition (last added = first to process)
# Order of processing: Correlation -> Security -> Prometheus

# Add Prometheus metrics middleware
app.add_middleware(PrometheusMiddleware, service_name="webui")

# Add security middleware (rate limiting, DDoS protection)
app.add_middleware(
    SecurityMiddleware,
    rate_limit_per_minute=120,  # Increased limit
    block_duration_minutes=5   # Reduced block time
)

# Add correlation ID middleware first (outermost - processes requests first)
app.add_middleware(CorrelationMiddleware)

# Initialize metrics
metrics = get_metrics()
metrics.set_service_health("webui", True)

# Initialize distributed tracing (only if OTEL_EXPORTER_OTLP_ENDPOINT is set)
setup_tracing(app=app, db_engine=engine)

# Ensure the static directory path is absolute
# In Docker: static files are at /app/web/static (working dir is /app/web)
# In local dev: services/web/static, while this file is at services/web/src/main.py
if os.path.exists("static"):
    # Docker environment - static directory is relative to working directory
    STATIC_DIR = os.path.abspath("static")
else:
    # Local development - static directory is one level up from src
    STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")


class CachedStaticFiles(StaticFiles):
    """StaticFiles with Cache-Control headers for improved performance."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        # Add cache headers for static assets (1 day for versioned/immutable assets)
        if path.endswith(('.css', '.js', '.png', '.jpg', '.jpeg', '.ico', '.woff2', '.woff', '.ttf')):
            response.headers['Cache-Control'] = 'public, max-age=86400'  # 1 day
        return response


print(f"[DEBUG] Static directory: {STATIC_DIR}")
print(f"[DEBUG] Static directory exists: {os.path.exists(STATIC_DIR)}")
app.mount("/static", CachedStaticFiles(directory=STATIC_DIR), name="static")


# Health check endpoints for Kubernetes probes and monitoring
@app.get("/health")
async def health_check():
    """Liveness probe - is the service running?"""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.get("/readiness")
async def readiness_check():
    """Readiness probe - can the service handle requests?"""
    db = SessionLocal()
    try:
        # Quick database connectivity check
        db.execute(text("SELECT 1"))
        db_healthy = True
    except Exception:
        db_healthy = False
    finally:
        db.close()

    return {
        "status": "ready" if db_healthy else "not_ready",
        "database": "connected" if db_healthy else "disconnected",
        "timestamp": datetime.utcnow().isoformat()
    }


# Register additional Jinja2 filters (markdown, truncate_url, url_to_title are in jinja_env.py)

def format_doc_set_name_filter(doc_set):
    """Jinja2 filter wrapper for format_doc_set_name."""
    return format_doc_set_name(doc_set) if doc_set else 'Unknown'

templates.env.filters['format_doc_set_name'] = format_doc_set_name_filter

def url_to_title_filter(url):
    """Extract a human-readable title from a GitHub docs URL.

    Example:
    https://github.com/MicrosoftDocs/azure-docs/blob/main/articles/active-directory-b2c/access-tokens.md
    → "Active Directory B2C: Access Tokens"
    """
    if not url:
        return "Untitled Page"

    try:
        # Extract the path after /articles/ or similar patterns
        path_match = re.search(r'/articles/([^/]+)/([^/]+?)(?:\.md)?$', url)
        if path_match:
            folder = path_match.group(1)
            filename = path_match.group(2)

            # Convert kebab-case to Title Case
            def to_title(s):
                # Handle common acronyms
                acronyms = {'b2c', 'b2b', 'api', 'sdk', 'cli', 'sql', 'vm', 'vms', 'aks', 'acr', 'dns', 'ssl', 'tls', 'ssh', 'rbac', 'aad', 'arm'}
                words = s.replace('-', ' ').replace('_', ' ').split()
                titled = []
                for word in words:
                    if word.lower() in acronyms:
                        titled.append(word.upper())
                    else:
                        titled.append(word.capitalize())
                return ' '.join(titled)

            folder_title = to_title(folder)
            file_title = to_title(filename)

            # Avoid redundancy if folder and file have similar names
            if file_title.lower().startswith(folder_title.lower().split()[0].lower()):
                return file_title

            return f"{folder_title}: {file_title}"

        # Fallback: just get the last path segment
        parts = url.rstrip('/').split('/')
        filename = parts[-1] if parts else url
        filename = re.sub(r'\.md$', '', filename)
        return filename.replace('-', ' ').replace('_', ' ').title()

    except Exception:
        return url

templates.env.filters['url_to_title'] = url_to_title_filter

# Admin authentication is now handled in webui/routes/admin.py

# Simple cache for expensive operations
class SimpleCache:
    def __init__(self):
        self.cache = {}
    
    def get(self, key):
        if key in self.cache:
            value, expiry = self.cache[key]
            if datetime.utcnow() < expiry:
                return value
            else:
                del self.cache[key]
        return None
    
    def set(self, key, value, ttl_minutes=5):
        expiry = datetime.utcnow() + timedelta(minutes=ttl_minutes)
        self.cache[key] = (value, expiry)
    
    def clear(self):
        self.cache.clear()

# Global cache instance
cache = SimpleCache()

# Admin authentication functions moved to webui/routes/admin.py

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

def get_doc_set_leaderboard(db):
    """
    Get bias metrics aggregated by documentation set (e.g., virtual-machines, app-service).
    Returns a list of doc sets with their bias statistics from all scans (including in-progress).
    Uses efficient aggregation queries for better performance.
    """
    from sqlalchemy import func, case, text
    
    # Check cache first
    cache_key = "doc_set_leaderboard_all_scans"
    cached_result = cache.get(cache_key)
    if cached_result is not None:
        print(f"[DEBUG] Using cached leaderboard data")
        return cached_result
    
    # Single optimized query to get doc set statistics
    # This replaces the O(scans × pages × snippets) nested loop approach
    query = text("""
        WITH doc_set_pages AS (
            SELECT 
                p.url,
                p.id as page_id,
                CASE 
                    WHEN position('/articles/' in p.url) > 0 THEN
                        split_part(
                            substring(p.url from position('/articles/' in p.url) + 10),
                            '/', 
                            1
                        )
                    ELSE NULL
                END as doc_set,
                -- Check if page needs attention based on bias_types in mcp_holistic
                CASE 
                    WHEN p.mcp_holistic IS NOT NULL 
                    AND jsonb_array_length(COALESCE(p.mcp_holistic->'bias_types', '[]'::jsonb)) > 0 
                    THEN true
                    ELSE false
                END as is_biased
            FROM pages p
            JOIN scans sc ON p.scan_id = sc.id
            WHERE p.url LIKE '%/articles/%'
        ),
        doc_set_aggregates AS (
            SELECT 
                doc_set,
                COUNT(DISTINCT url) as total_pages,
                COUNT(DISTINCT CASE WHEN is_biased THEN url END) as biased_pages
            FROM doc_set_pages
            WHERE doc_set IS NOT NULL AND doc_set != ''
            GROUP BY doc_set
        )
        SELECT 
            doc_set,
            total_pages,
            biased_pages,
            CAST(
                ROUND(
                    CASE 
                        WHEN total_pages > 0 THEN (biased_pages::numeric / total_pages::numeric * 100)
                        ELSE 0
                    END,
                    1
                ) AS FLOAT
            ) as bias_percentage
        FROM doc_set_aggregates
        WHERE total_pages > 0
        ORDER BY bias_percentage DESC, total_pages DESC
    """)
    
    try:
        result = db.execute(query).fetchall()
        print(f"[DEBUG] Found {len(result)} doc sets with data")
        
        # Convert to list of dicts with display names
        leaderboard = []
        for row in result:
            doc_set, total_pages, biased_pages, bias_percentage = row
            leaderboard.append({
                'doc_set': doc_set,
                'display_name': format_doc_set_name(doc_set),
                'total_pages': total_pages,
                'biased_pages': biased_pages,
                'bias_percentage': float(bias_percentage)
            })
        
        # Debug output for first few entries
        for i, entry in enumerate(leaderboard[:3]):
            print(f"[DEBUG] {entry['display_name']}: {entry['biased_pages']}/{entry['total_pages']} ({entry['bias_percentage']}%)")
        
        # Cache the result for 10 minutes
        cache.set(cache_key, leaderboard, ttl_minutes=10)
        print(f"[DEBUG] Cached leaderboard data for 10 minutes")
        
        return leaderboard
        
    except Exception as e:
        print(f"[ERROR] Failed to get leaderboard with optimized query: {e}")
        # Fallback to empty list rather than the slow original implementation
        return []



@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    db = SessionLocal()
    
    # Record database connection
    metrics.update_db_connections(1)
    
    # Optimized query to get all scans with their computed metrics
    with metrics.time_operation(metrics.db_query_duration, 'select'):
        from sqlalchemy import func, case
        
        # Get scans with page counts and flagged counts in a single query
        scan_query = (
            db.query(
                Scan.id,
                Scan.url,
                Scan.started_at,
                Scan.status,
                Scan.biased_pages_count,
                Scan.flagged_snippets_count,
                func.count(Page.id).label('total_pages'),
                func.count(
                    case(
                        (func.jsonb_array_length(func.coalesce(Page.mcp_holistic['bias_types'], '[]')) > 0, Page.id),
                        else_=None
                    )
                ).label('mcp_biased_pages')
            )
            .outerjoin(Page, Scan.id == Page.scan_id)
            .group_by(Scan.id, Scan.url, Scan.started_at, Scan.status, Scan.biased_pages_count, Scan.flagged_snippets_count)
            .order_by(Scan.started_at.desc())
        )
        
        scans_with_counts = scan_query.all()
    
    metrics.record_db_query('select', 0.1)  # Will be overwritten by context manager
    
    scan_summaries = []
    for scan_data in scans_with_counts:
        # Use computed fields if available, otherwise use query results
        scanned_count = scan_data.total_pages
        flagged_count = scan_data.mcp_biased_pages or 0
        
        # Fallback to stored computed fields if query didn't find flagged pages
        if flagged_count == 0 and scan_data.biased_pages_count:
            flagged_count = scan_data.biased_pages_count
        
        percent_flagged = (flagged_count / scanned_count * 100) if scanned_count else 0
        
        # Update bias detection rate metrics for completed scans
        if scan_data.status == "completed" and scanned_count > 0:
            metrics.update_bias_detection_rate(percent_flagged, 'last_scan')
        
        scan_summaries.append({
            "id": scan_data.id,
            "url": scan_data.url,
            "started_at": scan_data.started_at,
            "status": scan_data.status,
            "percent_flagged": round(percent_flagged, 1),
            "scanned_count": scanned_count,
            "flagged_count": flagged_count
        })
    
    
    # Show the most recent completed scan's results by default
    scan = next((s for s in scan_summaries if s["status"] == "completed"), None)
    last_result = None
    scan_status = False
    last_url = None
    if scan:
        scan_status = scan["status"] != "completed"
        last_url = scan["url"]
        if scan["status"] == "completed":
            # Get snippets for the completed scan with optimized query
            snippets_data = (
                db.query(Snippet, Page.url)
                .join(Page, Snippet.page_id == Page.id)
                .filter(Page.scan_id == scan["id"])
                .all()
            )
            last_result = [
                {
                    "url": page_url,
                    "context": snippet.context,
                    "code": snippet.code,
                    "llm_score": snippet.llm_score
                }
                for snippet, page_url in snippets_data
            ]
    
    # Prepare data for bias rate chart using bias snapshots
    bias_chart_data = []
    
    # Get bias snapshots for the last 30 days
    end_date = date.today()
    start_date = end_date - timedelta(days=30)
    
    try:
        snapshots = (
            db.query(BiasSnapshot)
            .filter(BiasSnapshot.date >= start_date)
            .order_by(BiasSnapshot.date)
            .all()
        )
        
        for snapshot in snapshots:
            bias_chart_data.append({
                "date": snapshot.date.strftime("%Y-%m-%d"),
                "percent_flagged": float(snapshot.bias_percentage)
            })
        
        # If no snapshots exist yet, fall back to calculating from scan data
        # This ensures the chart still works before snapshots are generated
        if not bias_chart_data:
            print("[INFO] No bias snapshots found, using scan data for chart")
            for scan in reversed(scan_summaries):
                started_at = scan.get("started_at")
                percent_flagged = scan.get("percent_flagged")
                scanned_count = scan.get("scanned_count")
                status = scan.get("status")
                if status == "completed" and scanned_count and started_at is not None and percent_flagged is not None:
                    if hasattr(started_at, 'strftime'):
                        try:
                            bias_chart_data.append({
                                "date": started_at.strftime("%Y-%m-%d %H:%M"),
                                "percent_flagged": float(percent_flagged)
                            })
                        except Exception as e:
                            print(f"[WARN] Skipping scan {scan.get('id')} in chart data due to error: {e}")
    except Exception as e:
        print(f"[ERROR] Failed to load bias snapshots: {e}")
        bias_chart_data = []
    # Use the scan dict for scan_id and last_url
    scan_obj = scan
    
    # Fetch Azure Docs directories from GitHub API for all configured repos
    azure_dirs = []

    # Check cache first
    github_cache_key = "github_azure_dirs"
    cached_dirs = cache.get(github_cache_key)
    if cached_dirs is not None:
        print(f"[DEBUG] Using cached GitHub API data")
        azure_dirs = cached_dirs
    else:
        try:
            seen_doc_sets = set()  # Avoid duplicates across repos
            async with httpx.AsyncClient(timeout=10.0) as client:
                for repo in AZURE_DOCS_REPOS:
                    api_url = f"https://api.github.com/repos/{repo.owner}/{repo.public_name}/contents/{repo.articles_path}"
                    print(f"[DEBUG] Fetching from {api_url}")
                    resp = await client.get(
                        api_url,
                        headers={"User-Agent": "linuxfirst-azuredocs-enforcer-dashboard"}
                    )
                    print(f"[DEBUG] GitHub API status for {repo.public_name}: {resp.status_code}")
                    if resp.status_code == 200:
                        data = resp.json()
                        print(f"[DEBUG] GitHub API returned {len(data)} items from {repo.public_name}")

                        # Only include directories and format for internal navigation
                        for item in data:
                            try:
                                if item.get('type') == 'dir':
                                    doc_set = item['name']
                                    if doc_set in seen_doc_sets:
                                        continue  # Skip duplicates
                                    seen_doc_sets.add(doc_set)

                                    try:
                                        display_name = format_doc_set_name(doc_set)
                                    except Exception as e:
                                        print(f"[WARN] Error formatting doc set name for '{doc_set}': {e}")
                                        display_name = doc_set.replace('-', ' ').title()

                                    azure_dirs.append({
                                        'doc_set': doc_set,
                                        'display_name': display_name,
                                        'name': item['name']
                                    })
                            except Exception as e:
                                print(f"[ERROR] Error processing item: {e}")
                                continue
                    else:
                        print(f"[WARN] Failed to fetch from {repo.public_name}: {resp.status_code}")

            # Sort alphabetically by display name
            azure_dirs.sort(key=lambda x: x['display_name'])
            print(f"[DEBUG] Total azure_dirs from all repos: {len(azure_dirs)}")

            # Cache the successful result for 1 hour
            if azure_dirs:
                cache.set(github_cache_key, azure_dirs, ttl_minutes=60)
                print(f"[DEBUG] Cached GitHub API data for 1 hour")
            else:
                raise Exception("No directories found from any repo")
        except Exception as e:
            print(f"[WARN] Exception fetching Azure Docs directories: {e}")
            print(f"[WARN] Using fallback data")
            # Fallback with common Azure services
            azure_dirs = [
                {"doc_set": "virtual-machines", "display_name": "Virtual Machines", "name": "virtual-machines"},
                {"doc_set": "app-service", "display_name": "App Service", "name": "app-service"},
                {"doc_set": "storage", "display_name": "Storage", "name": "storage"},
                {"doc_set": "container-instances", "display_name": "Container Instances", "name": "container-instances"},
                {"doc_set": "kubernetes-service", "display_name": "Kubernetes Service (AKS)", "name": "kubernetes-service"}
            ]
            print(f"[DEBUG] Fallback azure_dirs: {azure_dirs}")

    # Get doc set leaderboard
    try:
        doc_set_leaderboard = get_doc_set_leaderboard(db)
        print(f"[DEBUG] Leaderboard entries: {len(doc_set_leaderboard)}")
        if doc_set_leaderboard:
            print(f"[DEBUG] Sample leaderboard entry: {doc_set_leaderboard[0]}")
    except Exception as e:
        print(f"[ERROR] Failed to get leaderboard: {e}")
        doc_set_leaderboard = []
    
    # Get satisfaction metrics for dashboard
    satisfaction_metrics = {"llm_analysis": 0, "page_rewrites": 0}
    try:
        # Check cache first
        satisfaction_cache_key = "dashboard_satisfaction_metrics"
        cached_satisfaction = cache.get(satisfaction_cache_key)
        if cached_satisfaction is not None:
            print(f"[DEBUG] Using cached satisfaction metrics")
            satisfaction_metrics = cached_satisfaction
        else:
            from shared.models import UserFeedback
            from sqlalchemy import func
            
            # Debug: Check total feedback count first
            total_feedback = db.query(UserFeedback).count()
            print(f"[DEBUG] Total UserFeedback records: {total_feedback}")
            
            # Get LLM analysis satisfaction (all feedback - users rate AI analysis quality)
            # This includes both snippet feedback and page feedback since both involve AI analysis
            llm_analysis_feedback = db.query(UserFeedback).filter(
                (UserFeedback.snippet_id.isnot(None)) | (UserFeedback.page_id.isnot(None))
            ).all()
            
            print(f"[DEBUG] LLM analysis feedback count (snippets + pages): {len(llm_analysis_feedback)}")
            if llm_analysis_feedback:
                llm_thumbs_up = sum(1 for f in llm_analysis_feedback if f.rating == True)
                llm_total = len(llm_analysis_feedback)
                llm_satisfaction = (llm_thumbs_up / llm_total * 100) if llm_total > 0 else 0
                satisfaction_metrics["llm_analysis"] = round(llm_satisfaction, 1)
                print(f"[DEBUG] LLM analysis feedback - thumbs up: {llm_thumbs_up}, total: {llm_total}, satisfaction: {llm_satisfaction}%")
            else:
                print(f"[DEBUG] No LLM analysis feedback found")
            
            # Get page rewrite satisfaction (rewritten document feedback)  
            rewrite_feedback = db.query(UserFeedback).filter(
                UserFeedback.rewritten_document_id.isnot(None)
            ).all()
            
            print(f"[DEBUG] Rewrite feedback count: {len(rewrite_feedback)}")
            if rewrite_feedback:
                rewrite_thumbs_up = sum(1 for f in rewrite_feedback if f.rating == True)
                rewrite_total = len(rewrite_feedback)
                rewrite_satisfaction = (rewrite_thumbs_up / rewrite_total * 100) if rewrite_total > 0 else 0
                satisfaction_metrics["page_rewrites"] = round(rewrite_satisfaction, 1)
                print(f"[DEBUG] Rewrite feedback - thumbs up: {rewrite_thumbs_up}, total: {rewrite_total}, satisfaction: {rewrite_satisfaction}%")
            else:
                print(f"[DEBUG] No rewrite feedback found - this is normal if no rewritten documents exist yet")
                # Page rewrites stays at 0% if no rewritten documents have been created yet
                
            # Debug: Check what types of feedback we actually have
            snippet_feedback_count = db.query(UserFeedback).filter(
                UserFeedback.snippet_id.isnot(None)
            ).count()
            print(f"[DEBUG] Snippet feedback count: {snippet_feedback_count}")
            
            # Clear any existing cache first to ensure fresh calculation
            cache.clear()
            
            # Cache for 5 minutes
            cache.set(satisfaction_cache_key, satisfaction_metrics, ttl_minutes=5)
            print(f"[DEBUG] Cached satisfaction metrics: {satisfaction_metrics}")
            
    except Exception as e:
        print(f"[ERROR] Failed to get satisfaction metrics: {e}")
        satisfaction_metrics = {"llm_analysis": 0, "page_rewrites": 0}
    
    db.close()
    
    print(f"[DEBUG] Final azure_dirs being passed to template: {len(azure_dirs)}")
    if azure_dirs:
        print(f"[DEBUG] Final sample item: {azure_dirs[0]}")
    
    return templates.TemplateResponse("index.html", {
        "request": request,
        "last_result": last_result,
        "scan_status": scan_status,
        "last_url": scan_obj.get('url') if scan_obj else None,
        "all_scans": scan_summaries,
        "scan_id": scan_obj.get('id') if scan_obj else None,
        "bias_chart_data": bias_chart_data,
        "azure_dirs": azure_dirs,
        "doc_set_leaderboard": doc_set_leaderboard,
        "satisfaction_metrics": satisfaction_metrics
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

@app.get("/flagged")
async def flagged_docs(request: Request, docset: str = Query(None)):
    """Display all flagged documentation pages with optional docset filtering."""
    from utils.docset_queries import get_all_flagged_pages, get_available_docsets

    db = SessionLocal()
    try:
        flagged_pages = get_all_flagged_pages(db)
        available_docsets = get_available_docsets(db)

        # Filter by docset if specified
        if docset:
            flagged_pages = [p for p in flagged_pages if p['doc_set'] == docset]

        # Sort by docset, then by URL
        flagged_pages.sort(key=lambda x: (x['doc_set'] or '', x['url']))

        return templates.TemplateResponse("flagged_docs.html", {
            "request": request,
            "flagged_pages": flagged_pages,
            "available_docsets": available_docsets,
            "selected_docset": docset,
            "total_count": len(flagged_pages)
        })
    finally:
        db.close()

@app.get("/pull-requests")
async def pull_requests(request: Request):
    """Placeholder route for pull requests page"""
    return templates.TemplateResponse("placeholder.html", {
        "request": request,
        "page_title": "Pull Requests",
        "message": "This page will show pull requests created to fix Windows bias in documentation.",
        "coming_soon": True
    })

@app.get("/stats")
async def stats(request: Request):
    """Placeholder route for statistics page"""
    return templates.TemplateResponse("placeholder.html", {
        "request": request,
        "page_title": "Statistics",
        "message": "This page will show detailed statistics about documentation bias across all Azure services.",
        "coming_soon": True
    })

@app.get("/progress")
async def progress():
    db = SessionLocal()
    # Get the most recent scan (by started_at)
    scan = db.query(Scan).order_by(Scan.started_at.desc()).first()
    if not scan:
        db.close()
        return JSONResponse({"running": False, "flagged_snippets": []})
    
    running = scan.status != "completed"
    
    # Use computed fields when available for completed scans
    if scan.status == "completed" and scan.flagged_snippets_count is not None and scan.biased_pages_count is not None:
        # For completed scans, use the stored computed values for better performance
        scanned_count = scan.total_pages_found or 0
        flagged_count = scan.flagged_snippets_count
        flagged_pages = scan.biased_pages_count
        
        # Get URLs from pages table for scanned_urls
        pages = db.query(Page.url).filter(Page.scan_id == scan.id).all()
        scanned_urls = [p.url for p in pages]
        total_snippets = flagged_count  # For completed scans, we know total snippets processed
    else:
        # For running scans, we need fresh data
        # Optimized query to get page count and URLs in one go
        pages = db.query(Page.url).filter(Page.scan_id == scan.id).all()
        scanned_urls = [p.url for p in pages]
        scanned_count = len(scanned_urls)
        
        # Use count queries instead of loading all objects for performance
        from sqlalchemy import func
        total_snippets = (
            db.query(func.count(Snippet.id))
            .join(Page)
            .filter(Page.scan_id == scan.id)
            .scalar()
        ) or 0
        
        flagged_count = (
            db.query(func.count(Snippet.id))
            .join(Page)
            .filter(Page.scan_id == scan.id)
            .filter(Snippet.llm_score["windows_biased"].as_boolean() == True)
            .scalar()
        ) or 0
        
        flagged_pages = (
            db.query(func.count(func.distinct(Page.id)))
            .join(Snippet)
            .filter(Page.scan_id == scan.id)
            .filter(Snippet.llm_score["windows_biased"].as_boolean() == True)
            .scalar()
        ) or 0
    
    percent_flagged = (flagged_pages / scanned_count * 100) if scanned_count else 0
    
    # Get flagged snippets for serialization (limit to recent 50 for performance)
    flagged_snippets_data = (
        db.query(Snippet, Page.url)
        .join(Page, Snippet.page_id == Page.id)
        .filter(Page.scan_id == scan.id)
        .filter(Snippet.llm_score["windows_biased"].as_boolean() == True)
        .order_by(Snippet.id.desc())
        .limit(50)
        .all()
    )
    
    # Serialize flagged snippets for JSON
    flagged_serialized = []
    for snippet, page_url in flagged_snippets_data:
        flagged_serialized.append({
            "url": page_url,
            "context": snippet.context,
            "code": snippet.code,
            "llm_score": snippet.llm_score
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


app.include_router(admin.router)
app.include_router(scan.router)
app.include_router(llm.router)
app.include_router(websocket.router)
app.include_router(docset.router)
app.include_router(auth.router)
app.include_router(feedback.router)
app.include_router(docpage.router)

# Add metrics endpoint
app.get("/metrics")(create_metrics_endpoint())

@app.on_event("startup")
async def startup_event():
    """Log environment variables at startup"""
    logger.info("=== ADMIN PASSWORD CONFIGURATION ===")
    logger.info(f"ADMIN_PASSWORD environment variable: '{os.getenv('ADMIN_PASSWORD', 'NOT SET')}'")
    logger.info(f"ADMIN_PASSWORD length: {len(os.getenv('ADMIN_PASSWORD', ''))}")
    logger.info(f"ADMIN_SESSION_SECRET length: {len(os.getenv('ADMIN_SESSION_SECRET', ''))}")
    logger.info("=====================================")

    # Test the password hashing function
    test_password = "admin123"
    test_hash = hashlib.sha256(test_password.encode()).hexdigest()
    logger.info(f"Test hash for 'admin123': {test_hash}")
    logger.info(f"Expected hash: {hashlib.sha256(os.getenv('ADMIN_PASSWORD', 'admin123').encode()).hexdigest()}")
    logger.info("=====================================")

    # Log Azure OpenAI environment variables at startup
    logger.info("=== AZURE OPENAI CONFIGURATION ===")
    azure_openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    azure_openai_deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "")
    azure_openai_key = os.getenv("AZURE_OPENAI_KEY", "")
    azure_openai_clientid = os.getenv("AZURE_OPENAI_CLIENTID", "")

    logger.info(f"AZURE_OPENAI_ENDPOINT: '{azure_openai_endpoint}'")
    logger.info(f"AZURE_OPENAI_DEPLOYMENT: '{azure_openai_deployment}'")
    logger.info(f"AZURE_OPENAI_CLIENTID: '{azure_openai_clientid}'")

    if azure_openai_key:
        logger.info(f"AZURE_OPENAI_KEY (masked): {azure_openai_key[:4]}...{azure_openai_key[-4:]}")
    else:
        logger.info("AZURE_OPENAI_KEY: NOT SET")

    # Determine authentication method
    if azure_openai_endpoint and (azure_openai_key or azure_openai_clientid):
        if azure_openai_clientid and not azure_openai_key:
            auth_method = "managed_identity"
        elif azure_openai_key:
            auth_method = "api_key"
        else:
            auth_method = "unknown"
        logger.info(f"Azure OpenAI authentication method: {auth_method}")
        logger.info("Azure OpenAI should be AVAILABLE")
    else:
        logger.info("Azure OpenAI authentication method: none")
        logger.info("Azure OpenAI will NOT be available - missing endpoint or credentials")
    logger.info("===================================")
