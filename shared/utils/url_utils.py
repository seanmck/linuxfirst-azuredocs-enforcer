"""URL utility functions for detecting source types."""

from urllib.parse import urlparse
from typing import Optional
import re


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


def extract_doc_set_from_url(url: str) -> Optional[str]:
    """
    Extract the documentation set name from a URL.
    
    Args:
        url: The URL to extract from
        
    Returns:
        The doc set name or None if not found
    """

    if not url:
        return None
    
    try:
        # For GitHub URLs, extract more granular info
        if 'github.com' in url:
            # Check if it's azure-docs with a specific service
            if 'MicrosoftDocs/azure-docs' in url:
                # Pattern: github.com/MicrosoftDocs/azure-docs/blob/main/articles/{service}/...
                match = re.search(r'azure-docs/blob/[^/]+/articles/([^/]+)', url)
                if match:
                    service = match.group(1)
                    # Return the specific Azure service as the docset
                    return service
                # Fallback to repo name if no service found
                return 'azure-docs'
            
            # For other GitHub repos, extract repo name
            match = re.search(r'github\.com/[^/]+/([^/]+)', url)
            if match:
                return match.group(1)
        
        # For learn.microsoft.com URLs, extract the product/service
        elif 'learn.microsoft.com' in url:
            # Pattern: learn.microsoft.com/{locale}/azure/{service}/...
            match = re.search(r'learn\.microsoft\.com/[^/]+/azure/([^/]+)', url)
            if match:
                return match.group(1)
            # Pattern: learn.microsoft.com/{locale}/{product}/...
            match = re.search(r'learn\.microsoft\.com/[^/]+/([^/]+)', url)
            if match:
                return match.group(1)
        
        return None
    except Exception:
        return None


def format_doc_set_name(doc_set: Optional[str]) -> str:
    """
    Format a documentation set name for display.
    
    Args:
        doc_set: The doc set name to format
        
    Returns:
        Formatted name for display
    """
    if not doc_set:
        return "Unknown"
    
    # Replace hyphens and underscores with spaces
    formatted = doc_set.replace('-', ' ').replace('_', ' ')
    
    # Title case
    formatted = formatted.title()
    
    # Special cases
    replacements = {
        'Api': 'API',
        'Ai': 'AI',
        'Ml': 'ML',
        'Iot': 'IoT',
        'Sql': 'SQL',
        'Vm': 'VM',
        'Vms': 'VMs',
        'Cli': 'CLI',
        'Sdk': 'SDK',
        'Id': 'ID',
        'Ip': 'IP',
        'Dns': 'DNS',
        'Vpn': 'VPN',
        'Cdn': 'CDN',
        'Http': 'HTTP',
        'Https': 'HTTPS',
        'Json': 'JSON',
        'Xml': 'XML',
        'Yaml': 'YAML',
        'Rest': 'REST',
        'Blob': 'Blob'
    }
    
    for old, new in replacements.items():
        formatted = re.sub(r'\b' + old + r'\b', new, formatted)
    
    return formatted
