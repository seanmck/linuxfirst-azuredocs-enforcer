"""
Shared logging utilities for consistent logging across the application
"""
import logging
import sys
from typing import Optional
from src.shared.config import config


def get_logger(name: str, level: Optional[str] = None) -> logging.Logger:
    """
    Get a logger with consistent configuration
    
    Args:
        name: Logger name (typically __name__)
        level: Optional logging level override
        
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    
    # Don't add handlers if they already exist
    if logger.handlers:
        return logger
    
    # Set level based on config or parameter
    log_level = level or ('DEBUG' if config.application.debug else 'INFO')
    logger.setLevel(getattr(logging, log_level.upper()))
    
    # Create console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logger.level)
    
    # Create formatter
    formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)
    
    # Add handler to logger
    logger.addHandler(handler)
    
    return logger


def log_task_start(task_type: str, url: str, scan_id: int):
    """Log the start of a task with consistent formatting"""
    logger = get_logger(__name__)
    logger.info(f"Starting {task_type} scan pipeline for URL: {url}, scan_id: {scan_id}")


def log_task_complete(task_type: str, url: str, scan_id: int, success: bool):
    """Log the completion of a task with consistent formatting"""
    logger = get_logger(__name__)
    status = "successfully" if success else "with errors"
    logger.info(f"Completed {task_type} scan {status} for URL: {url}, scan_id: {scan_id}")


def log_phase_transition(phase: str, scan_id: int):
    """Log phase transitions in scan processing"""
    logger = get_logger(__name__)
    logger.info(f"Scan {scan_id}: Transitioning to {phase} phase")


def log_metrics(metrics: dict, scan_id: int):
    """Log scan metrics in a consistent format"""
    logger = get_logger(__name__)
    logger.info(f"Scan {scan_id} metrics: {metrics}")


def log_error(message: str, exception: Optional[Exception] = None):
    """Log errors with optional exception details"""
    logger = get_logger(__name__)
    if exception:
        logger.error(f"{message}: {str(exception)}", exc_info=True)
    else:
        logger.error(message)