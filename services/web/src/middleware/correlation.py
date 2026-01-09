"""
Correlation ID middleware for request tracing across services.

Generates or propagates X-Correlation-ID headers for request tracking.
"""
import uuid
import contextvars
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

# Context variable for request-scoped correlation ID
correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    'correlation_id', default=''
)


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Middleware that generates/propagates correlation IDs for request tracking."""

    async def dispatch(self, request: Request, call_next):
        # Get correlation ID from request header or generate a new one
        correlation_id = request.headers.get('X-Correlation-ID')
        if not correlation_id:
            correlation_id = str(uuid.uuid4())

        # Set in context var for access throughout request lifecycle
        correlation_id_var.set(correlation_id)

        # Add to request state for easy access in route handlers
        request.state.correlation_id = correlation_id

        # Process request
        response = await call_next(request)

        # Add correlation ID to response headers
        response.headers['X-Correlation-ID'] = correlation_id
        return response


def get_correlation_id() -> str:
    """Get the current request's correlation ID.

    Returns:
        The correlation ID for the current request, or empty string if not in request context.
    """
    return correlation_id_var.get()
