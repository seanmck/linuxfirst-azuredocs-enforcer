"""
Shared HTTP client utilities for consistent HTTP operations across the codebase
Standardizes on httpx for both sync and async operations
"""
import httpx
import asyncio
from typing import Dict, Any, Optional, Union
from shared.config import config


class HTTPClient:
    """Synchronous HTTP client with consistent configuration"""
    
    def __init__(self, timeout: int = 30, headers: Optional[Dict[str, str]] = None):
        self.timeout = timeout
        self.headers = headers or {}
        
        # Add user agent from config
        if 'User-Agent' not in self.headers:
            self.headers['User-Agent'] = config.application.user_agent
            
        self.client = httpx.Client(
            timeout=timeout,
            headers=self.headers
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.client.close()

    def get(self, url: str, **kwargs) -> httpx.Response:
        """Make a GET request"""
        return self.client.get(url, **kwargs)

    def post(self, url: str, **kwargs) -> httpx.Response:
        """Make a POST request"""
        return self.client.post(url, **kwargs)

    def put(self, url: str, **kwargs) -> httpx.Response:
        """Make a PUT request"""
        return self.client.put(url, **kwargs)

    def delete(self, url: str, **kwargs) -> httpx.Response:
        """Make a DELETE request"""
        return self.client.delete(url, **kwargs)

    def close(self):
        """Close the client"""
        self.client.close()


class AsyncHTTPClient:
    """Asynchronous HTTP client with consistent configuration"""
    
    def __init__(self, timeout: int = 30, headers: Optional[Dict[str, str]] = None):
        self.timeout = timeout
        self.headers = headers or {}
        
        # Add user agent from config
        if 'User-Agent' not in self.headers:
            self.headers['User-Agent'] = config.application.user_agent
            
        self.client = httpx.AsyncClient(
            timeout=timeout,
            headers=self.headers
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()

    async def get(self, url: str, **kwargs) -> httpx.Response:
        """Make an async GET request"""
        return await self.client.get(url, **kwargs)

    async def post(self, url: str, **kwargs) -> httpx.Response:
        """Make an async POST request"""
        return await self.client.post(url, **kwargs)

    async def put(self, url: str, **kwargs) -> httpx.Response:
        """Make an async PUT request"""
        return await self.client.put(url, **kwargs)

    async def delete(self, url: str, **kwargs) -> httpx.Response:
        """Make an async DELETE request"""
        return await self.client.delete(url, **kwargs)

    async def close(self):
        """Close the async client"""
        await self.client.aclose()


# Utility functions for common patterns
def make_request(
    method: str, 
    url: str, 
    timeout: int = 30,
    **kwargs
) -> httpx.Response:
    """
    Make a synchronous HTTP request with standard configuration
    
    Args:
        method: HTTP method (GET, POST, etc.)
        url: URL to request
        timeout: Request timeout in seconds
        **kwargs: Additional arguments passed to httpx
        
    Returns:
        httpx.Response object
    """
    with HTTPClient(timeout=timeout) as client:
        return getattr(client, method.lower())(url, **kwargs)


async def make_async_request(
    method: str,
    url: str,
    timeout: int = 30,
    **kwargs
) -> httpx.Response:
    """
    Make an asynchronous HTTP request with standard configuration
    
    Args:
        method: HTTP method (GET, POST, etc.)
        url: URL to request
        timeout: Request timeout in seconds
        **kwargs: Additional arguments passed to httpx
        
    Returns:
        httpx.Response object
    """
    async with AsyncHTTPClient(timeout=timeout) as client:
        return await getattr(client, method.lower())(url, **kwargs)


def post_json(
    url: str,
    data: Dict[str, Any],
    timeout: int = 60,
    headers: Optional[Dict[str, str]] = None
) -> httpx.Response:
    """
    Make a synchronous POST request with JSON data
    
    Args:
        url: URL to post to
        data: Dictionary to send as JSON
        timeout: Request timeout in seconds
        headers: Optional additional headers
        
    Returns:
        httpx.Response object
    """
    request_headers = headers or {}
    request_headers['Content-Type'] = 'application/json'
    
    with HTTPClient(timeout=timeout, headers=request_headers) as client:
        return client.post(url, json=data)


async def post_json_async(
    url: str,
    data: Dict[str, Any],
    timeout: int = 60,
    headers: Optional[Dict[str, str]] = None
) -> httpx.Response:
    """
    Make an asynchronous POST request with JSON data
    
    Args:
        url: URL to post to
        data: Dictionary to send as JSON
        timeout: Request timeout in seconds
        headers: Optional additional headers
        
    Returns:
        httpx.Response object
    """
    request_headers = headers or {}
    request_headers['Content-Type'] = 'application/json'
    
    async with AsyncHTTPClient(timeout=timeout, headers=request_headers) as client:
        return await client.post(url, json=data)