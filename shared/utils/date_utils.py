"""
Date utility functions for the Linux-first Azure Docs Enforcer
"""
import re
from datetime import datetime
from typing import Optional


def get_current_date_mmddyyyy() -> str:
    """
    Get the current date in MM/DD/YYYY format for Azure documentation metadata.
    
    Returns:
        str: Current date formatted as MM/DD/YYYY
    """
    return datetime.now().strftime("%m/%d/%Y")


def update_ms_date_in_content(content: str, new_date: Optional[str] = None) -> str:
    """
    Update the ms.date field in YAML frontmatter to the current date.
    
    Args:
        content (str): Document content with YAML frontmatter
        new_date (str, optional): Date to use. If None, uses current date.
    
    Returns:
        str: Content with updated ms.date field
    """
    if new_date is None:
        new_date = get_current_date_mmddyyyy()
    
    # Pattern to match ms.date in YAML frontmatter
    # Handles various spacing and quote patterns:
    # ms.date: 01/01/2024
    # ms.date: "01/01/2024" 
    # ms.date:'01/01/2024'
    pattern = r'(ms\.date\s*:\s*)(["\']?)(\d{1,2}/\d{1,2}/\d{4})(["\']?)'
    
    def replace_date(match):
        prefix = match.group(1)  # "ms.date: "
        quote_open = match.group(2)  # Opening quote if present
        quote_close = match.group(4)  # Closing quote if present
        return f"{prefix}{quote_open}{new_date}{quote_close}"
    
    updated_content = re.sub(pattern, replace_date, content)
    
    # If no ms.date field was found, and we have YAML frontmatter, add it
    if updated_content == content and content.strip().startswith('---'):
        # Find the end of the frontmatter
        frontmatter_end = content.find('---', 3)
        if frontmatter_end != -1:
            # Insert ms.date before the closing ---
            insertion_point = frontmatter_end
            # Add ms.date line with proper formatting
            ms_date_line = f"ms.date: {new_date}\n"
            updated_content = content[:insertion_point] + ms_date_line + content[insertion_point:]
    
    return updated_content


def extract_ms_date_from_content(content: str) -> Optional[str]:
    """
    Extract the current ms.date value from YAML frontmatter.
    
    Args:
        content (str): Document content with YAML frontmatter
        
    Returns:
        Optional[str]: The ms.date value if found, None otherwise
    """
    pattern = r'ms\.date\s*:\s*(["\']?)(\d{1,2}/\d{1,2}/\d{4})(["\']?)'
    match = re.search(pattern, content)
    if match:
        return match.group(2)
    return None