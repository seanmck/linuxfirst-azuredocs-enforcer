# Dockerfile for MCP server
FROM mcr.microsoft.com/devcontainers/python:1-3.12-bullseye

WORKDIR /app

COPY services/mcp-server/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files explicitly
COPY services/mcp-server/main.py ./

# List files to debug
RUN ls -la /app/

EXPOSE 9000

CMD ["python", "main.py"]
