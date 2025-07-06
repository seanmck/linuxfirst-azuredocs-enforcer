#!/bin/zsh
# scripts/start-worker.sh
# Starts the queue worker locally.

set -e
set -x

# Activate venv if it exists
if [ -d ".venv" ]; then
  source .venv/bin/activate
fi

# Load environment variables from .env file if it exists
if [ -f ".env" ]; then
  echo "Loading environment variables from .env file..."
  export $(grep -v '^#' .env | xargs)
fi

export PYTHONPATH=$(pwd):$PYTHONPATH
export RABBITMQ_HOST=localhost

# GitHub token for repository access (set this if you want GitHub scan functionality)
if [ -n "$GITHUB_TOKEN" ]; then
  export GITHUB_TOKEN="$GITHUB_TOKEN"
  echo "GitHub token found - GitHub scanning enabled"
else
  echo "Warning: GITHUB_TOKEN not set - GitHub scanning will be disabled"
fi

echo "Checking for existing queue worker processes..."
if pgrep -f "queue_worker.py" > /dev/null; then
  echo "Killing existing queue worker processes..."
  pkill -f "queue_worker.py"
fi

echo "Starting refactored queue worker with progress tracking..."
# Use python -u for unbuffered output - using the new refactored queue worker
python3 -u src/application/queue_worker.py > queue_worker.log 2>&1 &
QUEUE_WORKER_PID=$!

if ps -p $QUEUE_WORKER_PID > /dev/null; then
  echo "Queue worker started successfully with PID $QUEUE_WORKER_PID. Output is in queue_worker.log."
else
  echo "Failed to start the queue worker."
  exit 1
fi 