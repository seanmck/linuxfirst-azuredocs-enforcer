#!/bin/zsh
# scripts/start-webui.sh
# Starts the web UI locally.

set -e
set -x

# Activate venv if it exists
if [ -d ".venv" ]; then
  source .venv/bin/activate
fi

export PYTHONPATH=$(pwd):$PYTHONPATH
export RABBITMQ_HOST=localhost

echo "Checking if the web app is already running on port 8000..."
if lsof -i :8000 -t >/dev/null; then
  echo "Killing processes using port 8000..."
  lsof -i :8000 -t | xargs kill -9
fi

echo "Starting the web app..."
uvicorn webui.main:app --host 0.0.0.0 --port 8000 