"""
Unit tests for markdown_utils module.
Tests the shared markdown parsing utilities used across services.
"""

import pytest
from shared.utils.markdown_utils import (
    extract_title_from_markdown,
    extract_title_from_frontmatter,
)
class TestExtractTitleFromMarkdown:
    """Test cases for extract_title_from_markdown function"""

    def test_empty_content(self):
        """Should return empty string for empty content"""
        assert extract_title_from_markdown("") == ""
        assert extract_title_from_markdown(None) == ""

    def test_frontmatter_title_with_quotes(self):
        """Should extract title from YAML frontmatter with quotes"""
        content = '''---
title: "Install on Windows Server"
author: seanmck
---

# Some heading'''
        assert extract_title_from_markdown(content) == "Install on Windows Server"

    def test_frontmatter_title_without_quotes(self):
        """Should extract title from YAML frontmatter without quotes"""
        content = '''---
title: Install on Windows Server
author: seanmck
---

# Some heading'''
        assert extract_title_from_markdown(content) == "Install on Windows Server"

    def test_h1_heading(self):
        """Should extract H1 heading when no frontmatter"""
        content = '''# Install Azure CLI on Linux

This guide shows...'''
        assert extract_title_from_markdown(content) == "Install Azure CLI on Linux"

    def test_h1_heading_with_trailing_hash(self):
        """Should extract H1 heading with trailing hash marks"""
        content = '''# Install Azure CLI #

This guide shows...'''
        assert extract_title_from_markdown(content) == "Install Azure CLI"

    def test_h2_heading_fallback(self):
        """Should fall back to H2 heading when no frontmatter or H1"""
        content = '''Some intro text

## Getting Started

This guide shows...'''
        assert extract_title_from_markdown(content) == "Getting Started"

    def test_frontmatter_priority_over_h1(self):
        """Should prefer frontmatter title over H1"""
        content = '''---
title: From Frontmatter
---

# From H1

Content'''
        assert extract_title_from_markdown(content) == "From Frontmatter"

    def test_h1_priority_over_h2(self):
        """Should prefer H1 over H2"""
        content = '''# Main Title

## Subtitle

Content'''
        assert extract_title_from_markdown(content) == "Main Title"


class TestExtractFrontmatterTitle:
    """Test cases for extract_frontmatter_title function"""

    def test_empty_content(self):
        """Should return None for empty content"""
        assert extract_frontmatter_title("") is None
        assert extract_frontmatter_title(None) is None

    def test_no_frontmatter(self):
        """Should return None when no frontmatter present"""
        content = "# Just a heading"
        assert extract_frontmatter_title(content) is None

    def test_frontmatter_with_title(self):
        """Should extract title from valid frontmatter"""
        content = '''---
title: "Test Title"
author: test
---'''
        assert extract_frontmatter_title(content) == "Test Title"

    def test_frontmatter_without_title(self):
        """Should return None when frontmatter has no title"""
        content = '''---
author: test
date: 2024-01-01
---'''
        assert extract_frontmatter_title(content) is None


class TestExtractH1Heading:
    """Test cases for extract_h1_heading function"""

    def test_empty_content(self):
        """Should return None for empty content"""
        assert extract_h1_heading("") is None
        assert extract_h1_heading(None) is None

    def test_no_h1(self):
        """Should return None when no H1 present"""
        content = "## Just H2\n\nSome content"
        assert extract_h1_heading(content) is None

    def test_simple_h1(self):
        """Should extract simple H1"""
        content = "# Main Title\n\nContent"
        assert extract_h1_heading(content) == "Main Title"

    def test_h1_with_trailing_hash(self):
        """Should extract H1 with trailing hash"""
        content = "# Main Title ###\n\nContent"
        assert extract_h1_heading(content) == "Main Title"

    def test_first_h1_only(self):
        """Should extract only the first H1"""
        content = '''# First Title

Some content

# Second Title

More content'''
        assert extract_h1_heading(content) == "First Title"
