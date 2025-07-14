"""
Centralized configuration management for the Azure Docs Enforcer project.
"""
import os
import urllib.parse
from dataclasses import dataclass
from typing import Optional


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
class Config:
    """Main configuration class that combines all configuration sections"""
    database: DatabaseConfig
    azure_openai: AzureOpenAIConfig
    rabbitmq: RabbitMQConfig
    application: ApplicationConfig
    
    @classmethod
    def from_env(cls) -> 'Config':
        """Create configuration from environment variables"""
        return cls(
            database=DatabaseConfig.from_env(),
            azure_openai=AzureOpenAIConfig.from_env(),
            rabbitmq=RabbitMQConfig.from_env(),
            application=ApplicationConfig.from_env()
        )


# Global configuration instance
config = Config.from_env()