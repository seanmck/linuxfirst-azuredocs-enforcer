# Dockerfile for web service (FastAPI)
FROM python:3.12-slim

# Set work directory
WORKDIR /app

# Install dependencies
COPY services/web/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && pip install azure-identity

# Copy shared code and packages
COPY shared ./shared
COPY packages ./packages
COPY infra ./infra

# Copy web service code
COPY services/web/src ./web
COPY services/web/static ./static

# Set PYTHONPATH so modules are importable
ENV PYTHONPATH=/app

# Expose port
EXPOSE 8000

# Run the web service
CMD ["uvicorn", "web.main:app", "--host", "0.0.0.0", "--port", "8000"]
