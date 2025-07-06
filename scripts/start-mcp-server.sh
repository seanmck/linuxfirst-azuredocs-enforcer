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

# Change to mcp-server directory
cd mcp-server

# Activate venv if exists
if [ -d "../.venv" ]; then
  source ../.venv/bin/activate
fi

pip install -r requirements.txt

exec uvicorn main:app --reload --host 0.0.0.0 --port 9000
