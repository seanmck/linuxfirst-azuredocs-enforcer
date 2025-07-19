from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from shared.utils.database import SessionLocal
from shared.models import Scan, Page, Snippet, BiasSnapshotByDocset, User
from datetime import datetime, date, timedelta
from collections import defaultdict
from typing import Optional
import os
import json
from urllib.parse import unquote
from shared.utils.bias_utils import is_page_biased, count_biased_pages, get_bias_percentage
from shared.utils.url_utils import extract_doc_set_from_url, format_doc_set_name
from utils.docset_queries import get_docset_complete_data, get_available_docsets
from routes.auth import get_current_user

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
                # Get snippets for this page
                snippets = db.query(Snippet).filter(Snippet.page_id == page.id).all()
                
                # Parse mcp_holistic JSON if it's a string (same logic as scan.py)
                mcp_holistic = page.mcp_holistic
                if isinstance(mcp_holistic, str):
                    try:
                        import json
                        mcp_holistic = json.loads(mcp_holistic)
                    except Exception:
                        mcp_holistic = None
                
                # Debug logging to see what's in the data (limited to first page only)
                if len(flagged_pages) == 0:  # Only log for the first flagged page
                    print(f"[DEBUG] First flagged page {page.url}")
                    print(f"[DEBUG] mcp_holistic type: {type(mcp_holistic)}")
                    if mcp_holistic and isinstance(mcp_holistic, dict):
                        print(f"[DEBUG] mcp_holistic keys: {list(mcp_holistic.keys())}")
                        print(f"[DEBUG] has summary: {'summary' in mcp_holistic}")
                        print(f"[DEBUG] has recommendations: {'recommendations' in mcp_holistic}")
                        if 'summary' in mcp_holistic:
                            print(f"[DEBUG] summary value: {mcp_holistic.get('summary', 'None')[:100]}...")
                        if 'recommendations' in mcp_holistic:
                            print(f"[DEBUG] recommendations value: {mcp_holistic.get('recommendations', 'None')}")
                
                # Build bias_details structure that matches template expectations
                bias_details = {
                    'mcp_holistic': mcp_holistic,
                    'snippets': snippets
                }
                seen_urls.add(page.url)
                flagged_pages.append({
                    'id': page.id,  # Add page ID for pull request functionality
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
    print(f"[DEBUG] get_docset_summary_stats called with doc_set: '{doc_set}'")
    
    completed_scans = db.query(Scan).all()
    print(f"[DEBUG] Found {len(completed_scans)} total scans")
    
    all_pages = set()
    biased_pages = set()
    
    for scan in completed_scans:
        pages = db.query(Page).filter(Page.scan_id == scan.id).all()
        print(f"[DEBUG] Scan {scan.id}: {len(pages)} pages")
        
        docset_pages_in_scan = 0
        for page in pages:
            extracted_docset = extract_doc_set_from_url(page.url)
            if extracted_docset == doc_set:
                docset_pages_in_scan += 1
                all_pages.add(page.url)
                
                # Check if page has bias using unified logic
                if is_page_biased(page):
                    biased_pages.add(page.url)
        
        if docset_pages_in_scan > 0:
            print(f"[DEBUG] Scan {scan.id}: {docset_pages_in_scan} pages match docset '{doc_set}'")
    
    total_pages = len(all_pages)
    total_biased = len(biased_pages)
    bias_percentage = (total_biased / total_pages * 100) if total_pages > 0 else 0
    
    print(f"[DEBUG] Final stats: {total_pages} total pages, {total_biased} biased pages")
    
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
async def docset_details(doc_set_name: str, request: Request, current_user: Optional[User] = Depends(get_current_user)):
    """Show detailed bias analysis for a specific documentation set."""
    # URL decode the doc set name
    doc_set = unquote(doc_set_name)
    
    db = SessionLocal()
    
    try:
        print(f"[DEBUG] Docset request for: '{doc_set}'")
        
        # Get all docset data in a single optimized query
        docset_data = get_docset_complete_data(db, doc_set)
        
        summary_stats = docset_data['summary_stats']
        bias_history = docset_data['bias_history']
        flagged_pages = docset_data['flagged_pages']
        use_doc_set_column = docset_data['use_doc_set_column']
        
        print(f"[DEBUG] Summary stats: {summary_stats}")
        print(f"[DEBUG] Bias history: {len(bias_history)} entries")
        print(f"[DEBUG] Flagged pages: {len(flagged_pages)} pages")
        print(f"[DEBUG] Using doc_set column: {use_doc_set_column}")
        
        # Debug: Show available docsets if no pages found
        if summary_stats['total_pages'] == 0:
            print(f"[DEBUG] No pages found for doc_set: '{doc_set}' - showing empty state")
            available_docsets = get_available_docsets(db)
            print(f"[DEBUG] Available docsets in database: {sorted(available_docsets)}")
        
        # Format display name
        display_name = format_doc_set_name(doc_set)
        print(f"[DEBUG] Display name: {display_name}")
        
        print(f"[DEBUG] About to render template...")
        
        result = templates.TemplateResponse("docset_details.html", {
            "request": request,
            "doc_set": doc_set,
            "display_name": display_name,
            "summary_stats": summary_stats,
            "bias_history": bias_history,
            "flagged_pages": flagged_pages,
            "user": current_user
        })
        
        print(f"[DEBUG] Template rendered successfully")
        return result
        
    except Exception as e:
        print(f"[ERROR] Exception in docset_details: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
        
    finally:
        db.close()