import os
import re
import urllib
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.shared.models import Base
from azure.identity import ManagedIdentityCredential

def parse_pg_kv_connstr(kv_str):
    kv = dict(re.findall(r'(\w+)=([^ ]+)', kv_str))
    user = kv.get('user')
    host = kv.get('host')
    port = kv.get('port', '5432')
    dbname = kv.get('dbname')
    sslmode = kv.get('sslmode', 'require')
    password = kv.get('password', '')

    # If no password and user looks like AAD, fetch token
    if not password and user and user.startswith('aad_'):
        try:
            # Use service connector managed identity (not workload identity)
            managed_identity_client_id = os.getenv('AZURE_POSTGRESQL_CLIENTID')
            if managed_identity_client_id:
                from azure.identity import DefaultAzureCredential
                cred = DefaultAzureCredential()
                token = cred.get_token('https://ossrdbms-aad.database.windows.net/.default').token
                password = urllib.parse.quote_plus(token)
            else:
                raise RuntimeError("AZURE_POSTGRESQL_CLIENTID not found")
        except Exception as e:
            raise RuntimeError(f'Failed to get Azure AD token: {e}')
    pw_part = f':{password}' if password else ''
    return f'postgresql+psycopg2://{user}{pw_part}@{host}:{port}/{dbname}?sslmode={sslmode}'

# Prefer Service Connector's connection string if present
svc_conn_url = (
    os.environ.get("AZURE_POSTGRESQL_CONNECTIONSTRING")
    or os.environ.get("DATABASE_URL")
    or os.environ.get("PGCONNSTR_postgresql")
)
if svc_conn_url and svc_conn_url.startswith("dbname="):
    DB_URL = parse_pg_kv_connstr(svc_conn_url)
elif svc_conn_url:
    DB_URL = svc_conn_url
else:
    DB_MODE = os.environ.get("DB_MODE")
    DB_HOST = os.environ.get("DB_HOST", "localhost")
    DB_USER = os.environ.get("DB_USER", "azuredocs_user")
    DB_NAME = os.environ.get("DB_NAME", "azuredocs")
    DB_PASS = os.environ.get("DB_PASS", "azuredocs_pass")

    if DB_MODE == "azure":
        from azure.identity import DefaultAzureCredential
        credential = DefaultAzureCredential()
        token = credential.get_token("https://ossrdbms-aad.database.windows.net/.default").token
        user = f"{DB_USER}@{DB_HOST.split('.')[0]}"
        DB_URL = (
            f"postgresql+psycopg2://{user}:{urllib.parse.quote_plus(token)}@{DB_HOST}:5432/{DB_NAME}?sslmode=require"
        )
    else:
        DB_URL = (
            f"postgresql+psycopg2://{DB_USER}:{urllib.parse.quote_plus(DB_PASS)}@{DB_HOST}:5432/{DB_NAME}?sslmode=disable"
        )

engine = create_engine(DB_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)
