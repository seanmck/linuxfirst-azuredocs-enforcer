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


def extract_doc_set_from_url(url: Optional[str]) -> Optional[str]:
    """Extract the documentation set from a URL."""
    if not url:
        return None
    
    try:
        # Handle GitHub URLs (new format)
        if '/articles/' in url:
            parts = url.split('/articles/', 1)
            if len(parts) >= 2:
                path_parts = parts[1].split('/')
                if len(path_parts) > 0 and path_parts[0]:
                    return path_parts[0]
        
        # Handle MS Learn URLs (legacy format)
        elif '/azure/' in url:
            parts = url.split('/azure/', 1)
            if len(parts) >= 2:
                path_parts = parts[1].split('/')
                if len(path_parts) > 0 and path_parts[0]:
                    return path_parts[0]
    except Exception:
        return None
    
    return None


def format_doc_set_name(doc_set: Optional[str]) -> str:
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
        'notification-hubs': 'Notification Hubs',
        'vpn-gateway': 'VPN Gateway'
    }
    
    return name_mappings.get(doc_set, doc_set.replace('-', ' ').title())