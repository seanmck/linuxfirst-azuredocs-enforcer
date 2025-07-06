"""
Refactored Queue Worker - Uses extracted services for clean separation of concerns
This replaces the monolithic crawler/queue_worker.py
"""
import sys
import os
import time

# Add the project root to the Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.insert(0, project_root)

from typing import Dict, Any
from src.infrastructure.queue_service import QueueService
from src.application.scan_orchestrator import ScanOrchestrator
from src.shared.config import config
from src.shared.utils.database import SessionLocal
from src.shared.utils.logging import get_logger


class RefactoredQueueWorker:
    """
    Refactored queue worker that coordinates services instead of doing everything itself
    """
    
    def __init__(self):
        self.queue_service = QueueService()
        self.logger = get_logger(__name__)

    def process_task(self, task_data: Dict[str, Any]):
        """
        Process a scan task using the appropriate service
        
        Args:
            task_data: Dictionary containing task information
        """
        url = task_data.get('url')
        scan_id = task_data.get('scan_id')
        source = task_data.get('source', 'web')
        force_rescan = task_data.get('force_rescan', False)
        
        self.logger.info(f"Processing URL: {url} for scan_id: {scan_id} (source: {source}, force_rescan: {force_rescan})")
        
        # Create database session
        db_session = SessionLocal()
        
        try:
            # Create orchestrator with database session
            orchestrator = ScanOrchestrator(db_session)
            
            # Check if scan was cancelled before processing
            if orchestrator._check_cancellation(scan_id):
                self.logger.info(f"Scan {scan_id} was cancelled, skipping processing")
                return True  # Return True to acknowledge the message and remove it from queue
            
            # Process based on source type
            if source == 'github':
                success = orchestrator.process_github_scan(url, scan_id, force_rescan)
            else:
                success = orchestrator.process_web_scan(url, scan_id, force_rescan)
                
            if success:
                self.logger.info(f"Successfully completed {source} scan for {url}")
            else:
                self.logger.error(f"Failed to complete {source} scan for {url}")
                
        except Exception as e:
            self.logger.error(f"Unexpected error processing task: {e}", exc_info=True)
            
        finally:
            db_session.close()

    def start_consuming(self):
        """Start consuming tasks from the queue with resilient error handling"""
        self.logger.info("Refactored queue worker starting...")
        
        retry_count = 0
        max_retries = 3
        base_delay = 5  # seconds
        
        while retry_count < max_retries:
            try:
                self.logger.info(f"Starting to consume tasks (attempt {retry_count + 1}/{max_retries})...")
                # The queue service now handles its own connection retries
                self.queue_service.consume_tasks(self.process_task)
                
                # If we get here, consumption ended normally (e.g., KeyboardInterrupt)
                break
                
            except Exception as e:
                retry_count += 1
                self.logger.error(f"Error during task consumption (attempt {retry_count}/{max_retries}): {e}", exc_info=True)
                
                if retry_count < max_retries:
                    delay = base_delay * (2 ** (retry_count - 1))  # Exponential backoff
                    self.logger.info(f"Retrying in {delay} seconds...")
                    time.sleep(delay)
                else:
                    self.logger.error("Max retries reached. Queue worker shutting down.")
                    
        self.queue_service.disconnect()


def main():
    """Main entry point for the queue worker"""
    logger = get_logger(__name__)
    try:
        logger.info("Starting refactored queue worker...")
        worker = RefactoredQueueWorker()
        worker.start_consuming()
        
    except Exception as e:
        logger.error(f"Fatal error in queue worker: {e}", exc_info=True)


if __name__ == "__main__":
    main()