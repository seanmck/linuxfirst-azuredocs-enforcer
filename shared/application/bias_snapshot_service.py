"""Service for calculating and storing bias snapshots"""
import datetime
from typing import Dict, List, Optional, Tuple
from sqlalchemy import func, and_, select, distinct
from sqlalchemy.orm import Session
from shared.models import Page, Scan, BiasSnapshot, BiasSnapshotByDocset
from shared.utils.bias_utils import is_page_biased
from services.web.src.routes.docset import extract_doc_set_from_url


class BiasSnapshotService:
    """Service for calculating and storing daily bias snapshots"""
    
    def __init__(self, db_session: Session):
        self.db = db_session
    
    def calculate_snapshot_for_date(self, target_date: datetime.date) -> Optional[BiasSnapshot]:
        """
        Calculate bias snapshot for a specific date.
        
        This gets all unique URLs that have been scanned up to the target date,
        finds the most recent scan result for each URL as of that date,
        and calculates the overall bias percentage.
        
        Args:
            target_date: The date to calculate the snapshot for
            
        Returns:
            BiasSnapshot object or None if no data
        """
        # Convert date to datetime for comparison
        target_datetime = datetime.datetime.combine(target_date, datetime.time.max)
        
        # Get all distinct URLs with their most recent scan result as of target date
        # Using a subquery to get the latest scan_id for each URL
        latest_scan_subquery = (
            self.db.query(
                Page.url,
                func.max(Scan.started_at).label('latest_scan_time')
            )
            .join(Scan, Page.scan_id == Scan.id)
            .filter(
                and_(
                    Scan.status == 'done',
                    Scan.started_at <= target_datetime
                )
            )
            .group_by(Page.url)
            .subquery()
        )
        
        # Get the actual page records for these latest scans
        pages_query = (
            self.db.query(Page)
            .join(Scan, Page.scan_id == Scan.id)
            .join(
                latest_scan_subquery,
                and_(
                    Page.url == latest_scan_subquery.c.url,
                    Scan.started_at == latest_scan_subquery.c.latest_scan_time
                )
            )
        )
        
        pages = pages_query.all()
        
        if not pages:
            return None
        
        # Calculate bias statistics
        total_pages = len(pages)
        biased_pages = sum(1 for page in pages if is_page_biased(page))
        bias_percentage = (biased_pages / total_pages * 100) if total_pages > 0 else 0
        
        # Create snapshot
        snapshot = BiasSnapshot(
            date=target_date,
            total_pages=total_pages,
            biased_pages=biased_pages,
            bias_percentage=round(bias_percentage, 2),
            last_calculated_at=datetime.datetime.now(datetime.timezone.utc),
            additional_data={
                'calculation_method': 'latest_per_url',
                'included_scan_statuses': ['done']
            }
        )
        
        return snapshot
    
    def calculate_docset_snapshots_for_date(self, target_date: datetime.date) -> List[BiasSnapshotByDocset]:
        """
        Calculate bias snapshots for each doc set for a specific date.
        
        Args:
            target_date: The date to calculate snapshots for
            
        Returns:
            List of BiasSnapshotByDocset objects
        """
        # Convert date to datetime for comparison
        target_datetime = datetime.datetime.combine(target_date, datetime.time.max)
        
        # Get all distinct URLs with their most recent scan result as of target date
        latest_scan_subquery = (
            self.db.query(
                Page.url,
                func.max(Scan.started_at).label('latest_scan_time')
            )
            .join(Scan, Page.scan_id == Scan.id)
            .filter(
                and_(
                    Scan.status == 'done',
                    Scan.started_at <= target_datetime
                )
            )
            .group_by(Page.url)
            .subquery()
        )
        
        # Get the actual page records for these latest scans
        pages_query = (
            self.db.query(Page)
            .join(Scan, Page.scan_id == Scan.id)
            .join(
                latest_scan_subquery,
                and_(
                    Page.url == latest_scan_subquery.c.url,
                    Scan.started_at == latest_scan_subquery.c.latest_scan_time
                )
            )
        )
        
        pages = pages_query.all()
        
        if not pages:
            return []
        
        # Group pages by doc set
        pages_by_docset: Dict[str, List[Page]] = {}
        for page in pages:
            doc_set = extract_doc_set_from_url(page.url)
            if doc_set:
                if doc_set not in pages_by_docset:
                    pages_by_docset[doc_set] = []
                pages_by_docset[doc_set].append(page)
        
        # Calculate snapshots for each doc set
        snapshots = []
        for doc_set, doc_pages in pages_by_docset.items():
            total_pages = len(doc_pages)
            biased_pages = sum(1 for page in doc_pages if is_page_biased(page))
            bias_percentage = (biased_pages / total_pages * 100) if total_pages > 0 else 0
            
            snapshot = BiasSnapshotByDocset(
                date=target_date,
                doc_set=doc_set,
                total_pages=total_pages,
                biased_pages=biased_pages,
                bias_percentage=round(bias_percentage, 2)
            )
            snapshots.append(snapshot)
        
        return snapshots
    
    def save_snapshot(self, snapshot: BiasSnapshot) -> None:
        """Save or update a bias snapshot"""
        # Use merge to handle updates if snapshot for date already exists
        self.db.merge(snapshot)
        self.db.commit()
    
    def save_docset_snapshots(self, snapshots: List[BiasSnapshotByDocset]) -> None:
        """Save or update multiple docset snapshots"""
        for snapshot in snapshots:
            self.db.merge(snapshot)
        self.db.commit()
    
    def get_snapshot_for_date(self, target_date: datetime.date) -> Optional[BiasSnapshot]:
        """Retrieve a bias snapshot for a specific date"""
        return self.db.query(BiasSnapshot).filter(BiasSnapshot.date == target_date).first()
    
    def get_snapshots_range(self, start_date: datetime.date, end_date: datetime.date) -> List[BiasSnapshot]:
        """Retrieve bias snapshots for a date range"""
        return (
            self.db.query(BiasSnapshot)
            .filter(
                and_(
                    BiasSnapshot.date >= start_date,
                    BiasSnapshot.date <= end_date
                )
            )
            .order_by(BiasSnapshot.date)
            .all()
        )
    
    def get_docset_snapshots_range(
        self, doc_set: str, start_date: datetime.date, end_date: datetime.date
    ) -> List[BiasSnapshotByDocset]:
        """Retrieve docset bias snapshots for a date range"""
        return (
            self.db.query(BiasSnapshotByDocset)
            .filter(
                and_(
                    BiasSnapshotByDocset.doc_set == doc_set,
                    BiasSnapshotByDocset.date >= start_date,
                    BiasSnapshotByDocset.date <= end_date
                )
            )
            .order_by(BiasSnapshotByDocset.date)
            .all()
        )
    
    def calculate_and_save_today(self) -> Tuple[Optional[BiasSnapshot], List[BiasSnapshotByDocset]]:
        """
        Calculate and save snapshots for today.
        
        Returns:
            Tuple of (overall_snapshot, docset_snapshots)
        """
        today = datetime.date.today()
        
        # Calculate overall snapshot
        overall_snapshot = self.calculate_snapshot_for_date(today)
        if overall_snapshot:
            self.save_snapshot(overall_snapshot)
        
        # Calculate docset snapshots
        docset_snapshots = self.calculate_docset_snapshots_for_date(today)
        if docset_snapshots:
            self.save_docset_snapshots(docset_snapshots)
        
        return overall_snapshot, docset_snapshots
    
    def get_dates_needing_snapshots(self) -> List[datetime.date]:
        """
        Get list of dates that have scan data but no snapshots yet.
        
        Returns:
            List of dates needing snapshot calculation
        """
        # Get all dates with completed scans
        scan_dates_query = (
            self.db.query(func.date(Scan.started_at))
            .filter(Scan.status == 'done')
            .distinct()
            .order_by(func.date(Scan.started_at))
        )
        scan_dates = [row[0] for row in scan_dates_query.all()]
        
        # Get all dates with existing snapshots
        snapshot_dates_query = self.db.query(BiasSnapshot.date)
        snapshot_dates = {row[0] for row in snapshot_dates_query.all()}
        
        # Find dates needing snapshots
        dates_needing_snapshots = [
            date for date in scan_dates 
            if date not in snapshot_dates
        ]
        
        return dates_needing_snapshots