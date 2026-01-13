"""
Markdown utility functions for parsing and extracting information from markdown content.
"""
import re
from typing import Optional


def extract_yaml_frontmatter(content: str) -> Optional[str]:
    """
    Extract YAML frontmatter from markdown content.
    
    Args:
        content: Full markdown content
        
    Returns:
        The YAML frontmatter content (without the --- delimiters), or None if not found
    """
    if not content:
        return None
    
    frontmatter_match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if frontmatter_match:
        return frontmatter_match.group(1)
    
    return None


def extract_title_from_frontmatter(frontmatter: str) -> Optional[str]:
    """
    Extract the title field from YAML frontmatter.
    
    Args:
        frontmatter: YAML frontmatter content (without the --- delimiters)
        
    Returns:
        The title value, or None if not found
    """
    if not frontmatter:
        return None
    
    title_match = re.search(r'^title:\s*["\']?(.+?)["\']?\s*$', frontmatter, re.MULTILINE)
    if title_match:
        return title_match.group(1).strip()
    
    return None


def extract_title_from_markdown(content: str) -> str:
    """
    Extract the page title from markdown content.
    
    Looks for (in order of priority):
    1. YAML frontmatter 'title:' field
    2. First # heading
    3. First ## heading as fallback
    
    Args:
        content: Full markdown content
        
    Returns:
        The extracted title, or empty string if no title found
    """
    if not content:
        return ""
    
    # Try YAML frontmatter first
    frontmatter = extract_yaml_frontmatter(content)
    if frontmatter:
        title = extract_title_from_frontmatter(frontmatter)
        if title:
            return title
    
    # Try first # heading
    h1_match = re.search(r'^#\s+(.+?)(?:\s*#*)?\s*$', content, re.MULTILINE)
    if h1_match:
        return h1_match.group(1).strip()
    
    # Try first ## heading as fallback
    h2_match = re.search(r'^##\s+(.+?)(?:\s*#*)?\s*$', content, re.MULTILINE)
    if h2_match:
        return h2_match.group(1).strip()
    
    return ""
