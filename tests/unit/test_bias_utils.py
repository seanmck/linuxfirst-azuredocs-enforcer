"""
Unit tests for shared/utils/bias_utils.py
"""
import pytest
from unittest.mock import MagicMock
from shared.utils.bias_utils import (
    get_parsed_mcp_holistic,
    is_page_biased,
    get_page_priority,
    count_biased_pages,
    get_bias_percentage,
)


class TestGetParsedMcpHolistic:
    """Tests for get_parsed_mcp_holistic function."""

    def test_none_mcp_holistic_returns_none(self):
        """Page with None mcp_holistic should return None."""
        page = MagicMock()
        page.mcp_holistic = None
        del page._parsed_mcp_holistic  # Ensure no cache
        assert get_parsed_mcp_holistic(page) is None

    def test_dict_mcp_holistic_returned_directly(self):
        """Page with dict mcp_holistic should return it directly."""
        page = MagicMock()
        page.mcp_holistic = {"bias_types": ["powershell_only"]}
        del page._parsed_mcp_holistic
        result = get_parsed_mcp_holistic(page)
        assert result == {"bias_types": ["powershell_only"]}

    def test_string_mcp_holistic_parsed(self):
        """Page with JSON string mcp_holistic should be parsed."""
        page = MagicMock()
        page.mcp_holistic = '{"bias_types": ["windows_paths"]}'
        del page._parsed_mcp_holistic
        result = get_parsed_mcp_holistic(page)
        assert result == {"bias_types": ["windows_paths"]}

    def test_invalid_json_string_returns_none(self):
        """Page with invalid JSON string should return None."""
        page = MagicMock()
        page.mcp_holistic = "not valid json"
        del page._parsed_mcp_holistic
        result = get_parsed_mcp_holistic(page)
        assert result is None

    def test_non_dict_value_returns_none(self):
        """Page with non-dict mcp_holistic should return None."""
        page = MagicMock()
        page.mcp_holistic = ["not", "a", "dict"]
        del page._parsed_mcp_holistic
        result = get_parsed_mcp_holistic(page)
        assert result is None

    def test_caching_behavior(self):
        """Should cache parsed result on page object."""
        page = MagicMock()
        page.mcp_holistic = {"bias_types": ["test"]}
        del page._parsed_mcp_holistic

        # First call should parse and cache
        result1 = get_parsed_mcp_holistic(page)
        assert result1 == {"bias_types": ["test"]}
        assert hasattr(page, '_parsed_mcp_holistic')

        # Second call should use cache
        page._parsed_mcp_holistic = {"cached": True}
        result2 = get_parsed_mcp_holistic(page)
        assert result2 == {"cached": True}


class TestIsPageBiased:
    """Tests for is_page_biased function."""

    def test_no_mcp_data_returns_false(self):
        """Page with no MCP data should return False."""
        page = MagicMock()
        page.mcp_holistic = None
        del page._parsed_mcp_holistic
        assert is_page_biased(page) is False

    def test_empty_bias_types_returns_false(self):
        """Page with empty bias_types (no severity) should return False."""
        page = MagicMock()
        page.mcp_holistic = {"bias_types": []}
        del page._parsed_mcp_holistic
        assert is_page_biased(page) is False

    def test_with_bias_types_returns_true(self):
        """Page with bias_types (no severity) should return True via fallback."""
        page = MagicMock()
        page.mcp_holistic = {"bias_types": ["powershell_only"]}
        del page._parsed_mcp_holistic
        assert is_page_biased(page) is True

    def test_multiple_bias_types_returns_true(self):
        """Page with multiple bias_types should return True."""
        page = MagicMock()
        page.mcp_holistic = {"bias_types": ["powershell_only", "windows_paths", "missing_linux"]}
        del page._parsed_mcp_holistic
        assert is_page_biased(page) is True

    def test_string_bias_type_converted_to_list(self):
        """Page with string bias_types should be handled."""
        page = MagicMock()
        page.mcp_holistic = {"bias_types": "powershell_only"}
        del page._parsed_mcp_holistic
        assert is_page_biased(page) is True

    # Severity-based tests (primary indicator)
    def test_severity_high_returns_true(self):
        """Page with severity 'high' should return True."""
        page = MagicMock()
        page.mcp_holistic = {"severity": "high", "bias_types": []}
        del page._parsed_mcp_holistic
        assert is_page_biased(page) is True

    def test_severity_medium_returns_true(self):
        """Page with severity 'medium' should return True."""
        page = MagicMock()
        page.mcp_holistic = {"severity": "medium", "bias_types": []}
        del page._parsed_mcp_holistic
        assert is_page_biased(page) is True

    def test_severity_low_returns_true(self):
        """Page with severity 'low' should return True."""
        page = MagicMock()
        page.mcp_holistic = {"severity": "low", "bias_types": []}
        del page._parsed_mcp_holistic
        assert is_page_biased(page) is True

    def test_severity_none_returns_false(self):
        """Page with severity 'none' should return False."""
        page = MagicMock()
        page.mcp_holistic = {"severity": "none", "bias_types": []}
        del page._parsed_mcp_holistic
        assert is_page_biased(page) is False

    def test_severity_none_overrides_bias_types(self):
        """Severity 'none' should take precedence over non-empty bias_types."""
        page = MagicMock()
        page.mcp_holistic = {"severity": "none", "bias_types": ["powershell_only"]}
        del page._parsed_mcp_holistic
        assert is_page_biased(page) is False

    def test_severity_high_with_bias_types(self):
        """Page with severity 'high' and bias_types should return True."""
        page = MagicMock()
        page.mcp_holistic = {"severity": "high", "bias_types": ["powershell_only"]}
        del page._parsed_mcp_holistic
        assert is_page_biased(page) is True

    def test_severity_case_insensitive(self):
        """Severity comparison should be case-insensitive."""
        page = MagicMock()
        page.mcp_holistic = {"severity": "HIGH", "bias_types": []}
        del page._parsed_mcp_holistic
        assert is_page_biased(page) is True

        page.mcp_holistic = {"severity": "None", "bias_types": []}
        del page._parsed_mcp_holistic
        assert is_page_biased(page) is False

    def test_severity_with_whitespace(self):
        """Severity with whitespace should be handled."""
        page = MagicMock()
        page.mcp_holistic = {"severity": "  high  ", "bias_types": []}
        del page._parsed_mcp_holistic
        assert is_page_biased(page) is True

    def test_empty_string_severity_falls_back_to_bias_types(self):
        """Empty string severity should fall back to bias_types."""
        page = MagicMock()
        page.mcp_holistic = {"severity": "", "bias_types": ["powershell_only"]}
        del page._parsed_mcp_holistic
        assert is_page_biased(page) is True

        page.mcp_holistic = {"severity": "", "bias_types": []}
        del page._parsed_mcp_holistic
        assert is_page_biased(page) is False


class TestGetPagePriority:
    """Tests for get_page_priority function."""

    def test_no_mcp_data_returns_low(self):
        """Page with no MCP data should return Low priority."""
        page = MagicMock()
        page.mcp_holistic = None
        del page._parsed_mcp_holistic
        label, score = get_page_priority(page)
        assert label == "Low"
        assert score == 1

    def test_empty_bias_types_returns_low(self):
        """Page with empty bias_types should return Low priority."""
        page = MagicMock()
        page.mcp_holistic = {"bias_types": []}
        del page._parsed_mcp_holistic
        label, score = get_page_priority(page)
        assert label == "Low"
        assert score == 1

    def test_one_bias_type_returns_low(self):
        """Page with 1 bias type should return Low priority."""
        page = MagicMock()
        page.mcp_holistic = {"bias_types": ["powershell_only"]}
        del page._parsed_mcp_holistic
        label, score = get_page_priority(page)
        assert label == "Low"
        assert score == 1

    def test_two_bias_types_returns_medium(self):
        """Page with 2 bias types should return Medium priority."""
        page = MagicMock()
        page.mcp_holistic = {"bias_types": ["powershell_only", "windows_paths"]}
        del page._parsed_mcp_holistic
        label, score = get_page_priority(page)
        assert label == "Medium"
        assert score == 2

    def test_three_bias_types_returns_high(self):
        """Page with 3+ bias types should return High priority."""
        page = MagicMock()
        page.mcp_holistic = {"bias_types": ["powershell_only", "windows_paths", "missing_linux"]}
        del page._parsed_mcp_holistic
        label, score = get_page_priority(page)
        assert label == "High"
        assert score == 3

    def test_many_bias_types_returns_high(self):
        """Page with many bias types should return High priority."""
        page = MagicMock()
        page.mcp_holistic = {"bias_types": ["a", "b", "c", "d", "e"]}
        del page._parsed_mcp_holistic
        label, score = get_page_priority(page)
        assert label == "High"
        assert score == 3


class TestCountBiasedPages:
    """Tests for count_biased_pages function."""

    def test_empty_list_returns_zero(self):
        """Empty list should return 0."""
        assert count_biased_pages([]) == 0

    def test_no_biased_pages_returns_zero(self):
        """List with no biased pages should return 0."""
        pages = []
        for _ in range(3):
            page = MagicMock()
            page.mcp_holistic = {"bias_types": []}
            del page._parsed_mcp_holistic
            pages.append(page)
        assert count_biased_pages(pages) == 0

    def test_all_biased_pages(self):
        """List with all biased pages should return count."""
        pages = []
        for _ in range(5):
            page = MagicMock()
            page.mcp_holistic = {"bias_types": ["powershell_only"]}
            del page._parsed_mcp_holistic
            pages.append(page)
        assert count_biased_pages(pages) == 5

    def test_mixed_pages(self):
        """List with mixed pages should return correct count."""
        pages = []
        # 3 biased
        for _ in range(3):
            page = MagicMock()
            page.mcp_holistic = {"bias_types": ["test"]}
            del page._parsed_mcp_holistic
            pages.append(page)
        # 2 not biased
        for _ in range(2):
            page = MagicMock()
            page.mcp_holistic = {"bias_types": []}
            del page._parsed_mcp_holistic
            pages.append(page)
        assert count_biased_pages(pages) == 3


class TestGetBiasPercentage:
    """Tests for get_bias_percentage function."""

    def test_empty_list_returns_zero(self):
        """Empty list should return 0.0."""
        assert get_bias_percentage([]) == 0.0

    def test_no_biased_pages_returns_zero(self):
        """No biased pages should return 0.0."""
        pages = []
        for _ in range(4):
            page = MagicMock()
            page.mcp_holistic = {"bias_types": []}
            del page._parsed_mcp_holistic
            pages.append(page)
        assert get_bias_percentage(pages) == 0.0

    def test_all_biased_pages_returns_100(self):
        """All biased pages should return 100.0."""
        pages = []
        for _ in range(4):
            page = MagicMock()
            page.mcp_holistic = {"bias_types": ["test"]}
            del page._parsed_mcp_holistic
            pages.append(page)
        assert get_bias_percentage(pages) == 100.0

    def test_half_biased_returns_50(self):
        """Half biased pages should return 50.0."""
        pages = []
        # 2 biased
        for _ in range(2):
            page = MagicMock()
            page.mcp_holistic = {"bias_types": ["test"]}
            del page._parsed_mcp_holistic
            pages.append(page)
        # 2 not biased
        for _ in range(2):
            page = MagicMock()
            page.mcp_holistic = {"bias_types": []}
            del page._parsed_mcp_holistic
            pages.append(page)
        assert get_bias_percentage(pages) == 50.0

    def test_percentage_calculation(self):
        """Should calculate correct percentage."""
        pages = []
        # 1 biased out of 4 = 25%
        page = MagicMock()
        page.mcp_holistic = {"bias_types": ["test"]}
        del page._parsed_mcp_holistic
        pages.append(page)
        for _ in range(3):
            page = MagicMock()
            page.mcp_holistic = {"bias_types": []}
            del page._parsed_mcp_holistic
            pages.append(page)
        assert get_bias_percentage(pages) == 25.0
