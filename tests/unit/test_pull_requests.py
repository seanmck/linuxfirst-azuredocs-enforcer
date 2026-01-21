"""
Unit tests for pull request tracking functionality.
"""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime


class TestPRSyncService:
    """Tests for PRSyncService."""

    def test_parse_compare_url_valid(self):
        """Should correctly parse a valid GitHub compare URL."""
        from services.worker.src.tasks.pr_sync import PRSyncService

        service = PRSyncService()
        url = "https://github.com/MicrosoftDocs/azure-docs-pr/compare/main...testuser:azure-docs-pr:linuxfirstdocs-storage-20240101?expand=1"

        result = service._parse_compare_url(url)

        assert result['owner'] == 'MicrosoftDocs'
        assert result['repo'] == 'azure-docs-pr'
        assert result['base_branch'] == 'main'
        assert result['head_user'] == 'testuser'
        assert result['head_branch'] == 'linuxfirstdocs-storage-20240101'

    def test_parse_compare_url_with_query_params(self):
        """Should handle URLs with query parameters."""
        from services.worker.src.tasks.pr_sync import PRSyncService

        service = PRSyncService()
        url = "https://github.com/MicrosoftDocs/azure-docs-pr/compare/main...user:repo:branch?title=Test&body=Description"

        result = service._parse_compare_url(url)

        assert result['head_branch'] == 'branch'

    def test_parse_compare_url_invalid(self):
        """Should return None values for invalid URLs."""
        from services.worker.src.tasks.pr_sync import PRSyncService

        service = PRSyncService()
        url = "https://github.com/invalid-url"

        result = service._parse_compare_url(url)

        assert result['owner'] is None
        assert result['repo'] is None
        assert result['head_branch'] is None


class TestPRQueries:
    """Tests for PR query helper functions."""

    def test_format_pull_requests_empty_list(self):
        """Should return empty list for empty input."""
        from services.web.src.utils.pr_queries import _format_pull_requests

        result = _format_pull_requests([])
        assert result == []

    def test_format_pull_requests_basic(self):
        """Should format a basic PR correctly."""
        from services.web.src.utils.pr_queries import _format_pull_requests

        mock_pr = MagicMock()
        mock_pr.id = 1
        mock_pr.compare_url = "https://github.com/test/compare"
        mock_pr.pr_url = None
        mock_pr.pr_number = None
        mock_pr.source_repo = "MicrosoftDocs/azure-docs-pr"
        mock_pr.target_branch = "main"
        mock_pr.head_branch = "test-branch"
        mock_pr.fork_repo = "user/azure-docs-pr"
        mock_pr.file_path = "articles/storage/test.md"
        mock_pr.doc_set = "storage"
        mock_pr.page_id = None
        mock_pr.status = "pending"
        mock_pr.pr_title = "Test PR"
        mock_pr.pr_state = None
        mock_pr.created_at = datetime(2024, 1, 15, 10, 30, 0)
        mock_pr.submitted_at = None
        mock_pr.closed_at = None
        mock_pr.merged_at = None
        mock_pr.last_synced_at = None

        result = _format_pull_requests([mock_pr])

        assert len(result) == 1
        assert result[0]['id'] == 1
        assert result[0]['status'] == 'pending'
        assert result[0]['doc_set'] == 'storage'
        assert result[0]['doc_set_display'] == 'Storage'
        assert result[0]['file_path'] == 'articles/storage/test.md'

    def test_format_pull_requests_with_dates(self):
        """Should format dates correctly."""
        from services.web.src.utils.pr_queries import _format_pull_requests

        mock_pr = MagicMock()
        mock_pr.id = 1
        mock_pr.compare_url = "https://github.com/test/compare"
        mock_pr.pr_url = "https://github.com/test/pull/123"
        mock_pr.pr_number = 123
        mock_pr.source_repo = "MicrosoftDocs/azure-docs-pr"
        mock_pr.target_branch = "main"
        mock_pr.head_branch = "test-branch"
        mock_pr.fork_repo = "user/azure-docs-pr"
        mock_pr.file_path = "articles/storage/test.md"
        mock_pr.doc_set = "storage"
        mock_pr.page_id = None
        mock_pr.status = "merged"
        mock_pr.pr_title = "Test PR"
        mock_pr.pr_state = "closed"
        mock_pr.created_at = datetime(2024, 1, 15, 10, 30, 0)
        mock_pr.submitted_at = datetime(2024, 1, 15, 11, 0, 0)
        mock_pr.closed_at = datetime(2024, 1, 16, 14, 0, 0)
        mock_pr.merged_at = datetime(2024, 1, 16, 14, 0, 0)
        mock_pr.last_synced_at = datetime(2024, 1, 16, 15, 0, 0)

        result = _format_pull_requests([mock_pr])

        assert len(result) == 1
        assert result[0]['created_at'] == '2024-01-15T10:30:00'
        assert result[0]['submitted_at'] == '2024-01-15T11:00:00'
        assert result[0]['merged_at'] == '2024-01-16T14:00:00'


class TestPRModel:
    """Tests for PullRequest model."""

    def test_model_has_required_fields(self):
        """Should have all required fields defined."""
        from shared.models import PullRequest

        # Check that the model has expected columns
        columns = PullRequest.__table__.columns.keys()

        required_fields = [
            'id', 'compare_url', 'pr_url', 'pr_number',
            'source_repo', 'target_branch', 'head_branch', 'fork_repo',
            'file_path', 'doc_set', 'page_id', 'user_id',
            'status', 'created_at', 'submitted_at', 'closed_at', 'merged_at',
            'last_synced_at', 'pr_title', 'pr_state', 'rewritten_document_id'
        ]

        for field in required_fields:
            assert field in columns, f"Missing field: {field}"

    def test_model_has_indexes(self):
        """Should have indexes defined."""
        from shared.models import PullRequest

        index_names = [idx.name for idx in PullRequest.__table__.indexes]

        expected_indexes = [
            'ix_pull_requests_user_id',
            'ix_pull_requests_status',
            'ix_pull_requests_doc_set',
            'ix_pull_requests_created_at',
            'ix_pull_requests_source_repo'
        ]

        for idx in expected_indexes:
            assert idx in index_names, f"Missing index: {idx}"


class TestPRStatsCalculation:
    """Tests for PR statistics calculation."""

    def test_stats_empty_db(self):
        """Should return zeros for empty database."""
        from services.web.src.utils.pr_queries import get_pull_request_stats

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.count.return_value = 0

        result = get_pull_request_stats(mock_db)

        assert result['total'] == 0
        assert result['pending'] == 0
        assert result['open'] == 0
        assert result['closed'] == 0
        assert result['merged'] == 0

    def test_stats_with_user_filter(self):
        """Should filter by user_id when provided."""
        from services.web.src.utils.pr_queries import get_pull_request_stats
        from shared.models import PullRequest

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.count.return_value = 5

        result = get_pull_request_stats(mock_db, user_id=1)

        # Verify filter was called with user_id
        mock_query.filter.assert_called()
        assert result['total'] == 5
