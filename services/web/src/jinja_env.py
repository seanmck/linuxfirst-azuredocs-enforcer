import os
import re
from fastapi.templating import Jinja2Templates
from markdown import markdown as md_lib

def markdown_filter(text):
    return md_lib(text or "")

def truncate_url_filter(url, max_length=60):
    """Truncate URL for display, keeping the end (most specific part)."""
    if not url or len(url) <= max_length:
        return url
    # Keep the last part of the URL (the filename)
    parts = url.split('/')
    filename = parts[-1] if parts else url
    if len(filename) >= max_length - 3:
        return '...' + filename[-(max_length-3):]
    remaining = max_length - len(filename) - 4  # 4 for ".../"
    prefix = '/'.join(parts[:-1])
    if len(prefix) > remaining:
        prefix = '...' + prefix[-(remaining-3):]
    return prefix + '/' + filename

def url_to_title_filter(url):
    """Extract a human-readable title from a GitHub docs URL.

    Example:
    https://github.com/MicrosoftDocs/azure-docs/blob/main/articles/active-directory-b2c/access-tokens.md
    → "Active Directory B2C: Access Tokens"
    """
    if not url:
        return "Untitled Page"

    try:
        # Extract the path after /articles/ or similar patterns
        path_match = re.search(r'/articles/([^/]+)/([^/]+?)(?:\.md)?$', url)
        if path_match:
            folder = path_match.group(1)
            filename = path_match.group(2)

            # Convert kebab-case to Title Case
            def to_title(s):
                # Handle common acronyms
                acronyms = {'b2c', 'b2b', 'api', 'sdk', 'cli', 'sql', 'vm', 'vms', 'aks', 'acr', 'dns', 'ssl', 'tls', 'ssh', 'rbac', 'aad', 'arm'}
                words = s.replace('-', ' ').replace('_', ' ').split()
                titled = []
                for word in words:
                    if word.lower() in acronyms:
                        titled.append(word.upper())
                    else:
                        titled.append(word.capitalize())
                return ' '.join(titled)

            folder_title = to_title(folder)
            file_title = to_title(filename)

            # Avoid redundancy if folder and file have similar names
            if file_title.lower().startswith(folder_title.lower().split()[0].lower()):
                return file_title

            return f"{folder_title}: {file_title}"

        # Fallback: just get the last path segment
        parts = url.rstrip('/').split('/')
        filename = parts[-1] if parts else url
        filename = re.sub(r'\.md$', '', filename)
        return filename.replace('-', ' ').replace('_', ' ').title()

    except Exception:
        return url

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.filters['markdown'] = markdown_filter
templates.env.filters['truncate_url'] = truncate_url_filter
templates.env.filters['url_to_title'] = url_to_title_filter
