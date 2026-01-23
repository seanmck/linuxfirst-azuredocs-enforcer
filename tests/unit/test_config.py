"""
Unit tests for shared/config.py
"""
import pytest
from unittest.mock import patch, MagicMock
from shared.config import (
    DatabaseConfig,
    AzureOpenAIConfig,
    RabbitMQConfig,
    AzureDocsRepo,
    get_repo_from_url,
    is_tracked_repo_url,
)


class TestDatabaseConfigParsePgKvConnstr:
    """Tests for DatabaseConfig._parse_pg_kv_connstr method."""

    def test_parses_basic_connection_string(self):
        """Should parse basic key-value connection string."""
        connstr = "dbname=mydb user=myuser host=localhost port=5432"
        result = DatabaseConfig._parse_pg_kv_connstr(connstr)
        assert "mydb" in result
        assert "myuser" in result
        assert "localhost" in result
        assert "5432" in result

    def test_parses_connection_string_with_password(self):
        """Should parse connection string with password."""
        connstr = "dbname=mydb user=myuser host=localhost port=5432 password=secret"
        result = DatabaseConfig._parse_pg_kv_connstr(connstr)
        assert "secret" in result
        assert "postgresql+psycopg2://" in result

    def test_parses_connection_string_with_sslmode(self):
        """Should preserve sslmode setting."""
        connstr = "dbname=mydb user=myuser host=localhost port=5432 sslmode=require"
        result = DatabaseConfig._parse_pg_kv_connstr(connstr)
        assert "sslmode=require" in result

    def test_defaults_port_to_5432(self):
        """Should default to port 5432 if not specified."""
        connstr = "dbname=mydb user=myuser host=localhost"
        result = DatabaseConfig._parse_pg_kv_connstr(connstr)
        assert "5432" in result


class TestAzureOpenAIConfig:
    """Tests for AzureOpenAIConfig class."""

    def test_is_available_with_endpoint_and_key(self):
        """Should be available with endpoint and API key."""
        config = AzureOpenAIConfig(
            endpoint="https://example.openai.azure.com",
            api_key="test-key"
        )
        assert config.is_available  # Truthy check

    def test_is_available_with_endpoint_and_client_id(self):
        """Should be available with endpoint and client_id."""
        config = AzureOpenAIConfig(
            endpoint="https://example.openai.azure.com",
            client_id="test-client-id"
        )
        assert config.is_available  # Truthy check

    def test_not_available_without_endpoint(self):
        """Should not be available without endpoint."""
        config = AzureOpenAIConfig(api_key="test-key")
        assert not config.is_available

    def test_not_available_without_credentials(self):
        """Should not be available without key or client_id."""
        config = AzureOpenAIConfig(endpoint="https://example.openai.azure.com")
        assert not config.is_available

    def test_use_managed_identity_true(self):
        """Should use managed identity when client_id set and no api_key."""
        config = AzureOpenAIConfig(
            endpoint="https://example.openai.azure.com",
            client_id="test-client-id"
        )
        assert config.use_managed_identity is True

    def test_use_managed_identity_false_with_key(self):
        """Should not use managed identity when api_key is set."""
        config = AzureOpenAIConfig(
            endpoint="https://example.openai.azure.com",
            api_key="test-key",
            client_id="test-client-id"
        )
        assert config.use_managed_identity is False


class TestRabbitMQConfig:
    """Tests for RabbitMQConfig class."""

    @patch.dict('os.environ', {}, clear=True)
    def test_defaults(self):
        """Should have sensible defaults."""
        config = RabbitMQConfig.from_env()
        assert config.host == "localhost"
        assert config.port == 5672
        assert config.username == "guest"
        assert config.password == "guest"

    @patch.dict('os.environ', {'RABBITMQ_HOST': 'rabbit.example.com', 'RABBITMQ_PORT': '5673'})
    def test_from_env_variables(self):
        """Should read from environment variables."""
        config = RabbitMQConfig.from_env()
        assert config.host == "rabbit.example.com"
        assert config.port == 5673

    @patch.dict('os.environ', {'RABBITMQ_PORT': 'tcp://10.0.62.126:5672'})
    def test_parses_tcp_url_format(self):
        """Should parse TCP URL format for port."""
        config = RabbitMQConfig.from_env()
        assert config.host == "10.0.62.126"
        assert config.port == 5672


class TestAzureDocsRepo:
    """Tests for AzureDocsRepo class."""

    def test_full_name(self):
        """Should return owner/name format."""
        repo = AzureDocsRepo(
            owner="MicrosoftDocs",
            name="azure-docs-pr",
            public_name="azure-docs"
        )
        assert repo.full_name == "MicrosoftDocs/azure-docs-pr"

    def test_public_full_name(self):
        """Should return owner/public_name format."""
        repo = AzureDocsRepo(
            owner="MicrosoftDocs",
            name="azure-docs-pr",
            public_name="azure-docs"
        )
        assert repo.public_full_name == "MicrosoftDocs/azure-docs"

    def test_get_scan_url(self):
        """Should return correct GitHub scan URL."""
        repo = AzureDocsRepo(
            owner="MicrosoftDocs",
            name="azure-docs-pr",
            public_name="azure-docs",
            branch="main",
            articles_path="articles"
        )
        expected = "https://github.com/MicrosoftDocs/azure-docs-pr/tree/main/articles"
        assert repo.get_scan_url() == expected

    def test_get_scan_url_custom_branch(self):
        """Should use custom branch in URL."""
        repo = AzureDocsRepo(
            owner="MicrosoftDocs",
            name="azure-docs-pr",
            public_name="azure-docs",
            branch="develop"
        )
        assert "/tree/develop/" in repo.get_scan_url()

    def test_get_scan_url_custom_articles_path(self):
        """Should use custom articles path in URL."""
        repo = AzureDocsRepo(
            owner="MicrosoftDocs",
            name="azure-docs-pr",
            public_name="azure-docs",
            articles_path="docs"
        )
        assert "/docs" in repo.get_scan_url()

    def test_get_raw_url(self):
        """Should return correct raw.githubusercontent.com URL."""
        repo = AzureDocsRepo(
            owner="MicrosoftDocs",
            name="azure-docs-pr",
            public_name="azure-docs",
            branch="main"
        )
        file_path = "articles/storage/overview.md"
        expected = "https://raw.githubusercontent.com/MicrosoftDocs/azure-docs-pr/main/articles/storage/overview.md"
        assert repo.get_raw_url(file_path) == expected


class TestGetRepoFromUrl:
    """Tests for get_repo_from_url function."""

    def test_none_url_returns_none(self):
        """None URL should return None."""
        assert get_repo_from_url(None) is None

    def test_empty_url_returns_none(self):
        """Empty URL should return None."""
        assert get_repo_from_url("") is None

    def test_non_github_url_returns_none(self):
        """Non-GitHub URL should return None."""
        assert get_repo_from_url("https://gitlab.com/owner/repo") is None

    @patch('shared.config.AZURE_DOCS_REPOS', [
        AzureDocsRepo(owner="MicrosoftDocs", name="azure-docs-pr", public_name="azure-docs")
    ])
    def test_matches_private_repo_url(self):
        """Should match private repo URL."""
        url = "https://github.com/MicrosoftDocs/azure-docs-pr/blob/main/articles/test.md"
        result = get_repo_from_url(url)
        assert result is not None
        assert result.name == "azure-docs-pr"

    @patch('shared.config.AZURE_DOCS_REPOS', [
        AzureDocsRepo(owner="MicrosoftDocs", name="azure-docs-pr", public_name="azure-docs")
    ])
    def test_matches_public_repo_url(self):
        """Should match public repo URL."""
        url = "https://github.com/MicrosoftDocs/azure-docs/blob/main/articles/test.md"
        result = get_repo_from_url(url)
        assert result is not None
        assert result.public_name == "azure-docs"

    @patch('shared.config.AZURE_DOCS_REPOS', [
        AzureDocsRepo(owner="MicrosoftDocs", name="azure-docs-pr", public_name="azure-docs")
    ])
    def test_case_insensitive_matching(self):
        """Should match URLs case-insensitively."""
        url = "https://github.com/MICROSOFTDOCS/AZURE-DOCS-PR/blob/main/articles/test.md"
        result = get_repo_from_url(url)
        assert result is not None

    @patch('shared.config.AZURE_DOCS_REPOS', [
        AzureDocsRepo(owner="MicrosoftDocs", name="azure-docs-pr", public_name="azure-docs")
    ])
    def test_untracked_repo_returns_none(self):
        """Should return None for untracked repos."""
        url = "https://github.com/Azure/azure-cli/blob/main/README.md"
        result = get_repo_from_url(url)
        assert result is None


class TestIsTrackedRepoUrl:
    """Tests for is_tracked_repo_url function."""

    @patch('shared.config.AZURE_DOCS_REPOS', [
        AzureDocsRepo(owner="MicrosoftDocs", name="azure-docs-pr", public_name="azure-docs")
    ])
    def test_tracked_repo_returns_true(self):
        """Should return True for tracked repo URLs."""
        url = "https://github.com/MicrosoftDocs/azure-docs-pr/blob/main/articles/test.md"
        assert is_tracked_repo_url(url) is True

    @patch('shared.config.AZURE_DOCS_REPOS', [
        AzureDocsRepo(owner="MicrosoftDocs", name="azure-docs-pr", public_name="azure-docs")
    ])
    def test_untracked_repo_returns_false(self):
        """Should return False for untracked repo URLs."""
        url = "https://github.com/Azure/azure-cli/blob/main/README.md"
        assert is_tracked_repo_url(url) is False

    def test_non_github_url_returns_false(self):
        """Should return False for non-GitHub URLs."""
        assert is_tracked_repo_url("https://gitlab.com/owner/repo") is False
