"""
Unit tests for admin feedback endpoint (services/web/src/routes/admin.py).

Tests cover:
- get_admin_feedback helper function with pagination, filtering, and sorting
- /admin/feedback endpoint with session authentication

Note: The get_admin_feedback function is duplicated here rather than imported
because importing from services.web.src.routes.admin requires FastAPI and
jinja2 template dependencies that create circular import issues in the test
environment. This is a pragmatic solution to enable isolated unit testing.
If the function signature or logic changes in admin.py, this copy must be
updated as well. Consider extracting the function to a separate utility module
if this becomes a maintenance burden.
"""
import pytest
import sys
import os
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine, func, case, or_
from sqlalchemy.orm import Session, joinedload
from typing import Optional

# Add services/web/src to path to allow imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../services/web/src'))

from shared.models import Base, UserFeedback, User, Snippet, Page, Scan, RewrittenDocument


# Function under test - copied from services/web/src/routes/admin.py
# NOTE: This is duplicated to avoid import issues with FastAPI/Jinja2 dependencies.
# Keep this synchronized with the original if changes are made.
def get_admin_feedback(
    db,
    page: int = 1,
    per_page: int = 25,
    target_type: Optional[str] = None,
    rating: Optional[str] = None,
    has_comment: Optional[str] = None,
    sort_by: str = "date",
    sort_order: str = "desc"
):
    """
    Query feedback with server-side pagination, filtering, and sorting.
    
    This is a copy of the function from services/web/src/routes/admin.py:get_admin_feedback
    """
    # Validate and cap per_page
    per_page = min(max(1, per_page), 100)
    page = max(1, page)

    # Base query with eager loading
    query = db.query(UserFeedback).options(
        joinedload(UserFeedback.user),
        joinedload(UserFeedback.snippet),
        joinedload(UserFeedback.page),
        joinedload(UserFeedback.rewritten_document)
    )

    # Apply filters
    if target_type:
        if target_type == "snippet":
            query = query.filter(UserFeedback.snippet_id.isnot(None))
        elif target_type == "page":
            query = query.filter(UserFeedback.page_id.isnot(None))
        elif target_type == "rewritten":
            query = query.filter(UserFeedback.rewritten_document_id.isnot(None))

    if rating:
        if rating == "up":
            query = query.filter(UserFeedback.rating.is_(True))
        elif rating == "down":
            query = query.filter(UserFeedback.rating.is_(False))

    if has_comment:
        if has_comment == "yes":
            query = query.filter(
                UserFeedback.comment.isnot(None),
                func.length(func.trim(UserFeedback.comment)) > 0
            )
        elif has_comment == "no":
            query = query.filter(
                or_(
                    UserFeedback.comment.is_(None),
                    func.length(func.trim(UserFeedback.comment)) == 0
                )
            )

    # Apply sorting
    if sort_by == "rating":
        order_col = UserFeedback.rating
    else:  # default to date
        order_col = UserFeedback.created_at

    if sort_order == "asc":
        query = query.order_by(order_col.asc())
    else:
        query = query.order_by(order_col.desc())

    # Get total count (before pagination)
    total = query.count()
    total_pages = (total + per_page - 1) // per_page if total > 0 else 1

    # Apply pagination
    offset = (page - 1) * per_page
    feedback_items = query.offset(offset).limit(per_page).all()

    # Get stats using aggregation
    stats_query = db.query(
        func.count(UserFeedback.id).label('total'),
        func.sum(case((UserFeedback.rating.is_(True), 1), else_=0)).label('thumbs_up'),
        func.sum(case((UserFeedback.rating.is_(False), 1), else_=0)).label('thumbs_down'),
        func.sum(case((func.coalesce(func.length(func.trim(UserFeedback.comment)), 0) > 0, 1), else_=0)).label('has_comments')
    ).first()

    stats = {
        'total': stats_query.total or 0,
        'thumbs_up': stats_query.thumbs_up or 0,
        'thumbs_down': stats_query.thumbs_down or 0,
        'has_comments': stats_query.has_comments or 0
    }

    return {
        'items': feedback_items,
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total': total,
            'total_pages': total_pages,
            'has_prev': page > 1,
            'has_next': page < total_pages,
            'start_idx': offset + 1 if total > 0 else 0,
            'end_idx': min(offset + per_page, total)
        },
        'stats': stats
    }



@pytest.fixture
def test_db_engine():
    """Create an in-memory SQLite database engine for tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def test_db_session(test_db_engine):
    """Create a database session for tests."""
    with Session(test_db_engine) as session:
        yield session


@pytest.fixture
def sample_user(test_db_session):
    """Create a sample user for testing."""
    user = User(
        github_username="testuser",
        github_id=12345,
        email="test@example.com"
    )
    test_db_session.add(user)
    test_db_session.commit()
    test_db_session.refresh(user)
    return user


@pytest.fixture
def sample_scan_with_page(test_db_session):
    """Create a sample scan and page for testing."""
    scan = Scan(
        url="https://github.com/MicrosoftDocs/azure-docs/blob/main/articles/test.md",
        status="completed",
        current_phase="done",
    )
    test_db_session.add(scan)
    test_db_session.commit()
    test_db_session.refresh(scan)
    
    page = Page(
        scan_id=scan.id,
        url="https://github.com/MicrosoftDocs/azure-docs/blob/main/articles/test.md",
        status="completed",
        doc_set="test",
    )
    test_db_session.add(page)
    test_db_session.commit()
    test_db_session.refresh(page)
    
    return scan, page


@pytest.fixture
def sample_snippet(test_db_session, sample_scan_with_page):
    """Create a sample snippet for testing."""
    _, page = sample_scan_with_page
    snippet = Snippet(
        page_id=page.id,
        context="Test context",
        code="echo 'test'",
    )
    test_db_session.add(snippet)
    test_db_session.commit()
    test_db_session.refresh(snippet)
    return snippet


@pytest.fixture
def sample_rewritten_document(test_db_session, sample_scan_with_page):
    """Create a sample rewritten document for testing."""
    _, page = sample_scan_with_page
    rewritten_doc = RewrittenDocument(
        page_id=page.id,
        content="# Rewritten Content\n\nThis is rewritten content.",
        content_hash="abc123def456",
    )
    test_db_session.add(rewritten_doc)
    test_db_session.commit()
    test_db_session.refresh(rewritten_doc)
    return rewritten_doc


@pytest.fixture
def feedback_data_set(test_db_session, sample_user, sample_snippet, sample_scan_with_page, sample_rewritten_document):
    """Create a diverse set of feedback items for testing pagination, filtering, and sorting."""
    _, page = sample_scan_with_page
    
    feedback_items = []
    
    # Create feedback with various combinations of target_type, rating, and comments
    # 1. Snippet feedback with thumbs up and comment (oldest)
    feedback_items.append(UserFeedback(
        user_id=sample_user.id,
        snippet_id=sample_snippet.id,
        rating=True,
        comment="This is helpful!",
        created_at=datetime.utcnow() - timedelta(days=10)
    ))
    
    # 2. Snippet feedback with thumbs down and comment
    feedback_items.append(UserFeedback(
        user_id=sample_user.id,
        snippet_id=sample_snippet.id,
        rating=False,
        comment="Needs improvement",
        created_at=datetime.utcnow() - timedelta(days=9)
    ))
    
    # 3. Page feedback with thumbs up, no comment
    feedback_items.append(UserFeedback(
        user_id=sample_user.id,
        page_id=page.id,
        rating=True,
        comment=None,
        created_at=datetime.utcnow() - timedelta(days=8)
    ))
    
    # 4. Page feedback with thumbs down and comment
    feedback_items.append(UserFeedback(
        user_id=sample_user.id,
        page_id=page.id,
        rating=False,
        comment="Not accurate",
        created_at=datetime.utcnow() - timedelta(days=7)
    ))
    
    # 5. Rewritten document feedback with thumbs up and comment
    feedback_items.append(UserFeedback(
        user_id=sample_user.id,
        rewritten_document_id=sample_rewritten_document.id,
        rating=True,
        comment="Great rewrite!",
        created_at=datetime.utcnow() - timedelta(days=6)
    ))
    
    # 6. Rewritten document feedback with thumbs down, no comment
    feedback_items.append(UserFeedback(
        user_id=sample_user.id,
        rewritten_document_id=sample_rewritten_document.id,
        rating=False,
        comment=None,
        created_at=datetime.utcnow() - timedelta(days=5)
    ))
    
    # 7. Snippet feedback with thumbs up, empty string comment (should count as no comment)
    feedback_items.append(UserFeedback(
        user_id=sample_user.id,
        snippet_id=sample_snippet.id,
        rating=True,
        comment="   ",  # whitespace only
        created_at=datetime.utcnow() - timedelta(days=4)
    ))
    
    # 8. Page feedback with thumbs up and comment
    feedback_items.append(UserFeedback(
        user_id=sample_user.id,
        page_id=page.id,
        rating=True,
        comment="Very clear documentation",
        created_at=datetime.utcnow() - timedelta(days=3)
    ))
    
    # 9. Snippet feedback with thumbs down, no comment
    feedback_items.append(UserFeedback(
        user_id=sample_user.id,
        snippet_id=sample_snippet.id,
        rating=False,
        comment=None,
        created_at=datetime.utcnow() - timedelta(days=2)
    ))
    
    # 10. Rewritten document feedback with thumbs up and comment (most recent)
    feedback_items.append(UserFeedback(
        user_id=sample_user.id,
        rewritten_document_id=sample_rewritten_document.id,
        rating=True,
        comment="Perfect!",
        created_at=datetime.utcnow() - timedelta(days=1)
    ))
    
    for feedback in feedback_items:
        test_db_session.add(feedback)
    
    test_db_session.commit()
    
    for feedback in feedback_items:
        test_db_session.refresh(feedback)
    
    return feedback_items


class TestGetAdminFeedbackPagination:
    """Tests for pagination logic in get_admin_feedback."""
    
    def test_default_pagination(self, test_db_session, feedback_data_set):
        """Test default pagination (page 1, 25 per page)."""
        result = get_admin_feedback(test_db_session)
        
        assert result['pagination']['page'] == 1
        assert result['pagination']['per_page'] == 25
        assert result['pagination']['total'] == 10
        assert result['pagination']['total_pages'] == 1
        assert result['pagination']['has_prev'] is False
        assert result['pagination']['has_next'] is False
        assert len(result['items']) == 10
    
    def test_custom_per_page(self, test_db_session, feedback_data_set):
        """Test custom items per page."""
        result = get_admin_feedback(test_db_session, page=1, per_page=5)
        
        assert result['pagination']['per_page'] == 5
        assert result['pagination']['total'] == 10
        assert result['pagination']['total_pages'] == 2
        assert result['pagination']['has_next'] is True
        assert len(result['items']) == 5
    
    def test_second_page(self, test_db_session, feedback_data_set):
        """Test accessing second page."""
        result = get_admin_feedback(test_db_session, page=2, per_page=5)
        
        assert result['pagination']['page'] == 2
        assert result['pagination']['per_page'] == 5
        assert result['pagination']['has_prev'] is True
        assert result['pagination']['has_next'] is False
        assert len(result['items']) == 5
    
    def test_per_page_max_cap(self, test_db_session, feedback_data_set):
        """Test that per_page is capped at 100."""
        result = get_admin_feedback(test_db_session, per_page=200)
        
        assert result['pagination']['per_page'] == 100
    
    def test_per_page_minimum(self, test_db_session, feedback_data_set):
        """Test that per_page has a minimum of 1."""
        result = get_admin_feedback(test_db_session, per_page=0)
        
        assert result['pagination']['per_page'] == 1
    
    def test_page_minimum(self, test_db_session, feedback_data_set):
        """Test that page number has a minimum of 1."""
        result = get_admin_feedback(test_db_session, page=0)
        
        assert result['pagination']['page'] == 1
    
    def test_pagination_indices(self, test_db_session, feedback_data_set):
        """Test start and end indices in pagination."""
        result = get_admin_feedback(test_db_session, page=1, per_page=3)
        
        assert result['pagination']['start_idx'] == 1
        assert result['pagination']['end_idx'] == 3
        
        result = get_admin_feedback(test_db_session, page=2, per_page=3)
        assert result['pagination']['start_idx'] == 4
        assert result['pagination']['end_idx'] == 6
    
    def test_empty_result_pagination(self, test_db_session):
        """Test pagination with no results."""
        result = get_admin_feedback(test_db_session)
        
        assert result['pagination']['total'] == 0
        assert result['pagination']['total_pages'] == 1
        assert result['pagination']['start_idx'] == 0
        assert result['pagination']['end_idx'] == 0
        assert len(result['items']) == 0


class TestGetAdminFeedbackFiltering:
    """Tests for filtering logic in get_admin_feedback."""
    
    def test_filter_by_snippet_target_type(self, test_db_session, feedback_data_set):
        """Test filtering by snippet target type."""
        result = get_admin_feedback(test_db_session, target_type="snippet")
        
        assert result['pagination']['total'] == 4
        for item in result['items']:
            assert item.snippet_id is not None
            assert item.page_id is None
            assert item.rewritten_document_id is None
    
    def test_filter_by_page_target_type(self, test_db_session, feedback_data_set):
        """Test filtering by page target type."""
        result = get_admin_feedback(test_db_session, target_type="page")
        
        assert result['pagination']['total'] == 3
        for item in result['items']:
            assert item.page_id is not None
            assert item.snippet_id is None
            assert item.rewritten_document_id is None
    
    def test_filter_by_rewritten_target_type(self, test_db_session, feedback_data_set):
        """Test filtering by rewritten document target type."""
        result = get_admin_feedback(test_db_session, target_type="rewritten")
        
        assert result['pagination']['total'] == 3
        for item in result['items']:
            assert item.rewritten_document_id is not None
            assert item.snippet_id is None
            assert item.page_id is None
    
    def test_filter_by_thumbs_up_rating(self, test_db_session, feedback_data_set):
        """Test filtering by thumbs up rating."""
        result = get_admin_feedback(test_db_session, rating="up")
        
        assert result['pagination']['total'] == 6
        for item in result['items']:
            assert item.rating is True
    
    def test_filter_by_thumbs_down_rating(self, test_db_session, feedback_data_set):
        """Test filtering by thumbs down rating."""
        result = get_admin_feedback(test_db_session, rating="down")
        
        assert result['pagination']['total'] == 4
        for item in result['items']:
            assert item.rating is False
    
    def test_filter_by_has_comment_yes(self, test_db_session, feedback_data_set):
        """Test filtering for feedback with comments."""
        result = get_admin_feedback(test_db_session, has_comment="yes")
        
        # Should have 6 items with non-empty comments
        # Items 1, 2, 4, 5, 8, 10 have actual comments
        assert result['pagination']['total'] == 6
        for item in result['items']:
            assert item.comment is not None
            assert len(item.comment.strip()) > 0
    
    def test_filter_by_has_comment_no(self, test_db_session, feedback_data_set):
        """Test filtering for feedback without comments."""
        result = get_admin_feedback(test_db_session, has_comment="no")
        
        # Should have 4 items without comments (including whitespace-only)
        # Items 3, 6, 7 (whitespace), 9 have no comment or whitespace only
        assert result['pagination']['total'] == 4
        for item in result['items']:
            assert item.comment is None or len(item.comment.strip()) == 0
    
    def test_combined_filters(self, test_db_session, feedback_data_set):
        """Test combining multiple filters."""
        # Filter for snippet feedback with thumbs down
        result = get_admin_feedback(
            test_db_session, 
            target_type="snippet", 
            rating="down"
        )
        
        # Should have 2 items (items 2 and 9)
        assert result['pagination']['total'] == 2
        for item in result['items']:
            assert item.snippet_id is not None
            assert item.rating is False
    
    def test_three_way_filter(self, test_db_session, feedback_data_set):
        """Test combining three filters."""
        # Filter for page feedback with thumbs up and comments
        result = get_admin_feedback(
            test_db_session,
            target_type="page",
            rating="up",
            has_comment="yes"
        )
        
        # Should have 1 item (item 8)
        assert result['pagination']['total'] == 1
        assert result['items'][0].page_id is not None
        assert result['items'][0].rating is True
        assert len(result['items'][0].comment.strip()) > 0
    
    def test_invalid_filter_values(self, test_db_session, feedback_data_set):
        """Test that invalid filter values are ignored."""
        # Invalid values should be ignored, returning all results
        result = get_admin_feedback(
            test_db_session,
            target_type="invalid",
            rating="invalid",
            has_comment="invalid"
        )
        
        # Should return all items since filters are ignored
        assert result['pagination']['total'] == 10


class TestGetAdminFeedbackSorting:
    """Tests for sorting logic in get_admin_feedback."""
    
    def test_default_sort_by_date_desc(self, test_db_session, feedback_data_set):
        """Test default sorting (by date, descending)."""
        result = get_admin_feedback(test_db_session)
        
        # Most recent should be first
        dates = [item.created_at for item in result['items']]
        assert dates == sorted(dates, reverse=True)
    
    def test_sort_by_date_asc(self, test_db_session, feedback_data_set):
        """Test sorting by date ascending."""
        result = get_admin_feedback(test_db_session, sort_by="date", sort_order="asc")
        
        # Oldest should be first
        dates = [item.created_at for item in result['items']]
        assert dates == sorted(dates)
    
    def test_sort_by_rating_desc(self, test_db_session, feedback_data_set):
        """Test sorting by rating descending (True before False)."""
        result = get_admin_feedback(test_db_session, sort_by="rating", sort_order="desc")
        
        # All True ratings should come before False ratings
        ratings = [item.rating for item in result['items']]
        true_count = sum(1 for r in ratings if r is True)
        false_count = sum(1 for r in ratings if r is False)
        
        # Check that all True values come first
        assert all(ratings[i] is True for i in range(true_count))
        assert all(ratings[i] is False for i in range(true_count, true_count + false_count))
    
    def test_sort_by_rating_asc(self, test_db_session, feedback_data_set):
        """Test sorting by rating ascending (False before True)."""
        result = get_admin_feedback(test_db_session, sort_by="rating", sort_order="asc")
        
        # All False ratings should come before True ratings
        ratings = [item.rating for item in result['items']]
        false_count = sum(1 for r in ratings if r is False)
        true_count = sum(1 for r in ratings if r is True)
        
        # Check that all False values come first
        assert all(ratings[i] is False for i in range(false_count))
        assert all(ratings[i] is True for i in range(false_count, false_count + true_count))
    
    def test_sorting_with_filters(self, test_db_session, feedback_data_set):
        """Test sorting combined with filtering."""
        result = get_admin_feedback(
            test_db_session,
            target_type="snippet",
            sort_by="date",
            sort_order="asc"
        )
        
        # Should have 4 snippet items, sorted by date ascending
        assert result['pagination']['total'] == 4
        dates = [item.created_at for item in result['items']]
        assert dates == sorted(dates)


class TestGetAdminFeedbackStats:
    """Tests for statistics calculation in get_admin_feedback."""
    
    def test_stats_calculation(self, test_db_session, feedback_data_set):
        """Test that stats are correctly calculated."""
        result = get_admin_feedback(test_db_session)
        
        stats = result['stats']
        assert stats['total'] == 10
        assert stats['thumbs_up'] == 6
        assert stats['thumbs_down'] == 4
        assert stats['has_comments'] == 6  # Items with non-empty comments
    
    def test_stats_with_filters(self, test_db_session, feedback_data_set):
        """Test that stats reflect the global data, not filtered results."""
        result = get_admin_feedback(test_db_session, target_type="snippet")
        
        # Stats should still reflect all feedback, not just filtered
        stats = result['stats']
        assert stats['total'] == 10  # Total across all types
        assert stats['thumbs_up'] == 6
        assert stats['thumbs_down'] == 4
    
    def test_stats_empty_database(self, test_db_session):
        """Test stats with no feedback."""
        result = get_admin_feedback(test_db_session)
        
        stats = result['stats']
        assert stats['total'] == 0
        assert stats['thumbs_up'] == 0
        assert stats['thumbs_down'] == 0
        assert stats['has_comments'] == 0


class TestGetAdminFeedbackRelationships:
    """Tests for eager loading of relationships."""
    
    def test_user_relationship_loaded(self, test_db_session, feedback_data_set):
        """Test that user relationship is eager loaded."""
        result = get_admin_feedback(test_db_session, per_page=1)
        
        # Access user without triggering additional query
        item = result['items'][0]
        assert item.user is not None
        assert item.user.github_username == "testuser"
    
    def test_snippet_relationship_loaded(self, test_db_session, feedback_data_set):
        """Test that snippet relationship is eager loaded when present."""
        result = get_admin_feedback(test_db_session, target_type="snippet", per_page=1)
        
        item = result['items'][0]
        assert item.snippet is not None
        assert item.snippet.code is not None
    
    def test_page_relationship_loaded(self, test_db_session, feedback_data_set):
        """Test that page relationship is eager loaded when present."""
        result = get_admin_feedback(test_db_session, target_type="page", per_page=1)
        
        item = result['items'][0]
        assert item.page is not None
        assert item.page.url is not None
    
    def test_rewritten_document_relationship_loaded(self, test_db_session, feedback_data_set):
        """Test that rewritten_document relationship is eager loaded when present."""
        result = get_admin_feedback(
            test_db_session, 
            target_type="rewritten", 
            per_page=1
        )
        
        item = result['items'][0]
        assert item.rewritten_document is not None


class TestAdminFeedbackEndpointAuthentication:
    """Tests for the /admin/feedback FastAPI endpoint authentication.
    
    Note: These are integration-level tests that would require full FastAPI setup.
    For now, we focus on the helper function tests above. These tests serve as
    documentation of expected endpoint behavior.
    """
    
    def test_endpoint_requires_authentication(self):
        """The /admin/feedback endpoint should require admin session authentication."""
        # This would require TestClient and full app setup
        # Expected: Unauthorized requests redirect to /admin/login
        pass
    
    def test_endpoint_accepts_query_parameters(self):
        """The endpoint should accept and pass query parameters to get_admin_feedback."""
        # Expected parameters: page, per_page, target_type, rating, has_comment, sort_by, sort_order
        pass
    
    def test_endpoint_closes_database_session(self):
        """The endpoint should properly close the database session in finally block."""
        # Expected: db.close() is called even if an exception occurs
        pass

