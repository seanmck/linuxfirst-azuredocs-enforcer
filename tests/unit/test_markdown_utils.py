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
        assert extract_title_from_frontmatter("") is None
        assert extract_title_from_frontmatter(None) is None

    def test_no_frontmatter(self):
        """Should return None when no frontmatter present"""
        content = "# Just a heading"
        assert extract_title_from_frontmatter(content) is None

    def test_frontmatter_with_title(self):
        """Should extract title from valid frontmatter"""
        content = '''title: "Test Title"
author: test'''
        assert extract_title_from_frontmatter(content) == "Test Title"

    def test_frontmatter_without_title(self):
        """Should return None when frontmatter has no title"""
        content = '''author: test
date: 2024-01-01'''
        assert extract_title_from_frontmatter(content) is None


