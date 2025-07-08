#!/bin/zsh
# scripts/run-tests.sh
# Sets up the test environment and runs integration tests.

set -e
set -x

CLEANUP_PIDS=()
cleanup() {
  echo "[CLEANUP] Caught signal, cleaning up background processes..."
  for pid in $CLEANUP_PIDS; do
    if kill -0 $pid 2>/dev/null; then
      echo "[CLEANUP] Killing process $pid"
      kill $pid || true
    fi
  done
  exit 1
}
trap cleanup INT TERM

# Activate venv if it exists
if [ -d ".venv" ]; then
  source .venv/bin/activate
fi

export PYTHONPATH=$(pwd):$PYTHONPATH
export RABBITMQ_HOST=localhost

echo "[TEST MODE] Starting web server in background..."
(cd services/web && TEST_MODE=1 uvicorn src.main:app --host 0.0.0.0 --port 8000) &
WEB_PID=$!
CLEANUP_PIDS+=$WEB_PID

echo "Web server started with PID $WEB_PID. Waiting for it to be ready..."
for i in {1..20}; do
  if curl -sSf http://localhost:8000/ > /dev/null; then
    echo "Web server is up and responding to HTTP requests!"
    break
  fi
  echo "Waiting for web server HTTP response (attempt $i)..."
  sleep 1
done

if ! curl -sSf http://localhost:8000/ > /dev/null; then
  echo "Web server failed to start or respond to HTTP requests."
  kill $WEB_PID || true
  exit 1
fi

echo "[TEST MODE] Running test_manual_github_scan.py..."
python3 tests/test_manual_github_scan.py

echo "[TEST MODE] Starting queue worker..."
(cd services/worker && python3 src/queue_worker.py) &
WORKER_PID=$!
CLEANUP_PIDS+=$WORKER_PID
echo "[TEST MODE] Queue worker started with PID $WORKER_PID."

wait $WORKER_PID
echo "[TEST MODE] Cleaning up web server..."
kill $WEB_PID || true
echo "[TEST MODE] Done." 