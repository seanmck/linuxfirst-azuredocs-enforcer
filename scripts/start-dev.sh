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