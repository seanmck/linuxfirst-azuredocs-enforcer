"""
Unit tests for packages/extractor/parser.py
"""
from packages.extractor.parser import extract_code_snippets


class TestExtractCodeSnippets:
    """Tests for extract_code_snippets function."""

    def test_empty_html_returns_empty_list(self):
        """Empty HTML should return empty list."""
        assert extract_code_snippets("") == []
        assert extract_code_snippets("<html></html>") == []

    def test_html_without_pre_returns_empty_list(self):
        """HTML without pre blocks should return empty list."""
        html = "<html><body><p>No code here</p></body></html>"
        assert extract_code_snippets(html) == []

    def test_extracts_single_pre_block(self):
        """Should extract a single pre block."""
        html = "<html><body><pre>echo hello</pre></body></html>"
        snippets = extract_code_snippets(html)
        assert len(snippets) == 1
        assert snippets[0]['code'] == "echo hello"

    def test_extracts_multiple_pre_blocks(self):
        """Should extract multiple pre blocks."""
        html = """
        <html><body>
            <pre>echo first</pre>
            <pre>echo second</pre>
            <pre>echo third</pre>
        </body></html>
        """
        snippets = extract_code_snippets(html)
        assert len(snippets) == 3
        assert snippets[0]['code'] == "echo first"
        assert snippets[1]['code'] == "echo second"
        assert snippets[2]['code'] == "echo third"

    def test_extracts_context_from_parent_heading(self):
        """Should extract context from heading in parent container."""
        html = """
        <html><body>
            <section>
                <h2>Install Azure CLI</h2>
                <pre>curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash</pre>
            </section>
        </body></html>
        """
        snippets = extract_code_snippets(html)
        assert len(snippets) == 1
        assert snippets[0]['context'] == "Install Azure CLI"

    def test_extracts_context_from_previous_heading(self):
        """Should extract context from previous heading if no parent heading."""
        html = """
        <html><body>
            <h2>Configuration Steps</h2>
            <p>Run the following:</p>
            <pre>az configure</pre>
        </body></html>
        """
        snippets = extract_code_snippets(html)
        assert len(snippets) == 1
        assert snippets[0]['context'] == "Configuration Steps"

    def test_extracts_context_from_h1_to_h6(self):
        """Should extract context from any heading level."""
        for level in range(1, 7):
            html = f"""
            <html><body>
                <h{level}>Heading Level {level}</h{level}>
                <pre>code</pre>
            </body></html>
            """
            snippets = extract_code_snippets(html)
            assert snippets[0]['context'] == f"Heading Level {level}"

    def test_detects_azure_powershell_tab(self):
        """Should detect code under Azure PowerShell tab."""
        html = """
        <html><body>
            <div data-tab="azure-powershell">
                <pre>Get-AzResourceGroup</pre>
            </div>
        </body></html>
        """
        snippets = extract_code_snippets(html)
        assert len(snippets) == 1
        assert snippets[0]['under_az_powershell_tab'] is True

    def test_detects_azure_powershell_tab_case_insensitive(self):
        """Should detect Azure PowerShell tab case-insensitively."""
        html = """
        <html><body>
            <div data-tab="Azure-PowerShell">
                <pre>Get-AzVM</pre>
            </div>
        </body></html>
        """
        snippets = extract_code_snippets(html)
        assert snippets[0]['under_az_powershell_tab'] is True

    def test_non_powershell_tab_not_flagged(self):
        """Code under non-PowerShell tabs should not be flagged."""
        html = """
        <html><body>
            <div data-tab="azure-cli">
                <pre>az vm list</pre>
            </div>
        </body></html>
        """
        snippets = extract_code_snippets(html)
        assert len(snippets) == 1
        assert snippets[0]['under_az_powershell_tab'] is False

    def test_detects_windows_header(self):
        """Should detect code under Windows header."""
        html = """
        <html><body>
            <section>
                <h2>Windows Installation</h2>
                <pre>choco install azure-cli</pre>
            </section>
        </body></html>
        """
        snippets = extract_code_snippets(html)
        assert len(snippets) == 1
        assert snippets[0]['windows_header'] is True

    def test_windows_header_case_insensitive(self):
        """Should detect Windows header case-insensitively."""
        html = """
        <html><body>
            <h2>WINDOWS Setup</h2>
            <pre>winget install app</pre>
        </body></html>
        """
        snippets = extract_code_snippets(html)
        assert snippets[0]['windows_header'] is True

    def test_non_windows_header_not_flagged(self):
        """Code under non-Windows headers should not be flagged."""
        html = """
        <html><body>
            <section>
                <h2>Linux Installation</h2>
                <pre>apt-get install azure-cli</pre>
            </section>
        </body></html>
        """
        snippets = extract_code_snippets(html)
        assert len(snippets) == 1
        assert snippets[0]['windows_header'] is False

    def test_includes_excerpt(self):
        """Should include excerpt with surrounding context."""
        html = """
        <html><body>
            <section>
                <p>Before the code</p>
                <pre>echo hello</pre>
                <p>After the code</p>
            </section>
        </body></html>
        """
        snippets = extract_code_snippets(html)
        assert len(snippets) == 1
        assert 'excerpt' in snippets[0]
        assert snippets[0]['excerpt'] is not None

    def test_multiline_code_preserved(self):
        """Should preserve multiline code."""
        html = """
        <html><body>
            <pre>line 1
line 2
line 3</pre>
        </body></html>
        """
        snippets = extract_code_snippets(html)
        assert "line 1" in snippets[0]['code']
        assert "line 2" in snippets[0]['code']
        assert "line 3" in snippets[0]['code']

    def test_nested_pre_in_div(self):
        """Should extract pre inside nested divs."""
        html = """
        <html><body>
            <div>
                <div>
                    <div>
                        <pre>nested code</pre>
                    </div>
                </div>
            </div>
        </body></html>
        """
        snippets = extract_code_snippets(html)
        assert len(snippets) == 1
        assert snippets[0]['code'] == "nested code"

    def test_snippet_structure(self):
        """Should return snippets with correct structure."""
        html = """
        <html><body>
            <h2>Example</h2>
            <pre>echo test</pre>
        </body></html>
        """
        snippets = extract_code_snippets(html)
        assert len(snippets) == 1
        snippet = snippets[0]

        # Check required keys exist
        assert 'code' in snippet
        assert 'context' in snippet
        assert 'excerpt' in snippet
        assert 'under_az_powershell_tab' in snippet
        assert 'windows_header' in snippet
