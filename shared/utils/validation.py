"""
Shared validation utilities for data validation across the application
"""
import re
from typing import Dict, Any, Optional
from urllib.parse import urlparse


def is_valid_url(url: str) -> bool:
    """
    Validate if a string is a valid URL
    
    Args:
        url: URL string to validate
        
    Returns:
        True if valid URL, False otherwise
    """
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except Exception:
        return False


def is_github_url(url: str) -> bool:
    """
    Check if URL is a GitHub repository URL
    
    Args:
        url: URL to check
        
    Returns:
        True if GitHub URL, False otherwise
    """
    return url.startswith('https://github.com/') and '/' in url[19:]


def validate_task_data(task_data: Dict[str, Any]) -> tuple[bool, Optional[str]]:
    """
    Validate scan task data
    
    Args:
        task_data: Task data dictionary
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check required fields
    if 'url' not in task_data:
        return False, "Missing required field: url"
        
    if 'scan_id' not in task_data:
        return False, "Missing required field: scan_id"
    
    # Validate URL
    if not is_valid_url(task_data['url']):
        return False, f"Invalid URL: {task_data['url']}"
    
    # Validate scan_id is numeric
    try:
        int(task_data['scan_id'])
    except (ValueError, TypeError):
        return False, f"Invalid scan_id: {task_data['scan_id']}"
    
    # Validate source if present
    source = task_data.get('source', 'web')
    if source not in ['web', 'github']:
        return False, f"Invalid source: {source}"
    
    return True, None


def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename by removing/replacing invalid characters
    
    Args:
        filename: Original filename
        
    Returns:
        Sanitized filename safe for filesystem use
    """
    # Remove or replace invalid characters
    sanitized = re.sub(r'[<>:"/\\|?*]', '_', filename)
    
    # Remove leading/trailing whitespace and dots
    sanitized = sanitized.strip(' .')
    
    # Ensure it's not empty
    if not sanitized:
        sanitized = 'unnamed'
    
    return sanitized


def validate_scan_metrics(metrics: Dict[str, Any]) -> bool:
    """
    Validate scan metrics dictionary
    
    Args:
        metrics: Metrics dictionary to validate
        
    Returns:
        True if valid metrics, False otherwise
    """
    required_keys = ['biased_pages_count', 'flagged_snippets_count']
    
    for key in required_keys:
        if key not in metrics:
            return False
        try:
            int(metrics[key])
        except (ValueError, TypeError):
            return False
    
    return True