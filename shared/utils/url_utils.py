"""URL utility functions for detecting source types."""

from urllib.parse import urlparse
from typing import Optional


def detect_url_source(url: Optional[str]) -> str:
    """
    Detect the source type based on the URL.
    
    Args:
        url: The URL to analyze
        
    Returns:
        Source type: "github", "ms-learn", or "unknown"
    """
    if not url:
        return "unknown"
    
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        
        # Remove www. prefix if present
        if domain.startswith('www.'):
            domain = domain[4:]
        
        if domain == 'github.com':
            return "github"
        elif domain == 'learn.microsoft.com':
            return "ms-learn"
        else:
            return "unknown"
    except Exception:
        return "unknown"