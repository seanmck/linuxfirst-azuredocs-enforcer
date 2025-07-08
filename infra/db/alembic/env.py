from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context
import os
import sys
# Add the project root to the Python path
project_root = os.path.join(os.path.dirname(__file__), '../../../')
sys.path.insert(0, project_root)
from shared.models import Base  # Import your SQLAlchemy Base

config = context.config
fileConfig(config.config_file_name)
target_metadata = Base.metadata

def run_migrations_offline():
    # Use shared configuration system with fallback to config file
    try:
        from shared.config import config as shared_config
        url = shared_config.database.url
        print(f"Using database URL from shared config: {url}")
    except Exception as e:
        print(f"Failed to load shared config: {e}")
        # Fallback to config file
        url = config.get_main_option("sqlalchemy.url")
        if not url:
            raise ValueError("No database URL found in shared config or alembic.ini")
        print(f"Using database URL from alembic.ini: {url}")
    
    context.configure(
        url=url, target_metadata=target_metadata, literal_binds=True, compare_type=True
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    # Use shared configuration system with fallback to direct environment variable
    from sqlalchemy import create_engine
    
    try:
        from shared.config import config
        database_url = config.database.url
        print(f"Using database URL from shared config: {database_url}")
    except Exception as e:
        print(f"Failed to load shared config: {e}")
        # Fallback to direct environment variable check
        database_url = os.environ.get('DATABASE_URL')
        if not database_url:
            raise ValueError("DATABASE_URL environment variable is not set and shared config failed to load")
        print(f"Using database URL from environment: {database_url}")
    
    connectable = create_engine(database_url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, compare_type=True
        )
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
