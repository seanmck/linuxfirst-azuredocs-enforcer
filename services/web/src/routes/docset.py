from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from shared.utils.database import SessionLocal
from shared.models import Scan, Page, Snippet, BiasSnapshotByDocset
from datetime import datetime, date, timedelta
from collections import defaultdict
import os
import json
from urllib.parse import unquote
from shared.utils.bias_utils import is_page_biased, count_biased_pages, get_bias_percentage
from shared.utils.url_utils import extract_doc_set_from_url, format_doc_set_name

router = APIRouter()

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "../templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)



def get_docset_bias_history(db, doc_set):
    """Get historical bias data for a specific doc set from all scans (including in-progress)."""
    
    # Get bias snapshots for this docset for the last 90 days
    end_date = date.today()
    start_date = end_date - timedelta(days=90)
    
    try:
        # Try to get data from bias snapshots first
        snapshots = (
            db.query(BiasSnapshotByDocset)
            .filter(
                BiasSnapshotByDocset.doc_set == doc_set,
                BiasSnapshotByDocset.date >= start_date
            )
            .order_by(BiasSnapshotByDocset.date)
            .all()
        )
        
        if snapshots:
            # Use snapshot data
            bias_history = []
            for snapshot in snapshots:
                bias_history.append({
                    'date': snapshot.date.strftime('%Y-%m-%d'),
                    'scan_id': None,  # Snapshots aren't tied to specific scans
                    'total_pages': snapshot.total_pages,
                    'biased_pages': snapshot.biased_pages,
                    'bias_percentage': round(snapshot.bias_percentage, 1)
                })
            return bias_history
    except Exception as e:
        print(f"[WARN] Failed to load bias snapshots for docset {doc_set}: {e}")
    
    # Fallback to calculating from scan data if no snapshots exist
    print(f"[INFO] No bias snapshots found for docset {doc_set}, calculating from scan data")
    completed_scans = db.query(Scan).order_by(Scan.started_at.asc()).all()
    
    bias_history = []
    for scan in completed_scans:
        pages = db.query(Page).filter(Page.scan_id == scan.id).all()
        
        # Filter pages for this doc set
        doc_set_pages = []
        for page in pages:
            if extract_doc_set_from_url(page.url) == doc_set:
                doc_set_pages.append(page)
        
        if not doc_set_pages:
            continue
            
        # Count biased pages using unified logic
        biased_count = count_biased_pages(doc_set_pages)
        
        total_pages = len(doc_set_pages)
        bias_percentage = (biased_count / total_pages * 100) if total_pages > 0 else 0
        
        bias_history.append({
            'date': scan.started_at.strftime('%Y-%m-%d %H:%M'),
            'scan_id': scan.id,
            'total_pages': total_pages,
            'biased_pages': biased_count,
            'bias_percentage': round(bias_percentage, 1)
        })
    
    return bias_history

def get_docset_flagged_pages(db, doc_set):
    """Get detailed information about flagged pages for a specific doc set from all scans."""
    completed_scans = db.query(Scan).all()
    
    flagged_pages = []
    seen_urls = set()  # Avoid duplicates across scans
    
    for scan in completed_scans:
        pages = db.query(Page).filter(Page.scan_id == scan.id).all()
        
        for page in pages:
            if extract_doc_set_from_url(page.url) != doc_set:
                continue
                
            if page.url in seen_urls:
                continue
                
            # Check if page has bias using unified logic
            page_is_biased = is_page_biased(page)
            
            if page_is_biased:
                bias_details = {'mcp_holistic': page.mcp_holistic}
                seen_urls.add(page.url)
                flagged_pages.append({
                    'url': page.url,
                    'scan_id': scan.id,
                    'scan_date': scan.started_at,
                    'bias_details': bias_details
                })
    
    # Sort by most recent scan
    flagged_pages.sort(key=lambda x: x['scan_date'], reverse=True)
    return flagged_pages

def get_docset_summary_stats(db, doc_set):
    """Get summary statistics for a specific doc set from all scans."""
    completed_scans = db.query(Scan).all()
    
    all_pages = set()
    biased_pages = set()
    
    for scan in completed_scans:
        pages = db.query(Page).filter(Page.scan_id == scan.id).all()
        
        for page in pages:
            if extract_doc_set_from_url(page.url) != doc_set:
                continue
                
            all_pages.add(page.url)
            
            # Check if page has bias using unified logic
            if is_page_biased(page):
                biased_pages.add(page.url)
    
    total_pages = len(all_pages)
    total_biased = len(biased_pages)
    bias_percentage = (total_biased / total_pages * 100) if total_pages > 0 else 0
    
    return {
        'total_pages': total_pages,
        'biased_pages': total_biased,
        'bias_percentage': round(bias_percentage, 1),
        'clean_pages': total_pages - total_biased
    }

@router.get("/docset/test")
async def docset_test(request: Request):
    """Test route to verify docset router is working."""
    return HTMLResponse("<h1>Docset router is working!</h1>")

@router.get("/docset/{doc_set_name}")
async def docset_details(doc_set_name: str, request: Request):
    """Show detailed bias analysis for a specific documentation set."""
    # URL decode the doc set name
    doc_set = unquote(doc_set_name)
    
    db = SessionLocal()
    
    try:
        print(f"[DEBUG] Docset request for: '{doc_set}'")
        
        # Get summary statistics
        summary_stats = get_docset_summary_stats(db, doc_set)
        print(f"[DEBUG] Summary stats: {summary_stats}")
        
        # If no pages found, show empty state instead of 404
        if summary_stats['total_pages'] == 0:
            print(f"[DEBUG] No pages found for doc_set: '{doc_set}' - showing empty state")
            # Create empty data structures for template
            bias_history = []
            flagged_pages = []
            summary_stats = {
                'total_pages': 0,
                'biased_pages': 0,
                'bias_percentage': 0,
                'clean_pages': 0
            }
        else:
            # Get bias history for charts
            bias_history = get_docset_bias_history(db, doc_set)
            
            # Get flagged pages with details
            flagged_pages = get_docset_flagged_pages(db, doc_set)
        
        # Format display name
        display_name = format_doc_set_name(doc_set)
        
        return templates.TemplateResponse("docset_details.html", {
            "request": request,
            "doc_set": doc_set,
            "display_name": display_name,
            "summary_stats": summary_stats,
            "bias_history": bias_history,
            "flagged_pages": flagged_pages
        })
        
    finally:
        db.close()