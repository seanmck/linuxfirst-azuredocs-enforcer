# heuristics.py
# Lightweight regex-based pre-filtering for Windows bias detection.
# Used for both snippet-level and page-level heuristic scanning.

import re


# Patterns to detect Windows-specific content in full page prose/code
PROSE_WINDOWS_PATTERNS = [
    r'\bPowerShell\b',
    r'\bFiddler\b',
    r'\.exe\b',
    r'\badministrator\b',
    r'\.NET Framework\b',
    r'\bWindows Server\b',
    r'\bIIS\b',
    r'\bwin2019',   # Matches win2019, win2019datacenter, etc.
    r'\bwin2022',   # Matches win2022, win2022datacenter, etc.
    r'\bwin2016',   # Matches win2016, win2016datacenter, etc.
    r'Windows-only',
    r'Windows VM',
    r'\bwinget\b',
    r'\bchoco\b',
    r'chocolatey',
    r'msiexec',
    r'regedit',
    r'Windows Registry',
]


# Patterns for detecting intentionally Windows-focused page titles
# Used to skip scoring for pages that are clearly about Windows-specific topics
WINDOWS_FOCUSED_TITLE_PATTERNS = [
    r'\bWindows\b',                    # General Windows reference
    r'\bPowerShell\b',                 # PowerShell-focused content
    r'\bWindows Server\b',             # Windows Server documentation
    r'\bwin(?:20)?(?:16|19|22)\b',     # win2019, win2022, win2016, win16, etc.
    r'\bIIS\b',                        # Internet Information Services
    r'\.NET Framework\b',              # .NET Framework (not .NET Core/5+)
    r'\bWCF\b',                        # Windows Communication Foundation
    r'\bWPF\b',                        # Windows Presentation Foundation
    r'\bWinForms?\b',                  # Windows Forms
    r'\bActive Directory\b',           # Active Directory
    r'\bAD DS\b',                      # AD Domain Services
    r'\bHyper-V\b',                    # Hyper-V virtualization
    r'\bwinget\b',                     # Windows package manager
    r'\bChocolatey\b',                 # Chocolatey package manager
]


def is_windows_intentional_title(title: str) -> bool:
    """
    Check if a page title indicates intentionally Windows-focused documentation.

    Used to skip bias detection for pages that are legitimately about
    Windows-specific topics (e.g., "Configure Windows Server on Azure").

    Args:
        title: Page title from frontmatter or H1 heading

    Returns:
        True if the title indicates Windows-intentional content
    """
    if not title:
        return False

    for pattern in WINDOWS_FOCUSED_TITLE_PATTERNS:
        if re.search(pattern, title, re.IGNORECASE):
            return True
    return False


def page_has_windows_signals(page_content: str) -> bool:
    """
    Check if a page has Windows-specific content that needs LLM review.

    Used as a pre-filter to skip LLM scoring for pages with no Windows signals,
    reducing costs while ensuring Windows-biased pages get full analysis.

    Args:
        page_content: Full markdown/text content of the page

    Returns:
        True if Windows signals detected, False otherwise
    """
    if not page_content:
        return False

    for pattern in PROSE_WINDOWS_PATTERNS:
        if re.search(pattern, page_content, re.IGNORECASE):
            return True
    return False

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
