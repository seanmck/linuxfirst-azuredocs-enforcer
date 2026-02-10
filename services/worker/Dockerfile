FROM mcr.microsoft.com/devcontainers/python:1-3.12-bullseye

# Set working directory
WORKDIR /app

# Install system dependencies
RUN rm -f /etc/apt/sources.list.d/yarn.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        git \
        gcc \
        && \
    rm -rf /var/lib/apt/lists/*

# Copy requirements from worker service and install Python dependencies
COPY services/worker/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared code, packages, and config (less likely to change)
COPY shared /app/shared
COPY packages /app/packages
COPY config /app/config

# Copy necessary scripts (only specific ones needed by worker)
COPY scripts/enqueue_github_scan.py /app/scripts/

# Copy worker service code (most likely to change - keep last)
COPY services/worker/src /app/worker
COPY scripts/update_bias_snapshots.py /app/scripts/

# Create a non-root user
RUN useradd --create-home --shell /bin/bash app && \
    chown -R app:app /app
USER app

# Set Python path
ENV PYTHONPATH=/app

# Default command
CMD ["python", "worker/queue_worker.py"]
