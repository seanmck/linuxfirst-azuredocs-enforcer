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

# Copy Alembic migrations and shared models
COPY infra/db /app/infra/db
COPY infra/db/migrate.sh /app/infra/db/migrate.sh
COPY schema.sql /app/schema.sql

# Copy shared models (needed for alembic migrations)
RUN mkdir -p /app/src/shared
COPY src/shared/models.py /app/src/shared/models.py
COPY src/__init__.py /app/src/__init__.py
COPY src/shared/__init__.py /app/src/shared/__init__.py

# (Optional) Copy requirements if you have a separate file, or use the one from webui
COPY webui/requirements.txt /app/requirements.txt

# Install Python dependencies and Alembic
RUN pip install --no-cache-dir -r /app/requirements.txt alembic psycopg2-binary

# Ensure migrate.sh is executable
RUN chmod +x /app/infra/db/migrate.sh

# Set entrypoint to run migrations
ENTRYPOINT ["/app/infra/db/migrate.sh"]