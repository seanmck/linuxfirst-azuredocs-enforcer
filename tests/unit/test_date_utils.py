"""
Unit tests for shared/utils/date_utils.py
"""
import pytest
from datetime import datetime
from shared.utils.date_utils import (
    get_current_date_mmddyyyy,
    update_ms_date_in_content,
    extract_ms_date_from_content,
)


class TestGetCurrentDateMmddyyyy:
    """Tests for get_current_date_mmddyyyy function."""

    def test_returns_correct_format(self):
        """Should return date in MM/DD/YYYY format."""
        result = get_current_date_mmddyyyy()
        # Check format: MM/DD/YYYY
        import re
        assert re.match(r'\d{2}/\d{2}/\d{4}', result), f"Expected MM/DD/YYYY format, got {result}"

    def test_returns_current_date(self):
        """Should return today's date."""
        result = get_current_date_mmddyyyy()
        expected = datetime.now().strftime("%m/%d/%Y")
        assert result == expected


class TestUpdateMsDateInContent:
    """Tests for update_ms_date_in_content function."""

    def test_updates_existing_date(self):
        """Should update existing ms.date field."""
        content = """---
title: Test
ms.date: 01/01/2023
---

Content here."""
        result = update_ms_date_in_content(content, "12/25/2024")
        assert "ms.date: 12/25/2024" in result
        assert "01/01/2023" not in result

    def test_updates_date_with_quotes(self):
        """Should handle ms.date with quotes."""
        content = """---
title: Test
ms.date: "01/01/2023"
---

Content."""
        result = update_ms_date_in_content(content, "12/25/2024")
        assert 'ms.date: "12/25/2024"' in result

    def test_updates_date_with_single_quotes(self):
        """Should handle ms.date with single quotes."""
        content = """---
title: Test
ms.date: '01/01/2023'
---

Content."""
        result = update_ms_date_in_content(content, "12/25/2024")
        assert "ms.date: '12/25/2024'" in result

    def test_handles_different_spacing(self):
        """Should handle various spacing patterns."""
        content = """---
ms.date:01/01/2023
---"""
        result = update_ms_date_in_content(content, "12/25/2024")
        assert "12/25/2024" in result

    def test_adds_date_when_missing(self):
        """Should add ms.date if missing from frontmatter."""
        content = """---
title: Test Document
ms.service: storage
---

Content here."""
        result = update_ms_date_in_content(content, "12/25/2024")
        assert "ms.date: 12/25/2024" in result

    def test_no_change_without_frontmatter(self):
        """Should not modify content without YAML frontmatter."""
        content = "No frontmatter here, just content."
        result = update_ms_date_in_content(content, "12/25/2024")
        # Content unchanged if no frontmatter and no existing ms.date
        assert "ms.date" not in result

    @patch('shared.utils.date_utils.get_current_date_mmddyyyy')
    def test_uses_current_date_by_default(self, mock_get_date):
        """Should use current date if none provided."""
        mock_get_date.return_value = "06/15/2024"
        content = """---
ms.date: 01/01/2023
---"""
        result = update_ms_date_in_content(content)
        assert "ms.date: 06/15/2024" in result


class TestExtractMsDateFromContent:
    """Tests for extract_ms_date_from_content function."""

    def test_extracts_basic_date(self):
        """Should extract basic ms.date value."""
        content = """---
title: Test
ms.date: 01/15/2024
---

Content."""
        result = extract_ms_date_from_content(content)
        assert result == "01/15/2024"

    def test_extracts_date_with_double_quotes(self):
        """Should extract date with double quotes."""
        content = """---
ms.date: "03/20/2024"
---"""
        result = extract_ms_date_from_content(content)
        assert result == "03/20/2024"

    def test_extracts_date_with_single_quotes(self):
        """Should extract date with single quotes."""
        content = """---
ms.date: '03/20/2024'
---"""
        result = extract_ms_date_from_content(content)
        assert result == "03/20/2024"

    def test_handles_various_spacing(self):
        """Should handle various spacing patterns."""
        content = """---
ms.date:01/15/2024
---"""
        result = extract_ms_date_from_content(content)
        assert result == "01/15/2024"

    def test_returns_none_when_missing(self):
        """Should return None when ms.date is missing."""
        content = """---
title: Test
ms.service: storage
---

Content."""
        result = extract_ms_date_from_content(content)
        assert result is None

    def test_returns_none_for_no_frontmatter(self):
        """Should return None when no frontmatter exists."""
        content = "Just plain content without any frontmatter."
        result = extract_ms_date_from_content(content)
        assert result is None

    def test_handles_single_digit_dates(self):
        """Should handle dates with single-digit month/day."""
        content = """---
ms.date: 1/5/2024
---"""
        result = extract_ms_date_from_content(content)
        assert result == "1/5/2024"
