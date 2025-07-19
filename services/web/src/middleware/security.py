from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import time
import re
from collections import defaultdict
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class SecurityMiddleware(BaseHTTPMiddleware):
    """
    Security middleware to block malicious requests and prevent DoS attacks.
    """
    
    def __init__(self, app, rate_limit_per_minute: int = 60, block_duration_minutes: int = 30):
        super().__init__(app)
        self.rate_limit_per_minute = rate_limit_per_minute
        self.block_duration_minutes = block_duration_minutes
        self.request_counts = defaultdict(list)
        self.blocked_ips = {}
        
        # Patterns that indicate malicious requests
        self.malicious_patterns = [
            # Path traversal attempts
            re.compile(r'\.\./', re.IGNORECASE),
            re.compile(r'%2e%2e', re.IGNORECASE),
            re.compile(r'%252e%252e', re.IGNORECASE),
            
            # Shell injection attempts
            re.compile(r'/bin/sh', re.IGNORECASE),
            re.compile(r'cmd\.exe', re.IGNORECASE),
            re.compile(r'/etc/passwd', re.IGNORECASE),
            
            # PHP-specific attacks
            re.compile(r'eval-stdin\.php', re.IGNORECASE),
            re.compile(r'phpunit', re.IGNORECASE),
            re.compile(r'php://input', re.IGNORECASE),
            re.compile(r'auto_prepend_file', re.IGNORECASE),
            re.compile(r'allow_url_include', re.IGNORECASE),
            
            # Common vulnerability scanners
            re.compile(r'\.env$', re.IGNORECASE),
            re.compile(r'\.git/', re.IGNORECASE),
            re.compile(r'\.svn/', re.IGNORECASE),
            re.compile(r'\.htaccess', re.IGNORECASE),
            re.compile(r'web\.config', re.IGNORECASE),
            
            # Docker/container enumeration
            re.compile(r'/containers/json', re.IGNORECASE),
            re.compile(r'/_ping', re.IGNORECASE),
            
            # Common CMS/framework paths that don't apply to FastAPI
            re.compile(r'/wp-admin', re.IGNORECASE),
            re.compile(r'/wp-content', re.IGNORECASE),
            re.compile(r'/administrator', re.IGNORECASE),
            re.compile(r'/phpmyadmin', re.IGNORECASE),
            
            # SQL injection patterns
            re.compile(r'union.*select', re.IGNORECASE),
            re.compile(r'select.*from.*information_schema', re.IGNORECASE),
            
            # Other suspicious patterns
            re.compile(r'/cgi-bin/', re.IGNORECASE),
            re.compile(r'invokefunction', re.IGNORECASE),
            re.compile(r'call_user_func', re.IGNORECASE),
        ]
    
    def get_real_client_ip(self, request: Request) -> str:
        """Get the real client IP, handling nginx reverse proxy headers."""
        # Check nginx and common proxy headers in order of preference
        headers_to_check = [
            'x-forwarded-for',      # Standard header, nginx sets this with client IP
            'x-real-ip',            # Nginx-specific header
            'x-client-ip',          # Some proxies use this
            'cf-connecting-ip',     # Cloudflare (if behind CDN)
        ]
        
        for header in headers_to_check:
            ip = request.headers.get(header)
            if ip:
                # X-Forwarded-For can contain multiple IPs, take the first one
                if ',' in ip:
                    ip = ip.split(',')[0].strip()
                # Basic validation - ensure it's not empty and looks like an IP
                if ip and not ip.startswith('192.168.') and not ip.startswith('10.') and not ip.startswith('172.'):
                    return ip
        
        # Fallback to direct connection IP
        return request.client.host
    
    def is_request_malicious(self, request: Request) -> bool:
        """Check if the request matches any malicious patterns."""
        path = request.url.path
        query = str(request.url.query)
        full_url = f"{path}?{query}" if query else path
        
        for pattern in self.malicious_patterns:
            if pattern.search(full_url):
                return True
        
        return False
    
    def is_ip_blocked(self, client_ip: str) -> bool:
        """Check if an IP is currently blocked."""
        if client_ip in self.blocked_ips:
            block_until = self.blocked_ips[client_ip]
            if datetime.now() < block_until:
                return True
            else:
                # Block has expired
                del self.blocked_ips[client_ip]
        return False
    
    def is_rate_limited(self, client_ip: str) -> bool:
        """Check if the client has exceeded the rate limit."""
        now = datetime.now()
        minute_ago = now - timedelta(minutes=1)
        
        # Clean old entries
        self.request_counts[client_ip] = [
            timestamp for timestamp in self.request_counts[client_ip]
            if timestamp > minute_ago
        ]
        
        # Check rate limit
        if len(self.request_counts[client_ip]) >= self.rate_limit_per_minute:
            return True
        
        # Record this request
        self.request_counts[client_ip].append(now)
        return False
    
    def block_ip(self, client_ip: str):
        """Block an IP address for the configured duration."""
        block_until = datetime.now() + timedelta(minutes=self.block_duration_minutes)
        self.blocked_ips[client_ip] = block_until
        logger.warning(f"Blocked IP {client_ip} until {block_until}")
    
    async def dispatch(self, request: Request, call_next):
        # Get client IP (handle reverse proxy headers)
        client_ip = self.get_real_client_ip(request)
        
        # Check if IP is blocked
        if self.is_ip_blocked(client_ip):
            logger.warning(f"Rejected request from blocked IP: {client_ip}")
            return JSONResponse(
                status_code=403,
                content={"detail": "Access denied"}
            )
        
        # Check for malicious patterns
        if self.is_request_malicious(request):
            logger.warning(f"Blocked malicious request from {client_ip}: {request.url}")
            self.block_ip(client_ip)
            return JSONResponse(
                status_code=403,
                content={"detail": "Invalid request"}
            )
        
        # Check rate limit
        if self.is_rate_limited(client_ip):
            logger.warning(f"Rate limit exceeded for {client_ip}")
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests"}
            )
        
        # Process the request
        try:
            response = await call_next(request)
            return response
        except Exception as e:
            logger.error(f"Error processing request: {e}")
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error"}
            )