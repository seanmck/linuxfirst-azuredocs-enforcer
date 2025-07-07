"""
Custom exceptions for the Azure Docs Enforcer application
Provides consistent error handling across all components
"""


class AzureDocsEnforcerError(Exception):
    """Base exception for all application-specific errors"""
    
    def __init__(self, message: str, details: dict = None):
        self.message = message
        self.details = details or {}
        super().__init__(self.message)


class ConfigurationError(AzureDocsEnforcerError):
    """Raised when there are configuration-related errors"""
    pass


class DatabaseError(AzureDocsEnforcerError):
    """Raised when there are database-related errors"""
    pass


class CrawlerError(AzureDocsEnforcerError):
    """Raised when there are web crawling errors"""
    pass


class GitHubError(AzureDocsEnforcerError):
    """Raised when there are GitHub API related errors"""
    pass


class ScoringError(AzureDocsEnforcerError):
    """Raised when there are scoring-related errors"""
    pass


class QueueError(AzureDocsEnforcerError):
    """Raised when there are queue-related errors"""
    pass


class ValidationError(AzureDocsEnforcerError):
    """Raised when there are data validation errors"""
    pass


class HTTPError(AzureDocsEnforcerError):
    """Raised when there are HTTP request errors"""
    
    def __init__(self, message: str, status_code: int = None, response_text: str = None):
        details = {}
        if status_code is not None:
            details['status_code'] = status_code
        if response_text is not None:
            details['response_text'] = response_text
        super().__init__(message, details)
        self.status_code = status_code
        self.response_text = response_text


class ScanError(AzureDocsEnforcerError):
    """Raised when there are scan processing errors"""
    
    def __init__(self, message: str, scan_id: int = None, phase: str = None):
        details = {}
        if scan_id is not None:
            details['scan_id'] = scan_id
        if phase is not None:
            details['phase'] = phase
        super().__init__(message, details)
        self.scan_id = scan_id
        self.phase = phase