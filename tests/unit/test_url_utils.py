"""
Unit tests for shared/utils/url_utils.py
"""
from unittest.mock import patch, MagicMock
from shared.utils.url_utils import detect_url_source, extract_doc_set_from_url, format_doc_set_name


class TestDetectUrlSource:
    """Tests for detect_url_source function."""

    def test_none_url_returns_unknown(self):
        """None URL should return unknown."""
        assert detect_url_source(None) == "unknown"

    def test_empty_url_returns_unknown(self):
        """Empty URL should return unknown."""
        assert detect_url_source("") == "unknown"

    def test_github_url(self):
        """Should detect GitHub URLs."""
        urls = [
            "https://github.com/MicrosoftDocs/azure-docs",
            "https://github.com/Azure/azure-cli",
            "https://www.github.com/owner/repo",
        ]
        for url in urls:
            assert detect_url_source(url) == "github", f"Failed for: {url}"

    def test_ms_learn_url(self):
        """Should detect Microsoft Learn URLs."""
        urls = [
            "https://learn.microsoft.com/en-us/azure/storage",
            "https://learn.microsoft.com/azure/cli",
            "https://www.learn.microsoft.com/docs/article",
        ]
        for url in urls:
            assert detect_url_source(url) == "ms-learn", f"Failed for: {url}"

    def test_other_urls_return_unknown(self):
        """Other URLs should return unknown."""
        urls = [
            "https://example.com/page",
            "https://docs.microsoft.com/azure",
            "https://azure.microsoft.com",
            "https://google.com",
        ]
        for url in urls:
            assert detect_url_source(url) == "unknown", f"Failed for: {url}"

    def test_invalid_url_returns_unknown(self):
        """Invalid URLs should return unknown."""
        assert detect_url_source("not-a-url") == "unknown"
        # FTP URLs with github.com still get detected as github since we check domain
        assert detect_url_source("ftp://example.com") == "unknown"


class TestExtractDocSetFromUrl:
    """Tests for extract_doc_set_from_url function."""

    def test_none_url_returns_none(self):
        """None URL should return None."""
        assert extract_doc_set_from_url(None) is None

    def test_empty_url_returns_none(self):
        """Empty URL should return None."""
        assert extract_doc_set_from_url("") is None

    def test_learn_azure_service_url(self):
        """Should extract Azure service from learn.microsoft.com URLs."""
        url = "https://learn.microsoft.com/en-us/azure/storage/overview"
        result = extract_doc_set_from_url(url)
        assert result == "storage"

    def test_learn_product_url(self):
        """Should extract product from non-Azure learn.microsoft.com URLs."""
        url = "https://learn.microsoft.com/en-us/dotnet/overview"
        result = extract_doc_set_from_url(url)
        assert result == "dotnet"

    @patch('shared.utils.url_utils.get_repo_from_url')
    def test_github_url_with_tracked_repo(self, mock_get_repo):
        """Should extract service from tracked GitHub repo URLs."""
        mock_repo = MagicMock()
        mock_repo.name = "azure-docs-pr"
        mock_repo.public_name = "azure-docs"
        mock_repo.articles_path = "articles"
        mock_get_repo.return_value = mock_repo

        url = "https://github.com/MicrosoftDocs/azure-docs/blob/main/articles/storage/overview.md"
        result = extract_doc_set_from_url(url)
        assert result == "storage"

    @patch('shared.utils.url_utils.get_repo_from_url')
    def test_github_url_without_tracked_repo(self, mock_get_repo):
        """Should extract repo name for untracked GitHub repos."""
        mock_get_repo.return_value = None

        url = "https://github.com/Azure/azure-cli/blob/main/README.md"
        result = extract_doc_set_from_url(url)
        assert result == "azure-cli"

    def test_unrecognized_url_returns_none(self):
        """Unrecognized URLs should return None."""
        url = "https://example.com/page"
        result = extract_doc_set_from_url(url)
        assert result is None


class TestFormatDocSetName:
    """Tests for format_doc_set_name function."""

    def test_none_returns_unknown(self):
        """None should return Unknown."""
        assert format_doc_set_name(None) == "Unknown"

    def test_empty_returns_unknown(self):
        """Empty string should return Unknown."""
        assert format_doc_set_name("") == "Unknown"

    def test_replaces_hyphens_with_spaces(self):
        """Should replace hyphens with spaces."""
        assert format_doc_set_name("azure-storage") == "Azure Storage"

    def test_replaces_underscores_with_spaces(self):
        """Should replace underscores with spaces."""
        assert format_doc_set_name("azure_storage") == "Azure Storage"

    def test_title_cases_words(self):
        """Should title case words."""
        assert format_doc_set_name("azure storage") == "Azure Storage"

    def test_api_replacement(self):
        """Should replace Api with API."""
        assert format_doc_set_name("rest-api") == "REST API"
        assert format_doc_set_name("management-api") == "Management API"

    def test_ai_replacement(self):
        """Should replace Ai with AI."""
        assert format_doc_set_name("azure-ai") == "Azure AI"

    def test_ml_replacement(self):
        """Should replace Ml with ML."""
        assert format_doc_set_name("azure-ml") == "Azure ML"

    def test_iot_replacement(self):
        """Should replace Iot with IoT."""
        assert format_doc_set_name("azure-iot") == "Azure IoT"

    def test_sql_replacement(self):
        """Should replace Sql with SQL."""
        assert format_doc_set_name("azure-sql") == "Azure SQL"

    def test_vm_replacement(self):
        """Should replace Vm with VM."""
        assert format_doc_set_name("virtual-vm") == "Virtual VM"

    def test_cli_replacement(self):
        """Should replace Cli with CLI."""
        assert format_doc_set_name("azure-cli") == "Azure CLI"

    def test_sdk_replacement(self):
        """Should replace Sdk with SDK."""
        assert format_doc_set_name("python-sdk") == "Python SDK"

    def test_multiple_replacements(self):
        """Should handle multiple replacements."""
        assert format_doc_set_name("iot-api-sdk") == "IoT API SDK"
