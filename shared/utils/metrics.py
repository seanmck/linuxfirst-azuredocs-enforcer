"""
Prometheus metrics utilities for the Azure Docs Enforcer application.
Provides standardized metrics collection and instrumentation.
"""
import time
import functools
from typing import Dict, Any, Optional, Callable
from contextlib import contextmanager
from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry, Info, start_http_server
import logging

logger = logging.getLogger(__name__)


class AppMetrics:
    """
    Centralized metrics collection for the Azure Docs Enforcer application.
    Provides business metrics, performance metrics, and operational metrics.
    """
    
    def __init__(self, registry: Optional[CollectorRegistry] = None):
        """Initialize metrics with optional custom registry"""
        self.registry = registry or CollectorRegistry()
        self._setup_metrics()
        
    def _setup_metrics(self):
        """Setup all application metrics"""
        
        # === BUSINESS METRICS ===
        
        # Scan metrics
        self.scans_total = Counter(
            'azuredocs_scans_total',
            'Total number of scans initiated',
            ['source'],  # manual/scheduled
            registry=self.registry
        )
        
        self.scans_completed = Counter(
            'azuredocs_scans_completed_total',
            'Total number of scans completed',
            ['status'],  # done/error
            registry=self.registry
        )
        
        self.scan_duration = Histogram(
            'azuredocs_scan_duration_seconds',
            'Duration of scan processing',
            [],  # GitHub-only scanning
            buckets=[60, 300, 900, 1800, 3600, 7200],  # 1min to 2 hours
            registry=self.registry
        )
        
        # Document processing metrics
        self.documents_processed = Counter(
            'azuredocs_documents_processed_total',
            'Total number of documents processed',
            ['source', 'status'],  # web/github, success/error
            registry=self.registry
        )
        
        self.document_processing_duration = Histogram(
            'azuredocs_document_processing_duration_seconds',
            'Duration of individual document processing',
            ['source'],
            buckets=[1, 5, 10, 30, 60, 120],  # 1sec to 2min
            registry=self.registry
        )
        
        # Bias detection metrics
        self.bias_detected = Counter(
            'azuredocs_bias_detected_total',
            'Total number of bias instances detected',
            ['detection_method', 'bias_type'],  # heuristic/llm, windows/platform
            registry=self.registry
        )
        
        self.snippets_analyzed = Counter(
            'azuredocs_snippets_analyzed_total',
            'Total number of code snippets analyzed',
            ['analysis_type'],  # heuristic/llm
            registry=self.registry
        )
        
        self.bias_detection_rate = Gauge(
            'azuredocs_bias_detection_rate',
            'Current bias detection rate (percentage)',
            ['time_window'],  # last_hour/last_day
            registry=self.registry
        )
        
        # === PERFORMANCE METRICS ===
        
        # Discovery metrics
        self.discovery_duration = Histogram(
            'azuredocs_discovery_duration_seconds',
            'Duration of GitHub file discovery',
            ['discovery_type'],  # incremental/initial/recovery
            buckets=[1, 5, 10, 30, 60, 300],
            registry=self.registry
        )
        
        self.files_discovered = Counter(
            'azuredocs_files_discovered_total',
            'Total number of files discovered',
            ['discovery_type'],
            registry=self.registry
        )
        
        # Queue metrics
        self.queue_tasks_published = Counter(
            'azuredocs_queue_tasks_published_total',
            'Total number of tasks published to queues',
            ['queue_name'],
            registry=self.registry
        )
        
        self.queue_tasks_processed = Counter(
            'azuredocs_queue_tasks_processed_total',
            'Total number of tasks processed from queues',
            ['queue_name', 'status'],  # success/error
            registry=self.registry
        )
        
        self.queue_processing_duration = Histogram(
            'azuredocs_queue_processing_duration_seconds',
            'Duration of queue task processing',
            ['queue_name'],
            buckets=[1, 5, 10, 30, 60, 300],
            registry=self.registry
        )
        
        # External API metrics
        self.api_requests_total = Counter(
            'azuredocs_api_requests_total',
            'Total number of external API requests',
            ['service', 'method', 'status_code'],  # azure_openai/github, GET/POST, 200/400/500
            registry=self.registry
        )
        
        self.api_request_duration = Histogram(
            'azuredocs_api_request_duration_seconds',
            'Duration of external API requests',
            ['service', 'method'],
            buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
            registry=self.registry
        )
        
        self.api_rate_limit_remaining = Gauge(
            'azuredocs_api_rate_limit_remaining',
            'Remaining API rate limit',
            ['service'],
            registry=self.registry
        )
        
        # === OPERATIONAL METRICS ===
        
        # Database metrics
        self.db_connections_active = Gauge(
            'azuredocs_db_connections_active',
            'Number of active database connections',
            registry=self.registry
        )
        
        self.db_queries_total = Counter(
            'azuredocs_db_queries_total',
            'Total number of database queries',
            ['operation'],  # select/insert/update/delete
            registry=self.registry
        )
        
        self.db_query_duration = Histogram(
            'azuredocs_db_query_duration_seconds',
            'Duration of database queries',
            ['operation'],
            buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
            registry=self.registry
        )
        
        # Service health
        self.service_up = Gauge(
            'azuredocs_service_up',
            'Service health status (1=up, 0=down)',
            ['service'],  # webui/mcp_server/queue_worker
            registry=self.registry
        )
        
        self.errors_total = Counter(
            'azuredocs_errors_total',
            'Total number of errors',
            ['service', 'error_type'],
            registry=self.registry
        )
        
        # Application info
        self.app_info = Info(
            'azuredocs_app_info',
            'Application information',
            registry=self.registry
        )
        
        # Set application info
        self.app_info.info({
            'name': 'azuredocs-enforcer',
            'component': 'metrics',
            'description': 'Azure documentation bias detection system'
        })
    
    # === BUSINESS METRIC HELPERS ===
    
    def record_scan_started(self, source: str = 'manual'):
        """Record that a GitHub scan has been started"""
        self.scans_total.labels(source=source).inc()
        
    def record_scan_completed(self, status: str, duration_seconds: float):
        """Record that a GitHub scan has been completed"""
        self.scans_completed.labels(status=status).inc()
        self.scan_duration.observe(duration_seconds)
        
    def record_document_processed(self, source: str, status: str, duration_seconds: float):
        """Record that a document has been processed"""
        self.documents_processed.labels(source=source, status=status).inc()
        self.document_processing_duration.labels(source=source).observe(duration_seconds)
        
    def record_bias_detected(self, detection_method: str, bias_type: str = 'windows'):
        """Record that bias has been detected"""
        self.bias_detected.labels(detection_method=detection_method, bias_type=bias_type).inc()
        
    def record_snippet_analyzed(self, analysis_type: str):
        """Record that a snippet has been analyzed"""
        self.snippets_analyzed.labels(analysis_type=analysis_type).inc()
        
    def update_bias_detection_rate(self, rate: float, time_window: str = 'last_hour'):
        """Update the current bias detection rate"""
        self.bias_detection_rate.labels(time_window=time_window).set(rate)
    
    def record_discovery_completed(self, discovery_type: str, files_count: int, duration_seconds: float):
        """Record that GitHub discovery has completed"""
        self.discovery_duration.labels(discovery_type=discovery_type).observe(duration_seconds)
        self.files_discovered.labels(discovery_type=discovery_type).inc(files_count)
    
    def record_file_change_processed(self, change_type: str, status: str, duration_seconds: float):
        """Record that a file change has been processed"""
        # Use existing document processing metrics
        self.documents_processed.labels(source='github', status=status).inc()
        self.document_processing_duration.labels(source='github').observe(duration_seconds)
    
    # === PERFORMANCE METRIC HELPERS ===
    
    def record_queue_task_published(self, queue_name: str):
        """Record that a task has been published to a queue"""
        self.queue_tasks_published.labels(queue_name=queue_name).inc()
        
    def record_queue_task_processed(self, queue_name: str, status: str, duration_seconds: float):
        """Record that a queue task has been processed"""
        self.queue_tasks_processed.labels(queue_name=queue_name, status=status).inc()
        self.queue_processing_duration.labels(queue_name=queue_name).observe(duration_seconds)
        
    def record_api_request(self, service: str, method: str, status_code: int, duration_seconds: float):
        """Record an external API request"""
        self.api_requests_total.labels(service=service, method=method, status_code=str(status_code)).inc()
        self.api_request_duration.labels(service=service, method=method).observe(duration_seconds)
        
    def update_api_rate_limit(self, service: str, remaining: int):
        """Update API rate limit remaining"""
        self.api_rate_limit_remaining.labels(service=service).set(remaining)
    
    # === OPERATIONAL METRIC HELPERS ===
    
    def update_db_connections(self, count: int):
        """Update active database connection count"""
        self.db_connections_active.set(count)
        
    def record_db_query(self, operation: str, duration_seconds: float):
        """Record a database query"""
        self.db_queries_total.labels(operation=operation).inc()
        self.db_query_duration.labels(operation=operation).observe(duration_seconds)
        
    def set_service_health(self, service: str, is_up: bool):
        """Set service health status"""
        self.service_up.labels(service=service).set(1 if is_up else 0)
        
    def record_error(self, service: str, error_type: str):
        """Record an error occurrence"""
        self.errors_total.labels(service=service, error_type=error_type).inc()
    
    # === CONTEXT MANAGERS ===
    
    @contextmanager
    def time_operation(self, metric_histogram, *labels):
        """Context manager to time an operation"""
        start_time = time.time()
        try:
            yield
        finally:
            duration = time.time() - start_time
            metric_histogram.labels(*labels).observe(duration)
    
    @contextmanager
    def time_api_request(self, service: str, method: str):
        """Context manager to time an API request"""
        start_time = time.time()
        status_code = 0
        try:
            yield
            status_code = 200  # Default success
        except Exception as e:
            status_code = getattr(e, 'status_code', 500)
            raise
        finally:
            duration = time.time() - start_time
            self.record_api_request(service, method, status_code, duration)
    
    @contextmanager
    def time_document_processing(self, source: str):
        """Context manager to time document processing"""
        start_time = time.time()
        status = 'error'
        try:
            yield
            status = 'success'
        finally:
            duration = time.time() - start_time
            self.record_document_processed(source, status, duration)


def timed_metric(metric_histogram, *labels):
    """Decorator to time function execution"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                return func(*args, **kwargs)
            finally:
                duration = time.time() - start_time
                metric_histogram.labels(*labels).observe(duration)
        return wrapper
    return decorator


def count_metric(metric_counter, *labels):
    """Decorator to count function calls"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                result = func(*args, **kwargs)
                metric_counter.labels(*labels, 'success').inc()
                return result
            except Exception as e:
                metric_counter.labels(*labels, 'error').inc()
                raise
        return wrapper
    return decorator


# Global metrics instance
_metrics_instance = None

def get_metrics() -> AppMetrics:
    """Get the global metrics instance"""
    global _metrics_instance
    if _metrics_instance is None:
        _metrics_instance = AppMetrics()
    return _metrics_instance


def start_metrics_server(port: int = 8000, addr: str = '0.0.0.0'):
    """Start the Prometheus metrics HTTP server"""
    try:
        start_http_server(port, addr)
        logger.info(f"Metrics server started on {addr}:{port}")
    except Exception as e:
        logger.error(f"Failed to start metrics server: {e}")
        raise