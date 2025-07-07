FROM mcr.microsoft.com/devcontainers/python:3.12

# Set workdir
WORKDIR /app

# Install system dependencies, Azure CLI, and clean up
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    postgresql-client \
    curl \
    ca-certificates \
    lsb-release \
    gnupg \
    && curl -sL https://aka.ms/InstallAzureCLIDeb | bash \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (changes less frequently)
COPY webui/requirements.txt /app/requirements.txt

# Install Python dependencies and Alembic (expensive layer - cache this!)
RUN pip install --no-cache-dir -r /app/requirements.txt alembic psycopg2-binary

# Create directory structure
RUN mkdir -p /app/src/shared /app/infra/db/alembic/versions

# Copy shared models (needed for alembic migrations, changes less frequently)
COPY src/shared/models.py /app/src/shared/models.py
COPY src/__init__.py /app/src/__init__.py
COPY src/shared/__init__.py /app/src/shared/__init__.py

# Copy Alembic configuration (changes less frequently)
COPY infra/db/alembic.ini /app/infra/db/alembic.ini
COPY infra/db/alembic/env.py /app/infra/db/alembic/env.py
COPY infra/db/alembic/__init__.py /app/infra/db/alembic/__init__.py

# Copy schema (changes less frequently)
COPY infra/db/schema.sql /app/schema.sql

# Copy migration files (changes most frequently - put last)
COPY infra/db/alembic/versions/ /app/infra/db/alembic/versions/
COPY infra/db/migrate.sh /app/infra/db/migrate.sh

# Ensure migrate.sh is executable
RUN chmod +x /app/infra/db/migrate.sh

# Set entrypoint to run migrations
ENTRYPOINT ["/app/infra/db/migrate.sh"]