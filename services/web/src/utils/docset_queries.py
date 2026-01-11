"""
Optimized docset query functions for better performance.
Consolidates multiple database queries into efficient single queries.
"""

from sqlalchemy import func, and_, or_, text
from sqlalchemy.orm import Session
from shared.models import Scan, Page, Snippet, BiasSnapshotByDocset
from shared.utils.bias_utils import is_page_biased, get_parsed_mcp_holistic, get_page_priority
from shared.utils.url_utils import extract_doc_set_from_url
from shared.utils.logging import get_logger
from datetime import datetime, date, timedelta
from typing import Dict, List, Any, Optional
import json
from .docset_cache import get_cached_docset_data, cache_docset_data

# Initialize logger
logger = get_logger(__name__)


def get_docset_complete_data(db: Session, doc_set: str) -> Dict[str, Any]:
    """
    Get all docset data in a single optimized query with caching.
    
    This function replaces the three separate query functions:
    - get_docset_summary_stats
    - get_docset_bias_history  
    - get_docset_flagged_pages
    
    Args:
        db: Database session
        doc_set: Documentation set name
        
    Returns:
        Dictionary containing all docset data
    """
    
    # Try to get cached data first
    cached_data = get_cached_docset_data(doc_set)
    if cached_data is not None:
        logger.debug(f"Using cached data for docset: {doc_set}")
        return cached_data
    
    logger.debug(f"Cache miss for docset: {doc_set}, querying database")
    
    # Try to get recent bias history from snapshots first (last 90 days)
    end_date = date.today()
    start_date = end_date - timedelta(days=90)
    
    bias_history = []
    try:
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
            bias_history = [
                {
                    'date': snapshot.date.strftime('%Y-%m-%d'),
                    'scan_id': None,
                    'total_pages': snapshot.total_pages,
                    'biased_pages': snapshot.biased_pages,
                    'bias_percentage': round(snapshot.bias_percentage, 1)
                }
                for snapshot in snapshots
            ]
    except Exception as e:
        print(f"[WARN] Failed to load bias snapshots for docset {doc_set}: {e}")
    
    # Get all pages for this docset using optimized query
    # Try doc_set column first, fall back to URL extraction if no results
    pages_query = db.query(Page, Scan.started_at).join(Scan, Page.scan_id == Scan.id)

    # First try using the doc_set column (faster if populated)
    pages_query_with_docset = pages_query.filter(Page.doc_set == doc_set)
    page_scan_results = pages_query_with_docset.all()
    use_doc_set_column = True

    # If no results from doc_set column, fallback to URL extraction
    # This handles cases where doc_set wasn't populated for new repos
    if not page_scan_results:
        logger.debug(f"No pages found using doc_set column for '{doc_set}', falling back to URL extraction")
        use_doc_set_column = False
        # Load all pages and filter by URL extraction
        all_pages_query = pages_query
        all_page_results = all_pages_query.all()
        page_scan_results = [
            (page, scan_date) for page, scan_date in all_page_results
            if extract_doc_set_from_url(page.url) == doc_set
        ]
    
    # Process results
    all_pages = set()
    biased_pages = set()
    flagged_pages = []
    
    for page, scan_date in page_scan_results:
        all_pages.add(page.url)
        
        # Check if page is biased
        if is_page_biased(page):
            biased_pages.add(page.url)
            
            # Get snippets for this page in a single query
            snippets = db.query(Snippet).filter(Snippet.page_id == page.id).all()
            
            # Use cached parsed mcp_holistic data
            mcp_holistic = get_parsed_mcp_holistic(page)
            
            # Get priority for this page
            priority_label, priority_score = get_page_priority(page)

            # Build flagged page data
            flagged_pages.append({
                'id': page.id,
                'url': page.url,
                'scan_id': page.scan_id,
                'scan_date': scan_date,
                'priority_label': priority_label,
                'priority_score': priority_score,
                'bias_details': {
                    'mcp_holistic': mcp_holistic,
                    'snippets': snippets
                }
            })
    
    # Sort flagged pages by priority (high first) then by most recent scan
    flagged_pages.sort(key=lambda x: (-x['priority_score'], -x['scan_date'].timestamp()))
    
    # Calculate summary statistics
    total_pages = len(all_pages)
    total_biased = len(biased_pages)
    bias_percentage = (total_biased / total_pages * 100) if total_pages > 0 else 0
    
    summary_stats = {
        'total_pages': total_pages,
        'biased_pages': total_biased,
        'bias_percentage': round(bias_percentage, 1),
        'clean_pages': total_pages - total_biased
    }
    
    # If no bias history from snapshots, calculate from scan data
    if not bias_history and total_pages > 0:
        # Group pages by scan to calculate historical bias
        scan_groups = {}
        for page, scan_date in page_scan_results:
            scan_id = page.scan_id
            if scan_id not in scan_groups:
                scan_groups[scan_id] = {
                    'scan_date': scan_date,
                    'pages': [],
                    'biased_count': 0
                }
            scan_groups[scan_id]['pages'].append(page)
            if is_page_biased(page):
                scan_groups[scan_id]['biased_count'] += 1
        
        # Build bias history from scans
        for scan_id, scan_data in scan_groups.items():
            total_scan_pages = len(scan_data['pages'])
            biased_scan_pages = scan_data['biased_count']
            scan_bias_percentage = (biased_scan_pages / total_scan_pages * 100) if total_scan_pages > 0 else 0
            
            bias_history.append({
                'date': scan_data['scan_date'].strftime('%Y-%m-%d %H:%M'),
                'scan_id': scan_id,
                'total_pages': total_scan_pages,
                'biased_pages': biased_scan_pages,
                'bias_percentage': round(scan_bias_percentage, 1)
            })
        
        # Sort bias history by date
        bias_history.sort(key=lambda x: x['date'])
    
    result = {
        'summary_stats': summary_stats,
        'bias_history': bias_history,
        'flagged_pages': flagged_pages,
        'use_doc_set_column': use_doc_set_column
    }
    
    # Cache the result for 5 minutes
    cache_docset_data(doc_set, result, ttl=300)
    
    return result


def get_available_docsets(db: Session, limit: int = 100) -> List[str]:
    """
    Get a list of available docsets efficiently.
    
    Args:
        db: Database session
        limit: Maximum number of sample pages to check
        
    Returns:
        List of available docset names
    """
    
    # Try to use the doc_set column first
    try:
        docsets = (
            db.query(Page.doc_set)
            .filter(Page.doc_set.isnot(None))
            .distinct()
            .limit(limit)
            .all()
        )
        
        if docsets:
            return [doc_set[0] for doc_set in docsets if doc_set[0]]
    except Exception:
        # Fallback to extracting from URLs
        pass
    
    # Fallback: sample pages and extract docsets
    all_docsets = set()
    sample_pages = db.query(Page).limit(limit).all()
    
    for page in sample_pages:
        extracted_docset = extract_doc_set_from_url(page.url)
        if extracted_docset:
            all_docsets.add(extracted_docset)
    
    return sorted(list(all_docsets))


def get_all_flagged_pages(db: Session, limit: int = 1000) -> List[Dict[str, Any]]:
    """
    Get all flagged pages across all docsets efficiently.

    Args:
        db: Database session
        limit: Maximum number of pages to return

    Returns:
        List of flagged page dictionaries with docset, URL, bias info
    """
    from shared.utils.bias_utils import get_page_priority
    from shared.utils.url_utils import format_doc_set_name

    # Query pages joined with scans, ordered by most recent scan first
    pages_query = (
        db.query(Page, Scan.started_at)
        .join(Scan, Page.scan_id == Scan.id)
        .order_by(Scan.started_at.desc())
    )

    page_scan_results = pages_query.limit(limit * 2).all()  # Get extra to account for non-biased

    flagged_pages = []
    seen_urls = set()  # Deduplicate by URL (keep most recent scan)

    for page, scan_date in page_scan_results:
        if page.url in seen_urls:
            continue

        if not is_page_biased(page):
            continue

        seen_urls.add(page.url)

        # Get docset from page.doc_set or extract from URL
        doc_set = page.doc_set
        if not doc_set:
            doc_set = extract_doc_set_from_url(page.url)

        # Parse mcp_holistic for bias details
        mcp_data = get_parsed_mcp_holistic(page)
        bias_types = mcp_data.get('bias_types', []) if mcp_data else []
        if isinstance(bias_types, str):
            bias_types = [bias_types]
        priority_label, priority_score = get_page_priority(page)

        flagged_pages.append({
            'id': page.id,
            'url': page.url,
            'doc_set': doc_set,
            'display_name': format_doc_set_name(doc_set) if doc_set else 'Unknown',
            'scan_date': scan_date,
            'bias_types': bias_types,
            'priority': priority_label,
            'priority_score': priority_score,
            'summary': mcp_data.get('summary', '') if mcp_data else ''
        })

        if len(flagged_pages) >= limit:
            break

    return flagged_pages