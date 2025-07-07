"""
Error handling utilities for consistent error management across the application
"""
import functools
import traceback
from typing import Callable, Any, Optional, Type, Union
from shared.exceptions import AzureDocsEnforcerError
from shared.utils.logging import get_logger

logger = get_logger(__name__)


def handle_errors(
    default_return: Any = None,
    exceptions: Union[Type[Exception], tuple] = Exception,
    reraise_as: Optional[Type[AzureDocsEnforcerError]] = None,
    log_error: bool = True
):
    """
    Decorator for consistent error handling
    
    Args:
        default_return: Value to return if an error occurs
        exceptions: Exception types to catch
        reraise_as: Exception type to reraise caught exceptions as
        log_error: Whether to log the error
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except exceptions as e:
                if log_error:
                    logger.error(f"Error in {func.__name__}: {str(e)}", exc_info=True)
                
                if reraise_as:
                    raise reraise_as(f"Error in {func.__name__}: {str(e)}") from e
                
                return default_return
        return wrapper
    return decorator


def safe_execute(
    func: Callable,
    *args,
    default_return: Any = None,
    log_error: bool = True,
    error_message: Optional[str] = None,
    **kwargs
) -> Any:
    """
    Safely execute a function with error handling
    
    Args:
        func: Function to execute
        *args: Positional arguments for the function
        default_return: Value to return if an error occurs
        log_error: Whether to log errors
        error_message: Custom error message
        **kwargs: Keyword arguments for the function
        
    Returns:
        Function result or default_return if error occurs
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        if log_error:
            message = error_message or f"Error executing {func.__name__}"
            logger.error(f"{message}: {str(e)}", exc_info=True)
        return default_return


def log_and_raise(
    exception_class: Type[AzureDocsEnforcerError],
    message: str,
    details: dict = None,
    original_exception: Exception = None
):
    """
    Log an error and raise a custom exception
    
    Args:
        exception_class: Custom exception class to raise
        message: Error message
        details: Additional error details
        original_exception: Original exception that caused this error
    """
    # Log the error
    if original_exception:
        logger.error(f"{message}: {str(original_exception)}", exc_info=True)
        raise exception_class(message, details) from original_exception
    else:
        logger.error(message)
        raise exception_class(message, details)


def format_error_details(error: Exception) -> dict:
    """
    Format error details for logging or API responses
    
    Args:
        error: Exception to format
        
    Returns:
        Dictionary with error details
    """
    details = {
        'type': type(error).__name__,
        'message': str(error),
        'traceback': traceback.format_exc()
    }
    
    # Add custom details if it's our custom exception
    if isinstance(error, AzureDocsEnforcerError):
        details.update(error.details)
    
    return details


class ErrorHandler:
    """Context manager for consistent error handling"""
    
    def __init__(
        self,
        operation_name: str,
        reraise_as: Optional[Type[AzureDocsEnforcerError]] = None,
        suppress_errors: bool = False,
        log_errors: bool = True
    ):
        self.operation_name = operation_name
        self.reraise_as = reraise_as
        self.suppress_errors = suppress_errors
        self.log_errors = log_errors
        self.error = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.error = exc_val
            
            if self.log_errors:
                logger.error(f"Error in {self.operation_name}: {str(exc_val)}", exc_info=True)
            
            if self.reraise_as:
                raise self.reraise_as(f"Error in {self.operation_name}: {str(exc_val)}") from exc_val
            
            if self.suppress_errors:
                return True  # Suppress the exception
        
        return False


def retry_on_error(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: Union[Type[Exception], tuple] = Exception
):
    """
    Decorator to retry a function on error
    
    Args:
        max_attempts: Maximum number of retry attempts
        delay: Initial delay between retries in seconds
        backoff_factor: Factor to multiply delay by on each retry
        exceptions: Exception types to retry on
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None
            
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        logger.warning(
                            f"Attempt {attempt + 1} failed for {func.__name__}: {str(e)}. "
                            f"Retrying in {current_delay} seconds..."
                        )
                        import time
                        time.sleep(current_delay)
                        current_delay *= backoff_factor
                    else:
                        logger.error(f"All {max_attempts} attempts failed for {func.__name__}")
            
            raise last_exception
        return wrapper
    return decorator