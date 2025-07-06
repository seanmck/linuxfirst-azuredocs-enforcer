from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context
import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '../../../'))
from src.shared.models import Base  # Import your SQLAlchemy Base

config = context.config
fileConfig(config.config_file_name)
target_metadata = Base.metadata

def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url, target_metadata=target_metadata, literal_binds=True, compare_type=True
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    # Get DATABASE_URL directly from environment instead of using engine_from_config
    import os
    from sqlalchemy import create_engine
    
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        raise ValueError("DATABASE_URL environment variable is not set")
    
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
