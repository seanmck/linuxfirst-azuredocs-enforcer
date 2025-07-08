from fastapi import FastAPI, Request, Form, BackgroundTasks, HTTPException, Depends, Cookie, Body, Query
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.concurrency import run_in_threadpool
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
from datetime import datetime, timedelta
import time
import pika
from packages.scorer.llm_client import LLMClient
import requests
import re
import httpx
from markdown import markdown as md_lib
from functools import lru_cache
from routes import admin, scan, llm, websocket, docset
from routes.scan import enqueue_scan_task
from jinja_env import templates
from middleware.metrics import PrometheusMiddleware, create_metrics_endpoint
from middleware.security import SecurityMiddleware
from shared.utils.metrics import get_metrics
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Log environment variables at startup
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

# Add security middleware first (processes requests before other middleware)
app.add_middleware(
    SecurityMiddleware,
    rate_limit_per_minute=60,  # Adjust based on your needs
    block_duration_minutes=30
)

# Add Prometheus metrics middleware
app.add_middleware(PrometheusMiddleware, service_name="webui")

# Initialize metrics
metrics = get_metrics()
metrics.set_service_health("webui", True)

# Ensure the static directory path is absolute
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Register markdown filter for Jinja2

def markdown_filter(text):
    return md_lib(text or "")

templates.env.filters['markdown'] = markdown_filter

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
    Returns a list of doc sets with their bias statistics.
    Uses efficient aggregation queries for better performance.
    """
    from sqlalchemy import func, case, text
    
    # Check cache first
    cache_key = "doc_set_leaderboard_github"
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
            WHERE sc.status = 'done'
            AND p.url LIKE '%/articles/%'
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

def extract_doc_set_from_url(url):
    """Extract the documentation set from a URL."""
    if not url or '/azure/' not in url:
        return None
    
    try:
        # Extract path after /azure/
        parts = url.split('/azure/', 1)
        if len(parts) < 2:
            return None
        
        path_parts = parts[1].split('/')
        if len(path_parts) > 0 and path_parts[0]:
            return path_parts[0]
    except Exception:
        return None
    
    return None

def format_doc_set_name(doc_set):
    """Convert technical doc set name to user-friendly display name."""
    if not doc_set:
        return "Unknown"
    
    # Common mappings
    name_mappings = {
        'virtual-machines': 'Virtual Machines',
        'app-service': 'App Service',
        'storage': 'Storage',
        'container-instances': 'Container Instances',
        'kubernetes-service': 'Kubernetes Service (AKS)',
        'cognitive-services': 'Cognitive Services',
        'functions': 'Azure Functions',
        'logic-apps': 'Logic Apps',
        'service-fabric': 'Service Fabric',
        'batch': 'Batch',
        'hdinsight': 'HDInsight',
        'data-factory': 'Data Factory',
        'cosmos-db': 'Cosmos DB',
        'sql-database': 'SQL Database',
        'postgresql': 'PostgreSQL',
        'mysql': 'MySQL',
        'redis': 'Redis Cache',
        'search': 'Cognitive Search',
        'machine-learning': 'Machine Learning',
        'synapse-analytics': 'Synapse Analytics',
        'stream-analytics': 'Stream Analytics',
        'event-hubs': 'Event Hubs',
        'service-bus': 'Service Bus',
        'notification-hubs': 'Notification Hubs'
    }
    
    return name_mappings.get(doc_set, doc_set.replace('-', ' ').title())

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
        if scan_data.status == "done" and scanned_count > 0:
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
    scan = next((s for s in scan_summaries if s["status"] == "done"), None)
    last_result = None
    scan_status = False
    last_url = None
    if scan:
        scan_status = scan["status"] != "done"
        last_url = scan["url"]
        if scan["status"] == "done":
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
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=30)
    
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
                if status == "done" and scanned_count and started_at is not None and percent_flagged is not None:
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
    
    # Fetch Azure Docs directories from GitHub API
    azure_dirs = []
    
    # Check cache first
    github_cache_key = "github_azure_dirs"
    cached_dirs = cache.get(github_cache_key)
    if cached_dirs is not None:
        print(f"[DEBUG] Using cached GitHub API data")
        azure_dirs = cached_dirs
    else:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://api.github.com/repos/MicrosoftDocs/azure-docs/contents/articles",
                    headers={"User-Agent": "linuxfirst-azuredocs-enforcer-dashboard"}
                )
            print(f"[DEBUG] GitHub API status: {resp.status_code}")
            if resp.status_code == 200:
                data = resp.json()
                print(f"[DEBUG] GitHub API returned {len(data)} items")
                print(f"[DEBUG] Sample raw item: {data[0] if data else 'no data'}")
                
                # Only include directories and format for internal navigation
                azure_dirs = []
                processed_count = 0
                for i, item in enumerate(data):
                    try:
                        if item.get('type') == 'dir':
                            doc_set = item['name']  # This is the directory name like 'virtual-machines'
                            try:
                                display_name = format_doc_set_name(doc_set)
                            except Exception as e:
                                print(f"[WARN] Error formatting doc set name for '{doc_set}': {e}")
                                display_name = doc_set.replace('-', ' ').title()
                            
                            azure_dirs.append({
                                'doc_set': doc_set,
                                'display_name': display_name,
                                'name': item['name']  # Keep for backwards compatibility
                            })
                            processed_count += 1
                            
                            if i < 3:  # Debug first 3 items
                                print(f"[DEBUG] Processed item {i}: doc_set='{doc_set}', display_name='{display_name}'")
                                print(f"[DEBUG] Created dict: {azure_dirs[-1]}")
                    except Exception as e:
                        print(f"[ERROR] Error processing item {i}: {e}")
                        continue
                        
                print(f"[DEBUG] Processed {processed_count} directories out of {len(data)} total items")
                print(f"[DEBUG] azure_dirs length: {len(azure_dirs)}")
                print(f"[DEBUG] azure_dirs sample: {azure_dirs[:2] if azure_dirs else 'empty'}")
                
                # Cache the successful result for 1 hour
                cache.set(github_cache_key, azure_dirs, ttl_minutes=60)
                print(f"[DEBUG] Cached GitHub API data for 1 hour")
            else:
                print(f"[WARN] Failed to fetch Azure Docs directories: {resp.status_code} {resp.text}")
                raise Exception(f"GitHub API returned {resp.status_code}")
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
        "doc_set_leaderboard": doc_set_leaderboard
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
    
    # Use computed fields when available for completed scans
    if scan.status == "done" and scan.flagged_snippets_count is not None and scan.biased_pages_count is not None:
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

# Add metrics endpoint
app.get("/metrics")(create_metrics_endpoint())
