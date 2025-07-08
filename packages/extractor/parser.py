# parser.py
# Uses BeautifulSoup to extract <pre> blocks and their context from HTML.

from bs4 import BeautifulSoup
import re


def extract_code_snippets(html):
    soup = BeautifulSoup(html, 'html.parser')
    snippets = []
    for pre in soup.find_all('pre'):
        context = ''
        parent = pre.find_parent(['section', 'article', 'div'])
        if parent:
            heading = parent.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
            if heading:
                context = heading.get_text(strip=True)
        if not context:
            prev = pre.find_previous(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
            if prev:
                context = prev.get_text(strip=True)
        code = pre.get_text('\n', strip=True)
        # Get a broader context excerpt (up to 25 lines around the <pre> block)
        lines = pre.parent.get_text('\n', strip=True).split('\n') if pre.parent else []
        pre_text = pre.get_text('\n', strip=True)
        if lines and pre_text in lines:
            idx = lines.index(pre_text)
            start = max(0, idx - 12)
            end = min(len(lines), idx + 13)
            excerpt = '\n'.join(lines[start:end])
        else:
            excerpt = pre_text
        # Truncate excerpt if too long
        if excerpt.count('\n') > 25:
            excerpt = '\n'.join(excerpt.split('\n')[:25]) + '\n...'
        # Check if under Azure PowerShell tab
        under_az_powershell_tab = False
        tab_parent = pre.find_parent(attrs={"data-tab": True})
        if tab_parent and tab_parent.get("data-tab", "").lower() == "azure-powershell":
            under_az_powershell_tab = True
        # Check if context/header contains 'windows'
        windows_header = False
        if context and 'windows' in context.lower():
            windows_header = True
        snippets.append({
            'code': code,
            'context': context,
            'excerpt': excerpt,
            'under_az_powershell_tab': under_az_powershell_tab,
            'windows_header': windows_header
        })
    return snippets

# Example usage:
# html = ...
# for snippet in extract_code_snippets(html):
#     print(snippet['context'], snippet['code'][:80])
