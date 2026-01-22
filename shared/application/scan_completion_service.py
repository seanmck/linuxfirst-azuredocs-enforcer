"""Service for checking and finalizing scan completion"""
import datetime
from sqlalchemy import and_, or_, func
from sqlalchemy.orm import Session
from shared.models import Page, Scan, Snippet
from shared.utils.logging import get_logger

logger = get_logger(__name__)


class ScanCompletionService:
    """Service for checking if a scan can be finalized and marking it complete"""

    def __init__(self, db_session: Session):
        self.db = db_session

    def check_and_finalize(self, scan_id: int) -> bool:
        """
        Check if a scan can be finalized and finalize it if ready.

        A scan is ready for finalization when:
        1. All queued files have been processed
        2. No pages are still pending LLM scoring

        Args:
            scan_id: The scan ID to check

        Returns:
            True if scan was finalized, False otherwise
        """
        try:
            scan = self.db.query(Scan).filter(Scan.id == scan_id).first()
            if not scan:
                return False

            # Already completed
            if scan.status == 'completed':
                return False

            # Check if all files have been processed
            if scan.total_files_queued == 0 or scan.total_files_completed < scan.total_files_queued:
                return False

            # Check if any pages are still pending LLM scoring
            pending_llm = self.db.query(Page).filter(
                Page.scan_id == scan_id,
                Page.mcp_holistic.op('->>')('review_method') == 'llm_pending'
            ).count()

            if pending_llm > 0:
                logger.debug(f"Scan {scan_id} has {pending_llm} pages still pending LLM scoring")
                return False

            # All conditions met - finalize the scan
            return self._finalize_scan(scan)

        except Exception as e:
            logger.error(f"Error checking scan completion for scan {scan_id}: {e}")
            return False

    def _finalize_scan(self, scan: Scan) -> bool:
        """
        Finalize a scan by calculating metrics and marking it complete.

        Args:
            scan: The Scan object to finalize

        Returns:
            True if finalized successfully, False otherwise
        """
        try:
            scan_id = scan.id

            # Calculate metrics
            processed_pages = self.db.query(Page).filter(
                Page.scan_id == scan_id,
                Page.status == 'processed'
            ).count()

            error_pages = self.db.query(Page).filter(
                Page.scan_id == scan_id,
                Page.status == 'error'
            ).count()

            # Count biased pages using severity field as authoritative indicator
            # Fallback to bias_types for legacy pages without severity
            biased_pages_count = self.db.query(Page).filter(
                Page.scan_id == scan_id,
                Page.mcp_holistic.isnot(None),
                or_(
                    # Primary: severity exists and is not 'none'
                    and_(
                        Page.mcp_holistic['severity'].astext.isnot(None),
                        func.lower(Page.mcp_holistic['severity'].astext) != 'none'
                    ),
                    # Fallback: severity missing but bias_types array is non-empty
                    and_(
                        Page.mcp_holistic['severity'].astext.is_(None),
                        func.jsonb_array_length(func.coalesce(Page.mcp_holistic['bias_types'], '[]')) > 0
                    )
                )
            ).count()

            # Count flagged snippets
            flagged_snippets_count = self.db.query(Snippet).join(Page).filter(
                Page.scan_id == scan_id,
                Snippet.llm_score.isnot(None)
            ).count()

            # Mark scan as complete
            scan.status = 'completed'
            scan.finished_at = datetime.datetime.now(datetime.timezone.utc)
            scan.biased_pages_count = biased_pages_count
            scan.flagged_snippets_count = flagged_snippets_count

            # Set last_commit_sha for future incremental scans
            if scan.working_commit_sha:
                scan.last_commit_sha = scan.working_commit_sha

            self.db.commit()

            logger.info(
                f"Scan {scan_id} finalized: {processed_pages} processed, "
                f"{error_pages} errors, {biased_pages_count} biased pages, "
                f"{flagged_snippets_count} flagged snippets"
            )

            # Update bias snapshots after scan completion
            self._update_bias_snapshots(scan_id)

            return True

        except Exception as e:
            logger.error(f"Error finalizing scan {scan.id}: {e}")
            return False

    def _update_bias_snapshots(self, scan_id: int):
        """Update bias snapshots after scan completion"""
        try:
            from shared.application.bias_snapshot_service import BiasSnapshotService
            snapshot_service = BiasSnapshotService(self.db)
            overall_snapshot, docset_snapshots = snapshot_service.calculate_and_save_today()
            if overall_snapshot:
                logger.info(
                    f"Updated bias snapshot: {overall_snapshot.bias_percentage}% bias "
                    f"({overall_snapshot.biased_pages}/{overall_snapshot.total_pages} pages)"
                )
            else:
                logger.warning("Failed to create bias snapshot after scan completion")
        except Exception as e:
            logger.error(f"Error updating bias snapshot after scan {scan_id}: {e}", exc_info=True)
