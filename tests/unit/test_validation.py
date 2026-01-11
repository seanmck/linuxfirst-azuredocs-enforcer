"""
Unit tests for shared/utils/validation.py
"""
from shared.utils.validation import (
    is_valid_url,
    is_github_url,
    validate_task_data,
    sanitize_filename,
    validate_scan_metrics,
)


class TestIsValidUrl:
    """Tests for is_valid_url function."""

    def test_valid_https_url(self):
        """Valid HTTPS URLs should return True."""
        assert is_valid_url("https://example.com") is True
        assert is_valid_url("https://example.com/path") is True
        assert is_valid_url("https://example.com:8080/path?query=1") is True

    def test_valid_http_url(self):
        """Valid HTTP URLs should return True."""
        assert is_valid_url("http://example.com") is True

    def test_missing_scheme_returns_false(self):
        """URLs without scheme should return False."""
        assert is_valid_url("example.com") is False
        assert is_valid_url("www.example.com") is False

    def test_missing_netloc_returns_false(self):
        """URLs without netloc should return False."""
        assert is_valid_url("https://") is False
        assert is_valid_url("file:///path/to/file") is False

    def test_empty_string_returns_false(self):
        """Empty string should return False."""
        assert is_valid_url("") is False

    def test_none_like_values(self):
        """None-like values should return False."""
        assert is_valid_url(None) is False


class TestIsGitHubUrl:
    """Tests for is_github_url function."""

    def test_valid_github_repo_url(self):
        """Valid GitHub repo URLs should return True."""
        assert is_github_url("https://github.com/owner/repo") is True
        assert is_github_url("https://github.com/MicrosoftDocs/azure-docs") is True

    def test_github_url_with_path(self):
        """GitHub URLs with additional path should return True."""
        assert is_github_url("https://github.com/owner/repo/blob/main/file.md") is True

    def test_github_url_without_repo(self):
        """GitHub URLs without repo should return False."""
        assert is_github_url("https://github.com/owner") is False
        assert is_github_url("https://github.com/") is False

    def test_non_github_url_returns_false(self):
        """Non-GitHub URLs should return False."""
        assert is_github_url("https://gitlab.com/owner/repo") is False
        assert is_github_url("https://example.com/owner/repo") is False

    def test_http_github_url_returns_false(self):
        """HTTP (not HTTPS) GitHub URLs should return False."""
        assert is_github_url("http://github.com/owner/repo") is False


class TestValidateTaskData:
    """Tests for validate_task_data function."""

    def test_valid_task_data(self):
        """Valid task data should return (True, None)."""
        task_data = {
            'url': 'https://github.com/owner/repo',
            'scan_id': 123
        }
        is_valid, error = validate_task_data(task_data)
        assert is_valid is True
        assert error is None

    def test_valid_task_data_string_scan_id(self):
        """String scan_id that can be converted to int should be valid."""
        task_data = {
            'url': 'https://github.com/owner/repo',
            'scan_id': '123'
        }
        is_valid, error = validate_task_data(task_data)
        assert is_valid is True

    def test_missing_url(self):
        """Missing URL should return error."""
        task_data = {'scan_id': 123}
        is_valid, error = validate_task_data(task_data)
        assert is_valid is False
        assert "Missing required field: url" in error

    def test_missing_scan_id(self):
        """Missing scan_id should return error."""
        task_data = {'url': 'https://github.com/owner/repo'}
        is_valid, error = validate_task_data(task_data)
        assert is_valid is False
        assert "Missing required field: scan_id" in error

    def test_invalid_url(self):
        """Invalid URL should return error."""
        task_data = {
            'url': 'not-a-valid-url',
            'scan_id': 123
        }
        is_valid, error = validate_task_data(task_data)
        assert is_valid is False
        assert "Invalid URL" in error

    def test_non_github_url(self):
        """Non-GitHub URL should return error."""
        task_data = {
            'url': 'https://gitlab.com/owner/repo',
            'scan_id': 123
        }
        is_valid, error = validate_task_data(task_data)
        assert is_valid is False
        assert "Only GitHub URLs are supported" in error

    def test_invalid_scan_id(self):
        """Invalid scan_id should return error."""
        task_data = {
            'url': 'https://github.com/owner/repo',
            'scan_id': 'not-a-number'
        }
        is_valid, error = validate_task_data(task_data)
        assert is_valid is False
        assert "Invalid scan_id" in error


class TestSanitizeFilename:
    """Tests for sanitize_filename function."""

    def test_normal_filename_unchanged(self):
        """Normal filenames should remain unchanged."""
        assert sanitize_filename("document.txt") == "document.txt"
        assert sanitize_filename("my_file-name.md") == "my_file-name.md"

    def test_removes_invalid_characters(self):
        """Should replace invalid characters with underscores."""
        assert sanitize_filename('file<>name.txt') == 'file__name.txt'
        assert sanitize_filename('file:name.txt') == 'file_name.txt'
        assert sanitize_filename('file"name.txt') == 'file_name.txt'
        assert sanitize_filename('file/name.txt') == 'file_name.txt'
        assert sanitize_filename('file\\name.txt') == 'file_name.txt'
        assert sanitize_filename('file|name.txt') == 'file_name.txt'
        assert sanitize_filename('file?name.txt') == 'file_name.txt'
        assert sanitize_filename('file*name.txt') == 'file_name.txt'

    def test_strips_whitespace(self):
        """Should strip leading/trailing whitespace."""
        assert sanitize_filename("  file.txt  ") == "file.txt"

    def test_strips_dots(self):
        """Should strip leading/trailing dots."""
        assert sanitize_filename("..file.txt..") == "file.txt"
        assert sanitize_filename("...") == "unnamed"

    def test_empty_result_becomes_unnamed(self):
        """Empty result after sanitization should become 'unnamed'."""
        assert sanitize_filename("") == "unnamed"
        assert sanitize_filename("   ") == "unnamed"
        assert sanitize_filename("...") == "unnamed"
        assert sanitize_filename("***") == "unnamed"


class TestValidateScanMetrics:
    """Tests for validate_scan_metrics function."""

    def test_valid_metrics(self):
        """Valid metrics should return True."""
        metrics = {
            'biased_pages_count': 10,
            'flagged_snippets_count': 25
        }
        assert validate_scan_metrics(metrics) is True

    def test_valid_metrics_string_values(self):
        """String values that can be converted to int should be valid."""
        metrics = {
            'biased_pages_count': '10',
            'flagged_snippets_count': '25'
        }
        assert validate_scan_metrics(metrics) is True

    def test_missing_biased_pages_count(self):
        """Missing biased_pages_count should return False."""
        metrics = {'flagged_snippets_count': 25}
        assert validate_scan_metrics(metrics) is False

    def test_missing_flagged_snippets_count(self):
        """Missing flagged_snippets_count should return False."""
        metrics = {'biased_pages_count': 10}
        assert validate_scan_metrics(metrics) is False

    def test_invalid_biased_pages_count(self):
        """Invalid biased_pages_count should return False."""
        metrics = {
            'biased_pages_count': 'not-a-number',
            'flagged_snippets_count': 25
        }
        assert validate_scan_metrics(metrics) is False

    def test_invalid_flagged_snippets_count(self):
        """Invalid flagged_snippets_count should return False."""
        metrics = {
            'biased_pages_count': 10,
            'flagged_snippets_count': None
        }
        assert validate_scan_metrics(metrics) is False

    def test_empty_metrics(self):
        """Empty metrics dict should return False."""
        assert validate_scan_metrics({}) is False
