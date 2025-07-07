FROM mcr.microsoft.com/devcontainers/python:1-3.12-bullseye

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        git \
        gcc \
        && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements from worker service and install Python dependencies
COPY services/worker/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared code and packages
COPY shared /app/shared
COPY packages /app/packages

# Copy worker service code
COPY services/worker/src /app/worker

# Copy necessary scripts
COPY scripts /app/scripts

# Create a non-root user
RUN useradd --create-home --shell /bin/bash app && \
    chown -R app:app /app
USER app

# Set Python path
ENV PYTHONPATH=/app

# Default command
CMD ["python", "worker/queue_worker.py"]
