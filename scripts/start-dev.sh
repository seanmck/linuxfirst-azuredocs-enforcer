#!/bin/zsh
# scripts/start-dev.sh
# Starts all development services locally: web UI, queue worker, and bias-scoring service.

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
pip install -r services/bias-scoring-service/requirements.txt

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

if lsof -i :9000 -t >/dev/null; then
  echo "Killing processes using port 9000..."
  lsof -i :9000 -t | xargs kill -9
fi

echo "Killing all existing worker processes..."
pkill -f "queue_worker.py" || true
pkill -f "document_worker.py" || true
pkill -f "bias-scoring-service" || true
pkill -f "uvicorn.*main:app" || true

# Wait a moment for processes to terminate
sleep 2

# Clear Python cache to ensure fresh code is loaded
echo "Clearing Python cache..."
find . -name "*.pyc" -delete 2>/dev/null || true
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

# Start web UI
./scripts/start-webui.sh &
WEBUI_PID=$!

# Start queue worker
./scripts/start-worker.sh &
WORKER_PID=$!

# Start bias-scoring service
./scripts/start-bias-scoring-service.sh &
SCORING_PID=$!

echo "Web UI running with PID $WEBUI_PID"
echo "Queue worker running with PID $WORKER_PID"
echo "Bias-scoring service running with PID $SCORING_PID"

# Wait for user to stop with Ctrl-C
wait 