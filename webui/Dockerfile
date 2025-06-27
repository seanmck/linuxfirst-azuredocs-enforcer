# Dockerfile for webui (FastAPI)
FROM python:3.12-slim

# Set work directory
WORKDIR /app

# Install dependencies
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && pip install azure-identity

# Copy webui source code
COPY webui ./webui
COPY scorer ./scorer
COPY infra ./infra

# Set PYTHONPATH so 'infra' is importable
ENV PYTHONPATH=/app

# Expose port (adjust if your app uses a different port)
EXPOSE 8000

# Run the web UI (adjust if you use a different entrypoint)
CMD ["uvicorn", "webui.main:app", "--host", "0.0.0.0", "--port", "8000"]
