#!/bin/zsh
# scripts/start-dev.sh
# Starts all development services locally: web UI and queue worker.

set -e
set -x

# Ensure a virtual environment is created and activated for local development
if [ ! -d ".venv" ]; then
  echo "Creating a virtual environment..."
  python3 -m venv .venv
fi

# Activate the virtual environment
source .venv/bin/activate

# Always install dependencies for all services
echo "Installing dependencies..."
pip install -r services/web/requirements.txt
pip install -r services/worker/requirements.txt
pip install -r services/mcp-server/requirements.txt

# Set environment variables
export PYTHONPATH=$(pwd):$PYTHONPATH
export RABBITMQ_HOST=localhost

echo "Starting all services..."

# Clean up any existing processes first
echo "Checking for existing processes..."
if lsof -i :8000 -t >/dev/null; then
  echo "Killing processes using port 8000..."
  lsof -i :8000 -t | xargs kill -9
fi

if pgrep -f "queue_worker.py" > /dev/null; then
  echo "Killing existing queue worker processes..."
  pkill -f "queue_worker.py"
fi
if pgrep -f "document_worker.py" > /dev/null; then
  echo "Killing existing document worker processes..."
  pkill -f "document_worker.py"
fi

# Start web UI
./scripts/start-webui.sh &
WEBUI_PID=$!

# Start queue worker
./scripts/start-worker.sh &
WORKER_PID=$!

echo "Web UI running with PID $WEBUI_PID"
echo "Queue worker running with PID $WORKER_PID"

# Wait for user to stop with Ctrl-C
wait 