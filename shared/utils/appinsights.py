"""Azure Application Insights integration using OpenTelemetry."""
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def setup_appinsights(app=None, db_engine=None) -> bool:
    """
    Initialize Azure Application Insights using OpenTelemetry.

    Args:
        app: Optional FastAPI application instance (for future use)
        db_engine: Optional SQLAlchemy engine (for future use)

    Returns:
        True if App Insights was configured successfully, False otherwise.
    """
    connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")

    if not connection_string:
        logger.info("APPLICATIONINSIGHTS_CONNECTION_STRING not set, skipping App Insights setup")
        return False

    try:
        from azure.monitor.opentelemetry import configure_azure_monitor

        configure_azure_monitor(
            connection_string=connection_string,
            instrumentation_options={
                "fastapi": {"enabled": True},
                "psycopg2": {"enabled": True},
                "requests": {"enabled": True},
            }
        )
        logger.info("Azure Application Insights configured successfully")
        return True
    except ImportError:
        logger.warning("azure-monitor-opentelemetry package not installed, skipping App Insights")
        return False
    except Exception as e:
        logger.error(f"Failed to configure Azure Application Insights: {e}")
        return False


def get_instrumentation_key() -> Optional[str]:
    """
    Extract the instrumentation key from the connection string.

    This is used for the client-side JavaScript SDK which requires
    the instrumentation key rather than the full connection string.

    Returns:
        The instrumentation key if available, None otherwise.
    """
    connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not connection_string:
        return None

    try:
        # Connection string format: InstrumentationKey=xxx;IngestionEndpoint=xxx;...
        parts = dict(p.split("=", 1) for p in connection_string.split(";") if "=" in p)
        return parts.get("InstrumentationKey")
    except ValueError as e:
        logger.error(f"Failed to parse APPLICATIONINSIGHTS_CONNECTION_STRING: {e}")
        return None
