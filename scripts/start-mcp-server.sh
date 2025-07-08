#!/bin/bash
# Start the MCP server for holistic page bias scoring

if [ ! -f .env ]; then
  echo "No .env file found. Please copy .env.example to .env and fill in your AOAI credentials."
  exit 1
fi

# Load .env file into environment
set -a
source .env
set +a

# Activate venv if exists
if [ -d ".venv" ]; then
  source .venv/bin/activate
fi

# Install MCP server dependencies
pip install -r services/mcp-server/requirements.txt

# Change to services/mcp-server directory and start server
cd services/mcp-server
export PYTHONPATH=$(pwd):$PYTHONPATH

exec uvicorn main:app --reload --host 0.0.0.0 --port 9000
