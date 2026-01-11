#!/usr/bin/env bash
# scripts/run-tests.sh
# Runs unit tests and integration tests (if infrastructure is available).
#
# Usage:
#   ./scripts/run-tests.sh                    # Run all tests
#   SKIP_INTEGRATION=1 ./scripts/run-tests.sh # Run unit tests only

set -e
set -x

# Activate venv if it exists
if [ -d ".venv" ]; then
  source .venv/bin/activate
fi

export PYTHONPATH=$(pwd):$PYTHONPATH

# =============================================================================
# Unit Tests (no infrastructure required)
# =============================================================================
echo "=== Running Unit Tests ==="
pytest tests/unit/ -v --tb=short

# Check if we should skip integration tests
if [ "$SKIP_INTEGRATION" = "1" ]; then
  echo "=== Skipping Integration Tests (SKIP_INTEGRATION=1) ==="
  echo "=== All Unit Tests Passed ==="
  exit 0
fi

# =============================================================================
# Integration Tests (requires PostgreSQL and RabbitMQ)
# =============================================================================
echo "=== Checking Infrastructure for Integration Tests ==="

# Check PostgreSQL
if ! pg_isready -h localhost -p 5432 -q 2>/dev/null; then
  echo "WARNING: PostgreSQL not available on localhost:5432"
  echo "To run integration tests: docker-compose up -d db rabbitmq"
  echo "Skipping integration tests."
  echo "=== Unit Tests Passed (Integration Tests Skipped) ==="
  exit 0
fi

# Check RabbitMQ
if ! nc -z localhost 5672 2>/dev/null; then
  echo "WARNING: RabbitMQ not available on localhost:5672"
  echo "To run integration tests: docker-compose up -d db rabbitmq"
  echo "Skipping integration tests."
  echo "=== Unit Tests Passed (Integration Tests Skipped) ==="
  exit 0
fi

echo "Infrastructure available. Running integration tests..."

export RABBITMQ_HOST=localhost
export PGSSLMODE=disable

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

# Start web server in background for API tests
echo "Starting web server for integration tests..."
(cd services/web && TEST_MODE=1 uvicorn src.main:app --host 0.0.0.0 --port 8000) &
WEB_PID=$!
CLEANUP_PIDS+=$WEB_PID

# Wait for web server to be ready
echo "Waiting for web server to be ready..."
for i in {1..20}; do
  if curl -sSf http://localhost:8000/ > /dev/null 2>&1; then
    echo "Web server is ready!"
    break
  fi
  echo "Waiting for web server (attempt $i)..."
  sleep 1
done

if ! curl -sSf http://localhost:8000/ > /dev/null 2>&1; then
  echo "Web server failed to start."
  kill $WEB_PID 2>/dev/null || true
  exit 1
fi

# Run integration tests
echo "=== Running Integration Tests ==="
pytest tests/integration/ -v --tb=short || {
  echo "Integration tests failed."
  kill $WEB_PID 2>/dev/null || true
  exit 1
}

# Cleanup
echo "Cleaning up web server..."
kill $WEB_PID 2>/dev/null || true

echo "=== All Tests Passed ==="
