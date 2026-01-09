"""
OpenTelemetry distributed tracing setup for the application.

Provides auto-instrumentation for FastAPI, SQLAlchemy, and outbound HTTP requests.
Exports traces to Jaeger via OTLP protocol.

Usage:
    from shared.utils.tracing import setup_tracing
    setup_tracing(app, db_engine)

Environment variables:
    OTEL_EXPORTER_OTLP_ENDPOINT: The OTLP endpoint for trace export (e.g., http://localhost:4317)
    OTEL_SERVICE_NAME: Service name for traces (defaults to "azuredocs-enforcer")
"""
import os
import logging

logger = logging.getLogger(__name__)


def setup_tracing(app=None, db_engine=None):
    """
    Initialize OpenTelemetry tracing with Jaeger export.

    Args:
        app: FastAPI application instance to instrument
        db_engine: SQLAlchemy engine to instrument

    Returns:
        bool: True if tracing was set up, False if skipped (no endpoint configured)
    """
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")

    if not otlp_endpoint:
        logger.info("OTEL_EXPORTER_OTLP_ENDPOINT not set, skipping tracing setup")
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.semconv.resource import ResourceAttributes
    except ImportError:
        logger.warning(
            "OpenTelemetry packages not installed. Install with: "
            "pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp"
        )
        return False

    service_name = os.getenv("OTEL_SERVICE_NAME", "azuredocs-enforcer")

    # Create resource with service info
    resource = Resource(attributes={
        ResourceAttributes.SERVICE_NAME: service_name,
        ResourceAttributes.SERVICE_VERSION: "1.0.0",
    })

    # Set up tracer provider with resource
    provider = TracerProvider(resource=resource)

    # Configure OTLP exporter (Jaeger accepts OTLP on port 4317)
    otlp_exporter = OTLPSpanExporter(
        endpoint=otlp_endpoint,
        insecure=True  # Use insecure for local development
    )

    # Add batch processor for efficient span export
    processor = BatchSpanProcessor(otlp_exporter)
    provider.add_span_processor(processor)

    # Set as global tracer provider
    trace.set_tracer_provider(provider)

    logger.info(f"OpenTelemetry tracing configured, exporting to {otlp_endpoint}")

    # Instrument FastAPI
    if app:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            FastAPIInstrumentor.instrument_app(app)
            logger.info("FastAPI instrumented for tracing")
        except ImportError:
            logger.warning(
                "opentelemetry-instrumentation-fastapi not installed, skipping FastAPI instrumentation"
            )

    # Instrument SQLAlchemy
    if db_engine:
        try:
            from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
            SQLAlchemyInstrumentor().instrument(engine=db_engine)
            logger.info("SQLAlchemy instrumented for tracing")
        except ImportError:
            logger.warning(
                "opentelemetry-instrumentation-sqlalchemy not installed, skipping SQLAlchemy instrumentation"
            )

    # Instrument outgoing HTTP requests (requests library)
    try:
        from opentelemetry.instrumentation.requests import RequestsInstrumentor
        RequestsInstrumentor().instrument()
        logger.info("Requests library instrumented for tracing")
    except ImportError:
        logger.warning(
            "opentelemetry-instrumentation-requests not installed, skipping requests instrumentation"
        )

    # Instrument httpx (used by FastAPI's async client)
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        HTTPXClientInstrumentor().instrument()
        logger.info("HTTPX instrumented for tracing")
    except ImportError:
        pass  # httpx instrumentation is optional

    return True


def get_tracer(name: str = __name__):
    """
    Get a tracer instance for manual span creation.

    Args:
        name: Name for the tracer (usually __name__)

    Returns:
        Tracer instance
    """
    from opentelemetry import trace
    return trace.get_tracer(name)
