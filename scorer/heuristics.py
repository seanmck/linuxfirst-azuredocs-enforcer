# heuristics.py
# Optional: Lightweight regex-based pre-filtering of extracted snippets.

import re

def is_windows_biased(snippet):
    # If the snippet is under an Azure PowerShell tab, do not flag as biased
    if snippet.get('under_az_powershell_tab'):
        return False
    # If the snippet is under a Windows header, do not flag as biased
    if snippet.get('windows_header'):
        return False
    context = snippet.get('context', '').lower()
    url = snippet.get('url', '').lower() if 'url' in snippet else ''
    if (
        'windows' in context or
        'powershell' in context or
        '/windows/' in url or
        '/powershell/' in url or
        '/cmd/' in url or
        '/cli-windows/' in url or
        '/windows-' in url
    ):
        return False
    # Heuristic: look for Windows prompt, PowerShell, or Windows-only tools
    windows_patterns = [
        r'^\s*C:\\',  # Windows path
        r'\\',        # Backslash in path
        r'cmd\.exe',
        r'powershell',
        r'PS [A-Z]:',
        r'\\Users\\',
        r'net use',
        r'icacls',
        r'\bregedit\b',
        r'\bchoco(\s|$)',
        r'\bwinget(\s|$)',
        r'\bSet-ExecutionPolicy\b',
        r'\bGet-ChildItem\b',
        r'\bNew-Item\b',
        r'\bRemove-Item\b',
        r'\bdir\b',
        r'\bcopy\b',
        r'\bdel\b',
        r'\bcls\b',
        r'\btype\b',
        r'\bsc \b',
        r'\bnet start\b',
        r'\bnet stop\b',
        r'\bmsiexec\b',
        r'\btasklist\b',
        r'\btaskkill\b',
        r'\bshutdown\b',
        r'\bexplorer.exe\b',
    ]
    for pat in windows_patterns:
        if re.search(pat, snippet['code'], re.IGNORECASE|re.MULTILINE):
            return True
    return False
    
# Example usage:
# for snip in snippets:
#     if is_windows_biased(snip):
#         print('Windows bias:', snip['context'])
