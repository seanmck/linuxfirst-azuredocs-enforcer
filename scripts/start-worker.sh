#!/bin/zsh
# scripts/start-worker.sh
# Starts the queue worker locally.

set -e
set -x

# Activate venv if it exists
if [ -d ".venv" ]; then
  source .venv/bin/activate
fi

export PYTHONPATH=$(pwd):$PYTHONPATH
export RABBITMQ_HOST=localhost

echo "Checking for existing queue worker processes..."
if pgrep -f "crawler/queue_worker.py" > /dev/null; then
  echo "Killing existing queue worker processes..."
  pkill -f "crawler/queue_worker.py"
fi

echo "Starting queue worker..."
# Use python -u for unbuffered output
python3 -u crawler/queue_worker.py > queue_worker.log 2>&1 &
QUEUE_WORKER_PID=$!

if ps -p $QUEUE_WORKER_PID > /dev/null; then
  echo "Queue worker started successfully with PID $QUEUE_WORKER_PID. Output is in queue_worker.log."
else
  echo "Failed to start the queue worker."
  exit 1
fi 