"""
Unit tests for packages/scorer/heuristics.py
"""
from packages.scorer.heuristics import page_has_windows_signals, is_windows_biased, is_windows_intentional_title


class TestPageHasWindowsSignals:
    """Tests for page_has_windows_signals function."""

    def test_empty_content_returns_false(self):
        """Empty content should return False."""
        assert page_has_windows_signals("") is False
        assert page_has_windows_signals(None) is False

    def test_detects_powershell(self):
        """Should detect PowerShell mentions."""
        content = "Use PowerShell to run the command."
        assert page_has_windows_signals(content) is True

    def test_detects_powershell_case_insensitive(self):
        """Should detect PowerShell case-insensitively."""
        assert page_has_windows_signals("powershell script") is True
        assert page_has_windows_signals("POWERSHELL command") is True

    def test_detects_exe_extension(self):
        """Should detect .exe file references."""
        content = "Download and run setup.exe"
        assert page_has_windows_signals(content) is True

    def test_detects_windows_server(self):
        """Should detect Windows Server references."""
        content = "Deploy on Windows Server 2019"
        assert page_has_windows_signals(content) is True

    def test_detects_iis(self):
        """Should detect IIS references."""
        content = "Configure IIS for your application"
        assert page_has_windows_signals(content) is True

    def test_detects_winget(self):
        """Should detect winget package manager."""
        content = "Install using winget install package"
        assert page_has_windows_signals(content) is True

    def test_detects_chocolatey(self):
        """Should detect Chocolatey package manager."""
        assert page_has_windows_signals("Install via choco install") is True
        assert page_has_windows_signals("Use chocolatey for packages") is True

    def test_detects_msiexec(self):
        """Should detect msiexec installer."""
        content = "Run msiexec /i package.msi"
        assert page_has_windows_signals(content) is True

    def test_detects_regedit(self):
        """Should detect registry editor references."""
        content = "Open regedit to modify settings"
        assert page_has_windows_signals(content) is True

    def test_detects_windows_registry(self):
        """Should detect Windows Registry references."""
        content = "Modify the Windows Registry key"
        assert page_has_windows_signals(content) is True

    def test_detects_net_framework(self):
        """Should detect .NET Framework references."""
        content = "Requires .NET Framework 4.8"
        assert page_has_windows_signals(content) is True

    def test_detects_win_versions(self):
        """Should detect Windows version references (win2019, win2022, etc.)."""
        assert page_has_windows_signals("Use win2019datacenter image") is True
        assert page_has_windows_signals("Deploy on win2022") is True
        assert page_has_windows_signals("Legacy win2016 support") is True

    def test_no_signals_returns_false(self):
        """Content without Windows signals should return False."""
        content = """
        # Install Azure CLI on Linux

        Run the following commands:

        curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash

        Then authenticate:

        az login
        """
        assert page_has_windows_signals(content) is False

    def test_cross_platform_content(self):
        """Cross-platform content without Windows-specific terms."""
        content = "Use the Azure CLI to manage resources. Works on Linux, macOS, and Windows."
        # "Windows" alone is not in PROSE_WINDOWS_PATTERNS
        assert page_has_windows_signals(content) is False


class TestIsWindowsBiased:
    """Tests for is_windows_biased function."""

    def test_under_azure_powershell_tab_not_biased(self):
        """Snippets under Azure PowerShell tab should not be flagged."""
        snippet = {
            'code': 'Get-AzResourceGroup',
            'context': 'List resource groups',
            'under_az_powershell_tab': True
        }
        assert is_windows_biased(snippet) is False

    def test_under_windows_header_not_biased(self):
        """Snippets under Windows header should not be flagged."""
        snippet = {
            'code': 'choco install azure-cli',
            'context': 'Windows installation',
            'windows_header': True
        }
        assert is_windows_biased(snippet) is False

    def test_windows_in_context_not_biased(self):
        """Snippets with Windows in context should not be flagged."""
        snippet = {
            'code': 'choco install package',
            'context': 'Windows installation steps'
        }
        assert is_windows_biased(snippet) is False

    def test_powershell_in_context_not_biased(self):
        """Snippets with PowerShell in context should not be flagged."""
        snippet = {
            'code': 'Get-ChildItem',
            'context': 'Using PowerShell'
        }
        assert is_windows_biased(snippet) is False

    def test_windows_in_url_not_biased(self):
        """Snippets from Windows-specific URLs should not be flagged."""
        snippet = {
            'code': 'msiexec /i package.msi',
            'context': 'Install',
            'url': 'https://docs.microsoft.com/windows/install'
        }
        assert is_windows_biased(snippet) is False

    def test_detects_windows_paths(self):
        """Should detect Windows paths."""
        snippet = {
            'code': r'cd C:\Users\admin\Documents',
            'context': 'Navigate to folder'
        }
        assert is_windows_biased(snippet) is True

    def test_detects_backslash_paths(self):
        """Should detect backslash in paths."""
        snippet = {
            'code': r'copy file.txt backup\file.txt',
            'context': 'Copy file'
        }
        assert is_windows_biased(snippet) is True

    def test_detects_cmd_exe(self):
        """Should detect cmd.exe references."""
        snippet = {
            'code': 'cmd.exe /c script.bat',
            'context': 'Run script'
        }
        assert is_windows_biased(snippet) is True

    def test_detects_powershell_commands(self):
        """Should detect PowerShell-specific cmdlets."""
        assert is_windows_biased({'code': 'Set-ExecutionPolicy RemoteSigned', 'context': ''}) is True
        assert is_windows_biased({'code': 'Get-ChildItem -Recurse', 'context': ''}) is True
        assert is_windows_biased({'code': 'New-Item -ItemType Directory', 'context': ''}) is True
        assert is_windows_biased({'code': 'Remove-Item -Recurse', 'context': ''}) is True

    def test_detects_windows_commands(self):
        """Should detect Windows command prompt commands."""
        assert is_windows_biased({'code': 'dir /s', 'context': ''}) is True
        assert is_windows_biased({'code': 'copy file1.txt file2.txt', 'context': ''}) is True
        assert is_windows_biased({'code': 'del /f file.txt', 'context': ''}) is True
        assert is_windows_biased({'code': 'cls', 'context': ''}) is True

    def test_detects_windows_service_commands(self):
        """Should detect Windows service commands."""
        assert is_windows_biased({'code': 'net start ServiceName', 'context': ''}) is True
        assert is_windows_biased({'code': 'net stop ServiceName', 'context': ''}) is True
        assert is_windows_biased({'code': 'sc query', 'context': ''}) is True

    def test_detects_windows_tools(self):
        """Should detect Windows-specific tools."""
        assert is_windows_biased({'code': 'choco install package', 'context': ''}) is True
        assert is_windows_biased({'code': 'winget install package', 'context': ''}) is True
        assert is_windows_biased({'code': 'msiexec /i package.msi', 'context': ''}) is True

    def test_detects_task_commands(self):
        """Should detect Windows task management commands."""
        assert is_windows_biased({'code': 'tasklist', 'context': ''}) is True
        assert is_windows_biased({'code': 'taskkill /f /im process.exe', 'context': ''}) is True

    def test_linux_commands_not_biased(self):
        """Linux commands should not be flagged as biased."""
        snippets = [
            {'code': 'ls -la', 'context': ''},
            {'code': 'cat file.txt', 'context': ''},
            {'code': 'sudo apt-get install package', 'context': ''},
            {'code': 'chmod +x script.sh', 'context': ''},
            {'code': 'cd /home/user', 'context': ''},
            {'code': 'curl https://example.com', 'context': ''},
            {'code': 'az login', 'context': ''},
        ]
        for snippet in snippets:
            assert is_windows_biased(snippet) is False, f"Should not flag: {snippet['code']}"

    def test_cross_platform_tools_not_biased(self):
        """Cross-platform tools should not be flagged."""
        snippets = [
            {'code': 'python script.py', 'context': ''},
            {'code': 'node app.js', 'context': ''},
            {'code': 'docker run container', 'context': ''},
            {'code': 'git clone repo', 'context': ''},
            {'code': 'npm install', 'context': ''},
        ]
        for snippet in snippets:
            assert is_windows_biased(snippet) is False, f"Should not flag: {snippet['code']}"


class TestIsWindowsIntentionalTitle:
    """Tests for is_windows_intentional_title function."""

    def test_empty_title_returns_false(self):
        """Empty title should return False."""
        assert is_windows_intentional_title("") is False
        assert is_windows_intentional_title(None) is False

    def test_detects_windows_keyword(self):
        """Should detect 'Windows' in title."""
        assert is_windows_intentional_title("Configure Windows Server on Azure") is True
        assert is_windows_intentional_title("Windows VM deployment") is True

    def test_detects_powershell(self):
        """Should detect PowerShell in title."""
        assert is_windows_intentional_title("Using PowerShell with Azure") is True
        assert is_windows_intentional_title("PowerShell quickstart") is True

    def test_detects_windows_server(self):
        """Should detect Windows Server in title."""
        assert is_windows_intentional_title("Deploy Windows Server 2019") is True

    def test_detects_win_versions(self):
        """Should detect win2016, win2019, win2022 patterns."""
        assert is_windows_intentional_title("Using win2019 image") is True
        assert is_windows_intentional_title("win2022 datacenter setup") is True
        assert is_windows_intentional_title("Legacy win16 support") is True

    def test_detects_iis(self):
        """Should detect IIS in title."""
        assert is_windows_intentional_title("Configure IIS on Azure VM") is True

    def test_detects_dotnet_framework(self):
        """Should detect .NET Framework in title."""
        assert is_windows_intentional_title("Deploy .NET Framework app") is True

    def test_detects_wcf_wpf_winforms(self):
        """Should detect WCF, WPF, WinForms in title."""
        assert is_windows_intentional_title("Migrate WCF to Azure") is True
        assert is_windows_intentional_title("WPF application deployment") is True
        assert is_windows_intentional_title("WinForms modernization") is True
        assert is_windows_intentional_title("Windows Forms migration") is True

    def test_detects_active_directory(self):
        """Should detect Active Directory and AD DS in title."""
        assert is_windows_intentional_title("Active Directory integration") is True
        assert is_windows_intentional_title("Configure AD DS on Azure") is True

    def test_detects_hyper_v(self):
        """Should detect Hyper-V in title."""
        assert is_windows_intentional_title("Hyper-V nested virtualization") is True

    def test_detects_package_managers(self):
        """Should detect winget and Chocolatey in title."""
        assert is_windows_intentional_title("Install tools with winget") is True
        assert is_windows_intentional_title("Using Chocolatey on Azure VMs") is True

    def test_case_insensitive(self):
        """Pattern matching should be case-insensitive."""
        assert is_windows_intentional_title("WINDOWS SERVER SETUP") is True
        assert is_windows_intentional_title("powershell quickstart") is True
        assert is_windows_intentional_title("iis configuration") is True

    def test_cross_platform_titles_return_false(self):
        """Cross-platform titles should return False."""
        assert is_windows_intentional_title("Install Azure CLI") is False
        assert is_windows_intentional_title("Deploy container to AKS") is False
        assert is_windows_intentional_title("Python quickstart") is False
        assert is_windows_intentional_title("Docker on Azure") is False
        assert is_windows_intentional_title(".NET 6 deployment") is False  # Not .NET Framework
