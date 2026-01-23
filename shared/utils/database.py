"""
Shared database utilities for consistent database operations
"""
import time
from contextlib import contextmanager
from typing import Generator
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from shared.config import config
from shared.utils.logging import get_logger

logger = get_logger(__name__)

# Slow query threshold in milliseconds
SLOW_QUERY_THRESHOLD_MS = 500

# Create database engine and session factory using shared config
# Connection pool configuration for production performance
engine = create_engine(
    config.database.url,
    pool_size=10,           # Number of connections to keep in the pool
    max_overflow=20,        # Additional connections allowed beyond pool_size
    pool_timeout=30,        # Seconds to wait before giving up on getting a connection
    pool_recycle=1800,      # Recycle connections after 30 minutes (avoid stale connections)
    pool_pre_ping=True,     # Test connections before using them (handles disconnects)
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# Slow query detection using SQLAlchemy event listeners
@event.listens_for(engine, "before_cursor_execute")
def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    """Record query start time before execution."""
    conn.info.setdefault('query_start_time', []).append(time.time())


@event.listens_for(engine, "after_cursor_execute")
def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    """Log slow queries after execution."""
    start_time = conn.info['query_start_time'].pop(-1)
    duration_ms = (time.time() - start_time) * 1000

    if duration_ms > SLOW_QUERY_THRESHOLD_MS:
        # Truncate long statements for logging
        truncated_statement = statement[:500] + "..." if len(statement) > 500 else statement
        logger.warning(
            f"SLOW QUERY ({duration_ms:.2f}ms): {truncated_statement}"
        )


@event.listens_for(engine, "handle_error")
def handle_error(exception_context):
    """Clean up query_start_time on exception to prevent memory leak."""
    conn = exception_context.connection
    if conn is not None and 'query_start_time' in conn.info:
        # Pop the start time to prevent unbounded list growth
        # Use try-except to handle edge cases where list might be empty
        try:
            if conn.info['query_start_time']:
                conn.info['query_start_time'].pop(-1)
        except IndexError:
            # List was empty - safe to ignore
            pass


@contextmanager
def get_db_session() -> Generator[Session, None, None]:
    """
    Context manager for database sessions
    
    Yields:
        Database session that is automatically closed
    """
    session = SessionLocal()
    try:
        yield session
    except Exception as e:
        logger.error(f"Database error: {e}")
        session.rollback()
        raise
    finally:
        session.close()


def safe_commit(session: Session) -> bool:
    """
    Safely commit a database session with error handling
    
    Args:
        session: Database session to commit
        
    Returns:
        True if commit successful, False otherwise
    """
    try:
        session.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to commit database session: {e}")
        session.rollback()
        return False


def get_or_create(session: Session, model, **kwargs):
    """
    Get an existing object or create a new one
    
    Args:
        session: Database session
        model: SQLAlchemy model class
        **kwargs: Filter criteria and creation parameters
        
    Returns:
        Tuple of (instance, created) where created is boolean
    """
    instance = session.query(model).filter_by(**kwargs).first()
    if instance:
        return instance, False
    else:
        instance = model(**kwargs)
        session.add(instance)
        return instance, True


def get_db():
    """
    FastAPI dependency for database sessions
    
    Yields:
        Database session that is automatically closed
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()