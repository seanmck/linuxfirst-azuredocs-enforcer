# parser.py
# Uses BeautifulSoup to extract <pre> blocks and their context from HTML.

from bs4 import BeautifulSoup
import re

def extract_code_snippets(html):
    soup = BeautifulSoup(html, 'html.parser')
    snippets = []
    for pre in soup.find_all('pre'):
        # Get context: parent section, heading, or nearby text
        context = ''
        parent = pre.find_parent(['section', 'article', 'div'])
        if parent:
            heading = parent.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
            if heading:
                context = heading.get_text(strip=True)
        if not context:
            # Fallback: previous sibling heading
            prev = pre.find_previous(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
            if prev:
                context = prev.get_text(strip=True)
        code = pre.get_text('\n', strip=True)
        snippets.append({'code': code, 'context': context})
    return snippets

# Example usage:
# html = ...
# for snippet in extract_code_snippets(html):
#     print(snippet['context'], snippet['code'][:80])
