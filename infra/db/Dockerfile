FROM python:3.12-slim

# Set workdir
WORKDIR /app

# Install system dependencies (if needed)
RUN apt-get update && apt-get install -y gcc libpq-dev && rm -rf /var/lib/apt/lists/*

# Copy Alembic migrations and shared models
COPY infra/db /app/infra/db
COPY infra/db/migrate.sh /app/infra/db/migrate.sh

# (Optional) Copy requirements if you have a separate file, or use the one from webui
COPY webui/requirements.txt /app/requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir -r /app/requirements.txt

# Ensure migrate.sh is executable
RUN chmod +x /app/infra/db/migrate.sh

# Set entrypoint to run migrations
ENTRYPOINT ["/app/infra/db/migrate.sh"]