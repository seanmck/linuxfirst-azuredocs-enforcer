"""
Pull Requests page and API endpoints for tracking bias fix contributions.
"""
from typing import Optional
from fastapi import APIRouter, Request, Query, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
import logging

from shared.utils.database import get_db
from shared.models import User
from routes.auth import get_current_user
from jinja_env import templates
from utils.pr_queries import (
    get_user_pull_requests,
    get_all_pull_requests,
    get_pull_request_stats,
    get_available_pr_docsets
)
from shared.utils.url_utils import format_doc_set_name

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/pull-requests", response_class=HTMLResponse)
async def pull_requests_page(
    request: Request,
    status: str = Query("open", description="Filter by status: open or closed"),
    docset: Optional[str] = Query(None, description="Filter by documentation set"),
    page: int = Query(1, ge=1, description="Page number"),
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Display pull requests page with two sections:
    - My Pull Requests (if logged in)
    - All Pull Requests
    """
    per_page = 50

    # Get user's pull requests if logged in
    my_prs = []
    my_prs_total = 0
    my_pr_stats = None

    if current_user:
        my_prs, my_prs_total = get_user_pull_requests(
            db=db,
            user_id=current_user.id,
            status=status,
            doc_set=docset,
            limit=per_page,
            offset=(page - 1) * per_page
        )
        my_pr_stats = get_pull_request_stats(db, user_id=current_user.id)

    # Get all pull requests
    all_prs, all_prs_total = get_all_pull_requests(
        db=db,
        status=status,
        doc_set=docset,
        limit=per_page,
        offset=(page - 1) * per_page
    )

    # Get overall stats
    overall_stats = get_pull_request_stats(db)

    # Get available docsets for filter dropdown
    available_docsets = get_available_pr_docsets(db)

    # Calculate pagination
    total_pages = max(1, (all_prs_total + per_page - 1) // per_page)

    return templates.TemplateResponse("pull_requests.html", {
        "request": request,
        "user": current_user,
        "status": status,
        "selected_docset": docset,
        "current_page": page,
        "total_pages": total_pages,
        "my_prs": my_prs,
        "my_prs_total": my_prs_total,
        "my_pr_stats": my_pr_stats,
        "all_prs": all_prs,
        "all_prs_total": all_prs_total,
        "overall_stats": overall_stats,
        "available_docsets": available_docsets,
        "format_doc_set_name": format_doc_set_name
    })


@router.get("/api/pull-requests")
async def api_pull_requests(
    status: str = Query("open", description="Filter by status: open or closed"),
    docset: Optional[str] = Query(None, description="Filter by documentation set"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(50, ge=1, le=100, description="Results per page"),
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    API endpoint to get pull requests with filtering and pagination.
    """
    offset = (page - 1) * per_page

    # Get all pull requests
    prs, total = get_all_pull_requests(
        db=db,
        status=status,
        doc_set=docset,
        limit=per_page,
        offset=offset
    )

    # Get stats
    stats = get_pull_request_stats(db)

    return {
        "pull_requests": prs,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (total + per_page - 1) // per_page),
        "stats": stats
    }


@router.get("/api/pull-requests/my")
async def api_my_pull_requests(
    status: str = Query("open", description="Filter by status: open or closed"),
    docset: Optional[str] = Query(None, description="Filter by documentation set"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(50, ge=1, le=100, description="Results per page"),
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    API endpoint to get the current user's pull requests.
    """
    if not current_user:
        return {
            "pull_requests": [],
            "total": 0,
            "page": page,
            "per_page": per_page,
            "total_pages": 0,
            "stats": None,
            "authenticated": False
        }

    offset = (page - 1) * per_page

    prs, total = get_user_pull_requests(
        db=db,
        user_id=current_user.id,
        status=status,
        doc_set=docset,
        limit=per_page,
        offset=offset
    )

    stats = get_pull_request_stats(db, user_id=current_user.id)

    return {
        "pull_requests": prs,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (total + per_page - 1) // per_page),
        "stats": stats,
        "authenticated": True
    }


@router.get("/api/pull-requests/stats")
async def api_pull_request_stats(
    current_user: Optional[User] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    API endpoint to get pull request statistics.
    """
    overall_stats = get_pull_request_stats(db)

    user_stats = None
    if current_user:
        user_stats = get_pull_request_stats(db, user_id=current_user.id)

    return {
        "overall": overall_stats,
        "user": user_stats,
        "authenticated": current_user is not None
    }
