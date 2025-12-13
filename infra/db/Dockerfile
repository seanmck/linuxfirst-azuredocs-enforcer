# Database migration container for Azure PostgreSQL
# Uses Azure Workload Identity to authenticate via federated tokens

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
COPY infra/db/requirements.txt /app/requirements.txt

# Install Python dependencies (expensive layer - cache this!)
RUN pip install --no-cache-dir -r /app/requirements.txt

# Create directory structure
RUN mkdir -p /app/shared /app/infra/db/alembic/versions

# Copy shared components (needed for alembic migrations, changes less frequently)
COPY shared/ /app/shared/

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