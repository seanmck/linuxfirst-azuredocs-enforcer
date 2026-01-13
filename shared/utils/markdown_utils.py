"""
Shared utilities for parsing markdown content.
Provides consistent title extraction logic across all services.
"""

import re
from typing import Optional


def extract_title_from_markdown(content: str) -> str:
    """
    Extract the page title from markdown content.

    Looks for title in the following order:
    1. YAML frontmatter 'title:' field
    2. First # heading (H1)
    3. First ## heading (H2) as fallback

    Args:
        content: Full markdown content of the page

    Returns:
        The extracted title string, or empty string if no title found
    """
    if not content:
        return ""

    # Try YAML frontmatter first (between --- markers)
    frontmatter_match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if frontmatter_match:
        frontmatter = frontmatter_match.group(1)
        title_match = re.search(r'^title:\s*["\']?(.+?)["\']?\s*$', frontmatter, re.MULTILINE)
        if title_match:
            return title_match.group(1).strip()

    # Try first # heading
    h1_match = re.search(r'^#\s+(.+?)(?:\s*#*)?\s*$', content, re.MULTILINE)
    if h1_match:
        return h1_match.group(1).strip()

    # Try first ## heading as fallback
    h2_match = re.search(r'^##\s+(.+?)(?:\s*#*)?\s*$', content, re.MULTILINE)
    if h2_match:
        return h2_match.group(1).strip()

    return ""


def extract_frontmatter_title(content: str) -> Optional[str]:
    """
    Extract just the YAML frontmatter title from markdown content.

    Args:
        content: Full markdown content of the page

    Returns:
        The title from frontmatter if found, None otherwise
    """
    if not content:
        return None

    # Try YAML frontmatter (between --- markers)
    frontmatter_match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if frontmatter_match:
        frontmatter = frontmatter_match.group(1)
        title_match = re.search(r'^title:\s*["\']?(.+?)["\']?\s*$', frontmatter, re.MULTILINE)
        if title_match:
            return title_match.group(1).strip()

    return None


def extract_h1_heading(content: str) -> Optional[str]:
    """
    Extract the first H1 heading from markdown content.

    Args:
        content: Full markdown content of the page

    Returns:
        The H1 heading text if found, None otherwise
    """
    if not content:
        return None

    # Try first # heading
    h1_match = re.search(r'^#\s+(.+?)(?:\s*#*)?\s*$', content, re.MULTILINE)
    if h1_match:
        return h1_match.group(1).strip()

    return None
