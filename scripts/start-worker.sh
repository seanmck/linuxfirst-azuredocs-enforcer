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

echo "Checking for existing worker processes..."
if pgrep -f "queue_worker.py" > /dev/null; then
  echo "Killing existing queue worker processes..."
  pkill -f "queue_worker.py"
fi
if pgrep -f "document_worker.py" > /dev/null; then
  echo "Killing existing document worker processes..."
  pkill -f "document_worker.py"
fi

echo "Starting refactored queue worker with progress tracking..."
# Use python -u for unbuffered output - using the new refactored queue worker
(cd services/worker && python3 -u src/queue_worker.py) > queue_worker.log 2>&1 &
QUEUE_WORKER_PID=$!

echo "Starting document worker for processing queued documents..."
# Start document worker to process documents from doc_processing queue
(cd services/worker && python3 -u src/document_worker.py) > document_worker.log 2>&1 &
DOCUMENT_WORKER_PID=$!

# Check if both workers started successfully
if ps -p $QUEUE_WORKER_PID > /dev/null; then
  echo "Queue worker started successfully with PID $QUEUE_WORKER_PID. Output is in queue_worker.log."
else
  echo "Failed to start the queue worker."
  exit 1
fi

if ps -p $DOCUMENT_WORKER_PID > /dev/null; then
  echo "Document worker started successfully with PID $DOCUMENT_WORKER_PID. Output is in document_worker.log."
else
  echo "Failed to start the document worker."
  echo "Queue worker is still running with PID $QUEUE_WORKER_PID"
  exit 1
fi

echo "Both workers are running:"
echo "  Queue Worker PID: $QUEUE_WORKER_PID (logs: queue_worker.log)"
echo "  Document Worker PID: $DOCUMENT_WORKER_PID (logs: document_worker.log)" 