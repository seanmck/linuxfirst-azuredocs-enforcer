"""
Shared utilities for page-based bias detection.
Provides consistent logic across all UI components.
"""

import json
from typing import Dict, Any, Optional


def get_parsed_mcp_holistic(page) -> Optional[Dict[str, Any]]:
    """
    Parse and cache the mcp_holistic data for a page.
    
    Args:
        page: Page model instance with mcp_holistic field
        
    Returns:
        Parsed mcp_holistic data as dict, or None if parsing fails
    """
    if not page.mcp_holistic:
        return None
    
    # Check if we already have parsed data cached on the page object
    if hasattr(page, '_parsed_mcp_holistic'):
        return page._parsed_mcp_holistic
    
    # Parse the data
    mcp_data = page.mcp_holistic
    if isinstance(mcp_data, str):
        try:
            mcp_data = json.loads(mcp_data)
        except (json.JSONDecodeError, TypeError):
            mcp_data = None
    
    if not isinstance(mcp_data, dict):
        mcp_data = None
    
    # Cache the parsed result on the page object
    page._parsed_mcp_holistic = mcp_data
    
    return mcp_data

def is_page_biased(page):
    """
    Determine if a page needs attention based on holistic bias analysis.
    
    Args:
        page: Page model instance with mcp_holistic field
        
    Returns:
        bool: True if page has bias_types (needs attention), False otherwise
    """
    mcp_data = get_parsed_mcp_holistic(page)
    if not mcp_data:
        return False
    
    # A page needs attention if it has any bias_types
    bias_types = mcp_data.get('bias_types', [])
    if isinstance(bias_types, str):
        bias_types = [bias_types]
    
    return bool(bias_types and len(bias_types) > 0)


def get_page_priority(page):
    """
    Get the priority level for a page based on LLM-provided severity.
    Falls back to count-based logic for pages scanned before severity was added.

    Args:
        page: Page model instance with mcp_holistic field

    Returns:
        tuple: (priority_label, priority_score) where label is High/Medium/Low
               and score is 3/2/1 respectively
    """
    mcp_data = get_parsed_mcp_holistic(page)
    if not mcp_data:
        return ("Low", 1)

    # Prefer LLM-provided severity if available
    severity = mcp_data.get('severity')
    if severity:
        severity_map = {
            'high': ('High', 3),
            'medium': ('Medium', 2),
            'low': ('Low', 1),
            'none': ('Low', 1)
        }
        return severity_map.get(severity.lower(), ('Low', 1))

    # Fallback: count-based logic for legacy pages
    bias_types = mcp_data.get('bias_types', [])
    if isinstance(bias_types, str):
        bias_types = [bias_types]

    if not bias_types or not isinstance(bias_types, list):
        return ("Low", 1)

    n_bias = len(bias_types)
    if n_bias >= 3:
        return ("High", 3)
    elif n_bias == 2:
        return ("Medium", 2)
    elif n_bias == 1:
        return ("Low", 1)
    else:
        return ("Low", 1)


def count_biased_pages(pages):
    """
    Count how many pages in a list need attention.
    
    Args:
        pages: List of Page model instances
        
    Returns:
        int: Number of pages that need attention
    """
    return sum(1 for page in pages if is_page_biased(page))


def get_bias_percentage(pages):
    """
    Calculate the percentage of pages that need attention.
    
    Args:
        pages: List of Page model instances
        
    Returns:
        float: Percentage of pages needing attention (0-100)
    """
    if not pages:
        return 0.0
    
    total_pages = len(pages)
    biased_pages = count_biased_pages(pages)
    
    return (biased_pages / total_pages * 100) if total_pages > 0 else 0.0