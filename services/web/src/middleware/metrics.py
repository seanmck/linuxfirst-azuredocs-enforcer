"""
FastAPI middleware for Prometheus metrics collection.
"""
import time
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from shared.utils.metrics import get_metrics


class PrometheusMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware to collect HTTP request metrics"""
    
    def __init__(self, app, service_name: str = "webui"):
        super().__init__(app)
        self.service_name = service_name
        self.metrics = get_metrics()
        
        # HTTP-specific metrics (separate from shared metrics)
        self.http_requests_total = Counter(
            'fastapi_http_requests_total',
            'Total HTTP requests',
            ['service', 'method', 'endpoint', 'status_code']
        )
        
        self.http_request_duration_seconds = Histogram(
            'fastapi_http_request_duration_seconds',
            'HTTP request duration in seconds',
            ['service', 'method', 'endpoint'],
            buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
        )
        
        # Set service as healthy when middleware is initialized
        self.metrics.set_service_health(service_name, True)
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip metrics collection for the metrics endpoint itself
        if request.url.path == "/metrics":
            return await call_next(request)
        
        start_time = time.time()
        method = request.method
        path = request.url.path
        
        # Normalize endpoint path (remove dynamic parts for better cardinality)
        endpoint = self._normalize_path(path)
        
        try:
            response = await call_next(request)
            status_code = response.status_code
            
            # Record successful request
            self._record_request(method, endpoint, status_code, start_time)
            
            return response
            
        except Exception as e:
            # Record failed request
            status_code = getattr(e, 'status_code', 500)
            self._record_request(method, endpoint, status_code, start_time)
            
            # Record error in application metrics
            self.metrics.record_error(self.service_name, type(e).__name__)
            
            raise
    
    def _normalize_path(self, path: str) -> str:
        """Normalize URL path to reduce cardinality in metrics"""
        # Handle common dynamic paths
        if path.startswith('/scan/'):
            parts = path.split('/')
            if len(parts) >= 3 and parts[2].isdigit():
                return '/scan/{id}'
        
        if path.startswith('/admin/'):
            return '/admin/*'
            
        # Return the original path for static routes
        return path
    
    def _record_request(self, method: str, endpoint: str, status_code: int, start_time: float):
        """Record HTTP request metrics"""
        duration = time.time() - start_time
        
        # Record in HTTP-specific metrics
        self.http_requests_total.labels(
            service=self.service_name,
            method=method,
            endpoint=endpoint,
            status_code=str(status_code)
        ).inc()
        
        self.http_request_duration_seconds.labels(
            service=self.service_name,
            method=method,
            endpoint=endpoint
        ).observe(duration)


def create_metrics_endpoint():
    """Create a FastAPI endpoint that serves Prometheus metrics"""
    
    async def metrics_endpoint():
        """Endpoint to serve Prometheus metrics"""
        metrics_data = generate_latest()
        return Response(
            content=metrics_data,
            media_type=CONTENT_TYPE_LATEST
        )
    
    return metrics_endpoint