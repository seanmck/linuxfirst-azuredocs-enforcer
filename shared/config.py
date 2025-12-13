"""
Centralized configuration management for the Azure Docs Enforcer project.
"""
import logging
import os
import urllib.parse
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass
class DatabaseConfig:
    """Database configuration settings"""
    url: str
    host: str = "localhost"
    user: str = "azuredocs_user"
    password: str = "azuredocs_pass"
    name: str = "azuredocs"
    port: int = 5432
    mode: str = "local"  # local, azure
    
    @classmethod
    def from_env(cls) -> 'DatabaseConfig':
        # Check for service connector connection string first
        svc_conn_url = (
            os.environ.get("AZURE_POSTGRESQL_CONNECTIONSTRING")
            or os.environ.get("DATABASE_URL")
            or os.environ.get("PGCONNSTR_postgresql")
        )
        
        if svc_conn_url:
            # If we have a connection string, use it directly
            if svc_conn_url.startswith("dbname="):
                # Parse key-value format
                url = cls._parse_pg_kv_connstr(svc_conn_url)
            else:
                url = svc_conn_url
            
            # For local development, disable SSL if needed
            if "localhost" in url or "127.0.0.1" in url:
                if "sslmode=" not in url:
                    url += "&sslmode=disable" if "?" in url else "?sslmode=disable"
                else:
                    # Replace any existing sslmode with disable
                    import re
                    url = re.sub(r'sslmode=\w+', 'sslmode=disable', url)
            
            return cls(
                url=url,
                mode="service_connector"
            )
        
        # Fall back to individual environment variables
        host = os.environ.get("DB_HOST", "localhost")
        user = os.environ.get("DB_USER", "azuredocs_user")
        password = os.environ.get("DB_PASS", "azuredocs_pass")
        name = os.environ.get("DB_NAME", "azuredocs")
        mode = os.environ.get("DB_MODE", "local")
        
        if mode == "azure":
            # Azure AD authentication
            from azure.identity import DefaultAzureCredential
            credential = DefaultAzureCredential()
            token = credential.get_token("https://ossrdbms-aad.database.windows.net/.default").token
            user_with_host = f"{user}@{host.split('.')[0]}"
            url = (
                f"postgresql+psycopg2://{user_with_host}:{urllib.parse.quote_plus(token)}@{host}:5432/{name}?sslmode=require"
            )
        else:
            # Standard username/password authentication
            url = (
                f"postgresql+psycopg2://{user}:{urllib.parse.quote_plus(password)}@{host}:5432/{name}?sslmode=disable"
            )
        
        return cls(
            url=url,
            host=host,
            user=user,
            password=password,
            name=name,
            mode=mode
        )
    
    @staticmethod
    def _parse_pg_kv_connstr(kv_str: str) -> str:
        """Parse PostgreSQL key-value connection string format"""
        import re
        kv = dict(re.findall(r'(\w+)=([^ ]+)', kv_str))
        user = kv.get('user')
        host = kv.get('host')
        port = kv.get('port', '5432')
        dbname = kv.get('dbname')
        sslmode = kv.get('sslmode', 'require')
        password = kv.get('password', '')
        
        # If no password and user looks like AAD, use service connector managed identity (not workload identity)
        if not password and user and user.startswith('aad_'):
            try:
                # Use the service connector's managed identity (from the node, not workload identity)
                managed_identity_client_id = os.getenv('AZURE_POSTGRESQL_CLIENTID')
                if managed_identity_client_id:
                    from azure.identity import ManagedIdentityCredential
                    # Use DefaultAzureCredential to find the managed identity on the node
                    from azure.identity import DefaultAzureCredential
                    cred = DefaultAzureCredential()
                    token = cred.get_token('https://ossrdbms-aad.database.windows.net/.default').token
                    password = urllib.parse.quote_plus(token)
                else:
                    raise RuntimeError("AZURE_POSTGRESQL_CLIENTID not found for AAD authentication")
            except Exception as e:
                raise RuntimeError(f'Failed to get Azure AD token for PostgreSQL: {e}')
        
        pw_part = f':{password}' if password else ''
        return f'postgresql+psycopg2://{user}{pw_part}@{host}:{port}/{dbname}?sslmode={sslmode}'


@dataclass
class AzureOpenAIConfig:
    """Azure OpenAI configuration settings"""
    api_key: Optional[str] = None
    endpoint: Optional[str] = None
    deployment: str = "gpt-35-turbo"
    api_version: str = "2023-05-15"
    client_id: Optional[str] = None  # For managed identity authentication
    
    @classmethod
    def from_env(cls) -> 'AzureOpenAIConfig':
        return cls(
            api_key=os.getenv("AZURE_OPENAI_KEY"),
            endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
            deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-35-turbo"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2023-05-15"),
            client_id=os.getenv("AZURE_OPENAI_CLIENTID")
        )
    
    @property
    def is_available(self) -> bool:
        """Check if Azure OpenAI configuration is complete"""
        return self.endpoint and (self.api_key or self.client_id)
    
    @property
    def use_managed_identity(self) -> bool:
        """Check if we should use managed identity authentication"""
        return self.client_id and not self.api_key


@dataclass
class RabbitMQConfig:
    """RabbitMQ configuration settings"""
    host: str = "localhost"
    port: int = 5672
    username: str = "guest"
    password: str = "guest"
    
    @classmethod
    def from_env(cls) -> 'RabbitMQConfig':
        # Handle case where RABBITMQ_PORT might be a full URL
        port_env = os.getenv("RABBITMQ_PORT", "5672")
        if port_env.startswith("tcp://"):
            # Extract port from TCP URL like "tcp://10.0.62.126:5672"
            port = int(port_env.split(":")[-1])
            host = port_env.split("://")[1].split(":")[0]
        else:
            port = int(port_env)
            host = os.getenv("RABBITMQ_HOST", "localhost")
            
        return cls(
            host=host,
            port=port,
            username=os.getenv("RABBITMQ_USERNAME", "guest"),
            password=os.getenv("RABBITMQ_PASSWORD", "guest")
        )


@dataclass
class ApplicationConfig:
    """General application configuration"""
    environment: str = "development"
    debug: bool = False
    test_mode: bool = False
    user_agent: str = "Azure-Docs-Enforcer/1.0"
    # Web crawling configs removed - GitHub-only focus
    
    # Retry mechanism configuration
    max_retries: int = 3
    retry_delay_seconds: int = 60
    
    @classmethod
    def from_env(cls) -> 'ApplicationConfig':
        # Web crawling configs removed - GitHub-only focus
        
        return cls(
            environment=os.getenv("ENVIRONMENT", "development"),
            debug=os.getenv("DEBUG", "false").lower() == "true",
            test_mode=os.getenv("TEST_MODE", "0") == "1",
            user_agent=os.getenv("USER_AGENT", "Azure-Docs-Enforcer/1.0"),
            # Web crawling configs removed - GitHub-only focus
            max_retries=int(os.getenv("MAX_RETRIES", "3")),
            retry_delay_seconds=int(os.getenv("RETRY_DELAY_SECONDS", "60"))
        )


@dataclass
class GitHubOAuthConfig:
    """GitHub OAuth configuration settings"""
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: str = "repo"  # Need 'repo' scope for private repositories
    
    @classmethod
    def from_env(cls) -> 'GitHubOAuthConfig':
        """Create configuration from environment variables"""
        client_id = os.environ.get("GITHUB_CLIENT_ID", "")
        client_secret = os.environ.get("GITHUB_CLIENT_SECRET", "")
        redirect_uri = os.environ.get("GITHUB_OAUTH_REDIRECT_URI", "/auth/github/callback")
        scopes = os.environ.get("GITHUB_OAUTH_SCOPES", "repo")  # Default to 'repo' for private repos
        
        # Make redirect URI absolute if it's relative
        if redirect_uri.startswith("/"):
            base_url = os.environ.get("BASE_URL", "http://localhost:8000")
            redirect_uri = f"{base_url.rstrip('/')}{redirect_uri}"
        
        return cls(
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
            scopes=scopes
        )


@dataclass
class GitHubAppConfig:
    """GitHub App configuration settings"""
    app_id: str
    private_key: str
    installation_url: str
    
    @classmethod
    def from_env(cls) -> 'GitHubAppConfig':
        """Create configuration from environment variables"""
        app_id = os.environ.get("GITHUB_APP_ID", "")
        private_key = os.environ.get("GITHUB_APP_PRIVATE_KEY", "")
        installation_url = os.environ.get("GITHUB_APP_INSTALLATION_URL", "")
        
        return cls(
            app_id=app_id,
            private_key=private_key,
            installation_url=installation_url
        )


@dataclass
class Config:
    """Main configuration class that combines all configuration sections"""
    database: DatabaseConfig
    azure_openai: AzureOpenAIConfig
    rabbitmq: RabbitMQConfig
    application: ApplicationConfig
    github_oauth: GitHubOAuthConfig
    github_app: GitHubAppConfig
    
    @classmethod
    def from_env(cls) -> 'Config':
        """Create configuration from environment variables"""
        return cls(
            database=DatabaseConfig.from_env(),
            azure_openai=AzureOpenAIConfig.from_env(),
            rabbitmq=RabbitMQConfig.from_env(),
            application=ApplicationConfig.from_env(),
            github_oauth=GitHubOAuthConfig.from_env(),
            github_app=GitHubAppConfig.from_env()
        )


# Global configuration instance
config = Config.from_env()


# =============================================================================
# Azure Documentation Repositories Configuration
# =============================================================================

@dataclass
class AzureDocsRepo:
    """Configuration for an Azure documentation repository"""
    owner: str
    name: str
    public_name: str  # Public repo equivalent (for fallback)
    branch: str = "main"
    articles_path: str = "articles"

    @property
    def full_name(self) -> str:
        """Returns owner/name format (e.g., MicrosoftDocs/azure-docs-pr)"""
        return f"{self.owner}/{self.name}"

    @property
    def public_full_name(self) -> str:
        """Returns owner/public_name format (e.g., MicrosoftDocs/azure-docs)"""
        return f"{self.owner}/{self.public_name}"

    def get_scan_url(self) -> str:
        """Returns the GitHub URL for scanning this repo"""
        return f"https://github.com/{self.owner}/{self.name}/tree/{self.branch}/{self.articles_path}"

    def get_raw_url(self, file_path: str) -> str:
        """Returns the raw.githubusercontent.com URL for a file"""
        return f"https://raw.githubusercontent.com/{self.owner}/{self.name}/{self.branch}/{file_path}"


def _get_default_repos() -> list[AzureDocsRepo]:
    """Return the default repository configuration"""
    return [
        AzureDocsRepo(
            owner="MicrosoftDocs",
            name="azure-docs-pr",
            public_name="azure-docs",
        )
    ]


def _load_repos_config() -> list[AzureDocsRepo]:
    """Load repository configuration from YAML file"""
    # Allow override via environment variable
    config_path = os.getenv(
        "REPOS_CONFIG_PATH",
        str(Path(__file__).parent.parent / "config" / "repos.yaml")
    )

    try:
        with open(config_path, "r") as f:
            data = yaml.safe_load(f)

        repos = []
        for repo_data in data.get("repos", []):
            try:
                repos.append(AzureDocsRepo(
                    owner=repo_data["owner"],
                    name=repo_data["name"],
                    public_name=repo_data.get("public_name", repo_data["name"]),
                    branch=repo_data.get("branch", "main"),
                    articles_path=repo_data.get("articles_path", "articles"),
                ))
            except KeyError as e:
                field_name = str(e.args[0]) if e.args else str(e)
                logger.warning("Missing required field %s in repo config, skipping entry", field_name)
                continue
        return repos
    except FileNotFoundError:
        # Fallback to default if config file not found
        logger.warning("repos.yaml not found at %s, using defaults", config_path)
        return _get_default_repos()
    except yaml.YAMLError as e:
        # Fallback to default if YAML is malformed
        logger.error("Failed to parse YAML at %s: %s, using defaults", config_path, e)
        return _get_default_repos()
    except Exception as e:
        # Catch any other unexpected errors
        logger.error("Failed to load repos config from %s: %s, using defaults", config_path, e)
        return _get_default_repos()


# Load repos at module initialization
AZURE_DOCS_REPOS: list[AzureDocsRepo] = _load_repos_config()


def get_repo_scan_urls() -> list[str]:
    """Returns list of GitHub URLs for scanning all tracked repos"""
    return [repo.get_scan_url() for repo in AZURE_DOCS_REPOS]


def get_repo_from_url(url: str) -> Optional[AzureDocsRepo]:
    """
    Given a GitHub URL, returns the matching repo config.
    Matches against both private (-pr) and public repo names.

    Args:
        url: A GitHub URL (e.g., https://github.com/MicrosoftDocs/azure-docs-pr/blob/main/articles/...)

    Returns:
        The matching AzureDocsRepo config, or None if not found
    """
    if not url or 'github.com' not in url:
        return None

    url_lower = url.lower()
    for repo in AZURE_DOCS_REPOS:
        # Check for both private and public repo names (case-insensitive)
        private_pattern = f"{repo.owner}/{repo.name}".lower()
        public_pattern = f"{repo.owner}/{repo.public_name}".lower()

        if private_pattern in url_lower or public_pattern in url_lower:
            return repo

    return None


def is_tracked_repo_url(url: str) -> bool:
    """Check if a URL belongs to one of our tracked repos"""
    return get_repo_from_url(url) is not None