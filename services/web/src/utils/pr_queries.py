"""
Query helpers for Pull Request tracking.
"""

from sqlalchemy import func, desc
from sqlalchemy.orm import Session
from shared.models import PullRequest, User
from shared.utils.url_utils import format_doc_set_name
from typing import Dict, List, Any, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def get_user_pull_requests(
    db: Session,
    user_id: int,
    status: Optional[str] = None,
    doc_set: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """
    Get pull requests created by a specific user.

    Args:
        db: Database session
        user_id: User ID to filter by
        status: Filter by status ('pending', 'open', 'closed', 'merged')
        doc_set: Filter by documentation set
        limit: Maximum number of results
        offset: Offset for pagination

    Returns:
        List of pull request dictionaries
    """
    query = db.query(PullRequest).filter(PullRequest.user_id == user_id)

    if status:
        if status == 'open':
            query = query.filter(PullRequest.status.in_(['pending', 'open']))
        elif status == 'closed':
            query = query.filter(PullRequest.status.in_(['closed', 'merged']))
        else:
            query = query.filter(PullRequest.status == status)

    if doc_set:
        query = query.filter(PullRequest.doc_set == doc_set)

    query = query.order_by(desc(PullRequest.created_at))

    total_count = query.count()
    pull_requests = query.offset(offset).limit(limit).all()

    return _format_pull_requests(pull_requests), total_count


def get_all_pull_requests(
    db: Session,
    status: Optional[str] = None,
    doc_set: Optional[str] = None,
    limit: int = 50,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """
    Get all pull requests with optional filtering.

    Args:
        db: Database session
        status: Filter by status ('open', 'closed')
        doc_set: Filter by documentation set
        limit: Maximum number of results
        offset: Offset for pagination

    Returns:
        List of pull request dictionaries and total count
    """
    query = db.query(PullRequest).outerjoin(User, PullRequest.user_id == User.id)

    if status:
        if status == 'open':
            query = query.filter(PullRequest.status.in_(['pending', 'open']))
        elif status == 'closed':
            query = query.filter(PullRequest.status.in_(['closed', 'merged']))
        else:
            query = query.filter(PullRequest.status == status)

    if doc_set:
        query = query.filter(PullRequest.doc_set == doc_set)

    query = query.order_by(desc(PullRequest.created_at))

    total_count = query.count()
    pull_requests = query.offset(offset).limit(limit).all()

    return _format_pull_requests(pull_requests, include_user=True, db=db), total_count


def get_pull_request_stats(db: Session, user_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Get statistics about pull requests.

    Args:
        db: Database session
        user_id: Optional user ID to filter by

    Returns:
        Dictionary with PR statistics
    """
    base_query = db.query(PullRequest)

    if user_id:
        base_query = base_query.filter(PullRequest.user_id == user_id)

    total = base_query.count()
    pending = base_query.filter(PullRequest.status == 'pending').count()
    open_prs = base_query.filter(PullRequest.status == 'open').count()
    closed = base_query.filter(PullRequest.status == 'closed').count()
    merged = base_query.filter(PullRequest.status == 'merged').count()

    return {
        'total': total,
        'pending': pending,
        'open': open_prs,
        'closed': closed,
        'merged': merged,
        'open_total': pending + open_prs,  # Combined for "Open" tab
        'closed_total': closed + merged     # Combined for "Closed" tab
    }


def get_available_pr_docsets(db: Session) -> List[str]:
    """
    Get list of documentation sets that have associated pull requests.

    Args:
        db: Database session

    Returns:
        List of docset names
    """
    docsets = (
        db.query(PullRequest.doc_set)
        .filter(PullRequest.doc_set.isnot(None))
        .distinct()
        .all()
    )

    return [ds[0] for ds in docsets if ds[0]]


def create_pull_request_record(
    db: Session,
    compare_url: str,
    source_repo: str,
    head_branch: str,
    file_path: str,
    user_id: Optional[int] = None,
    target_branch: str = "main",
    fork_repo: Optional[str] = None,
    doc_set: Optional[str] = None,
    page_id: Optional[int] = None,
    rewritten_document_id: Optional[int] = None,
    pr_title: Optional[str] = None
) -> PullRequest:
    """
    Create a new pull request record.

    Args:
        db: Database session
        compare_url: GitHub compare/PR creation URL
        source_repo: Source repository (e.g., "MicrosoftDocs/azure-docs-pr")
        head_branch: Branch with changes
        file_path: Path to the file being changed
        user_id: User ID who created the PR
        target_branch: Base branch (default: main)
        fork_repo: User's fork repository name
        doc_set: Documentation set name
        page_id: Associated page ID
        rewritten_document_id: Associated rewritten document ID
        pr_title: Title for the PR

    Returns:
        Created PullRequest object
    """
    # Check if PR record already exists for this compare_url
    existing = db.query(PullRequest).filter(
        PullRequest.compare_url == compare_url
    ).first()

    if existing:
        logger.info(f"PR record already exists for compare_url: {compare_url}")
        return existing

    pr = PullRequest(
        compare_url=compare_url,
        source_repo=source_repo,
        target_branch=target_branch,
        head_branch=head_branch,
        fork_repo=fork_repo,
        file_path=file_path,
        doc_set=doc_set,
        page_id=page_id,
        rewritten_document_id=rewritten_document_id,
        user_id=user_id,
        status='pending',
        pr_title=pr_title
    )

    db.add(pr)
    db.commit()
    db.refresh(pr)

    logger.info(f"Created PR record {pr.id} for {file_path}")
    return pr


def update_pull_request_from_github(
    db: Session,
    pr_id: int,
    pr_url: Optional[str] = None,
    pr_number: Optional[int] = None,
    pr_state: Optional[str] = None,
    status: Optional[str] = None,
    pr_title: Optional[str] = None,
    merged_at: Optional[datetime] = None,
    closed_at: Optional[datetime] = None
) -> Optional[PullRequest]:
    """
    Update a pull request record with data from GitHub.

    Args:
        db: Database session
        pr_id: Pull request record ID
        pr_url: GitHub PR URL
        pr_number: GitHub PR number
        pr_state: GitHub PR state
        status: Internal status
        pr_title: PR title
        merged_at: When PR was merged
        closed_at: When PR was closed

    Returns:
        Updated PullRequest or None if not found
    """
    pr = db.query(PullRequest).filter(PullRequest.id == pr_id).first()

    if not pr:
        return None

    if pr_url:
        pr.pr_url = pr_url
    if pr_number:
        pr.pr_number = pr_number
    if pr_state:
        pr.pr_state = pr_state
    if status:
        pr.status = status
    if pr_title:
        pr.pr_title = pr_title
    if merged_at:
        pr.merged_at = merged_at
    if closed_at:
        pr.closed_at = closed_at

    # Update submitted_at if we now have a PR URL and didn't before
    if pr_url and not pr.submitted_at:
        pr.submitted_at = datetime.utcnow()

    pr.last_synced_at = datetime.utcnow()

    db.commit()
    db.refresh(pr)

    return pr


def _format_pull_requests(
    pull_requests: List[PullRequest],
    include_user: bool = False,
    db: Optional[Session] = None
) -> List[Dict[str, Any]]:
    """
    Format pull request objects into dictionaries.

    Args:
        pull_requests: List of PullRequest objects
        include_user: Whether to include user information
        db: Database session (required if include_user is True)

    Returns:
        List of formatted pull request dictionaries
    """
    result = []

    for pr in pull_requests:
        formatted = {
            'id': pr.id,
            'compare_url': pr.compare_url,
            'pr_url': pr.pr_url,
            'pr_number': pr.pr_number,
            'source_repo': pr.source_repo,
            'target_branch': pr.target_branch,
            'head_branch': pr.head_branch,
            'fork_repo': pr.fork_repo,
            'file_path': pr.file_path,
            'doc_set': pr.doc_set,
            'doc_set_display': format_doc_set_name(pr.doc_set) if pr.doc_set else None,
            'page_id': pr.page_id,
            'status': pr.status,
            'pr_title': pr.pr_title,
            'pr_state': pr.pr_state,
            'created_at': pr.created_at.isoformat() if pr.created_at else None,
            'submitted_at': pr.submitted_at.isoformat() if pr.submitted_at else None,
            'closed_at': pr.closed_at.isoformat() if pr.closed_at else None,
            'merged_at': pr.merged_at.isoformat() if pr.merged_at else None,
            'last_synced_at': pr.last_synced_at.isoformat() if pr.last_synced_at else None,
        }

        if include_user and db:
            user = db.query(User).filter(User.id == pr.user_id).first() if pr.user_id else None
            formatted['user'] = {
                'id': user.id,
                'username': user.github_username,
                'avatar_url': user.avatar_url
            } if user else None

        result.append(formatted)

    return result
