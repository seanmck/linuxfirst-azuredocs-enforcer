"""
LLMScoringWorker - Handles LLM scoring tasks from the llm_scoring queue
This worker is decoupled from the document worker to allow heuristic checks
to run at full speed while LLM calls run at rate-limited speed.
"""
import sys
import os
import time
import signal
import threading
from typing import Dict, Any

# Add the project root to the Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
sys.path.insert(0, project_root)

from shared.models import Page, Scan
from shared.infrastructure.queue_service import QueueService
from shared.application.progress_tracker import progress_tracker
from shared.application.scan_completion_service import ScanCompletionService
from shared.utils.database import SessionLocal
from shared.utils.logging import get_logger
from shared.utils.metrics import get_metrics
from scoring_service import ScoringService


class LLMScoringWorker:
    """Worker that processes LLM scoring tasks from the llm_scoring queue"""

    def __init__(self):
        self.queue_service = QueueService(queue_name='llm_scoring')
        self.scoring_service = ScoringService()
        self.logger = get_logger(__name__)
        self.metrics = get_metrics()
        self.worker_id = f"llm_scoring_worker_{os.getpid()}_{int(time.time())}"
        self.shutdown_event = threading.Event()
        self.setup_signal_handlers()

    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        def signal_handler(signum, frame):
            self.logger.info(f"Received signal {signum}, initiating graceful shutdown...")
            self.shutdown_event.set()

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

    def process_llm_task(self, message: Dict[str, Any]) -> bool:
        """
        Process a single LLM scoring task from the queue

        Args:
            message: LLM scoring message with scan_id, page_id, page_url, page_content

        Returns:
            True if successful, False otherwise
        """
        scan_id = message.get('scan_id')
        page_id = message.get('page_id')
        page_url = message.get('page_url')
        page_content = message.get('page_content')

        if not all([scan_id, page_id, page_url, page_content]):
            self.logger.error(f"Invalid LLM scoring message: missing required fields")
            return True  # Ack bad message to avoid infinite retry

        self.logger.info(f"Processing LLM scoring task: page_id={page_id}, url={page_url[:80]}...")

        processing_start_time = time.time()
        db_session = SessionLocal()

        try:
            # Check if scan was cancelled
            scan = db_session.query(Scan).filter(Scan.id == scan_id).first()
            if scan and scan.cancellation_requested:
                self.logger.info(f"Scan {scan_id} was cancelled, skipping LLM scoring for page {page_id}")
                return True

            # Get the page record
            page = db_session.query(Page).filter(Page.id == page_id).first()
            if not page:
                self.logger.warning(f"Page {page_id} not found, may have been deleted")
                return True  # Page deleted, skip

            # Call the LLM for holistic scoring (this is the slow part, ~60 sec)
            self.logger.info(f"[LLM] Calling MCP server for page {page_id}")
            mcp_result = self.scoring_service.apply_mcp_holistic_scoring(
                page_content, page_url
            )

            if mcp_result:
                mcp_result['review_method'] = 'llm'
                page.mcp_holistic = mcp_result
                self.logger.info(f"[LLM] Successfully scored page {page_id}, bias_types={mcp_result.get('bias_types', [])}")

                # Report bias if detected
                if mcp_result.get('bias_types'):
                    progress_tracker.report_page_result(
                        db_session, scan_id, page_url, True, mcp_result
                    )
            else:
                # LLM call failed
                page.mcp_holistic = {
                    'bias_types': [],
                    'summary': None,
                    'review_method': 'llm_error',
                    'error': 'Holistic scoring failed'
                }
                self.logger.warning(f"[LLM] Failed to score page {page_id}")

            db_session.commit()

            # Check if scan can be finalized now that this LLM task is complete
            completion_service = ScanCompletionService(db_session)
            completion_service.check_and_finalize(scan_id)

            # Record metrics
            processing_time = time.time() - processing_start_time
            self.metrics.record_file_change_processed('llm_scoring', 'success', processing_time)
            self.logger.info(f"[LLM] Completed page {page_id} in {processing_time:.1f}s")

            return True

        except Exception as e:
            self.logger.error(f"Error processing LLM scoring task for page {page_id}: {e}", exc_info=True)
            self.metrics.record_file_change_processed('llm_scoring', 'error', time.time() - processing_start_time)
            return False

        finally:
            db_session.close()

    def start_consuming(self):
        """Start consuming LLM scoring tasks from the queue"""
        self.logger.info("LLM scoring worker starting...")

        if not self.queue_service.connect():
            self.logger.error("Failed to connect to RabbitMQ")
            return

        try:
            self.logger.info("Starting to consume LLM scoring tasks...")
            self.queue_service.consume_tasks(self.process_llm_task, shutdown_event=self.shutdown_event)

        except Exception as e:
            self.logger.error(f"Error during LLM scoring task consumption: {e}", exc_info=True)

        finally:
            self.logger.info("LLM scoring worker shutting down gracefully...")
            self.queue_service.disconnect()


def main():
    """Main entry point for the LLM scoring worker"""
    logger = get_logger(__name__)
    try:
        logger.info("Starting LLM scoring worker...")
        worker = LLMScoringWorker()
        worker.start_consuming()

    except Exception as e:
        logger.error(f"Fatal error in LLM scoring worker: {e}", exc_info=True)


if __name__ == "__main__":
    main()
