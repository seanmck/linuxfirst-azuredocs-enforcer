"""
Shared database utilities for consistent database operations
"""
from contextlib import contextmanager
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from shared.config import config
from shared.utils.logging import get_logger

logger = get_logger(__name__)

# Create database engine and session factory using shared config
engine = create_engine(config.database.url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


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