# Dockerfile for web service (FastAPI)
FROM python:3.12-slim

# Set work directory
WORKDIR /app

# Install dependencies
COPY services/web/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && pip install azure-identity

# Copy shared code, packages, and config
COPY shared ./shared
COPY packages ./packages
COPY infra ./infra
COPY config ./config

# Copy web service code
COPY services/web/src ./web
COPY services/web/static ./web/static

# Set PYTHONPATH so modules are importable
ENV PYTHONPATH=/app

# Change working directory to web service directory to match local development
WORKDIR /app/web

# Expose port
EXPOSE 8000

# Run the web service (now from web directory, so we can use relative imports)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
