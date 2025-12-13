#!/bin/bash
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
pip install -r services/bias-scoring-service/requirements.txt

# Ensure infrastructure services (PostgreSQL and RabbitMQ) are accessible
echo "Checking infrastructure services..."

# Check if PostgreSQL is accessible on localhost:5432
if pg_isready -h localhost -p 5432 -U azuredocs_user -d azuredocs >/dev/null 2>&1; then
  echo "PostgreSQL is already accessible on localhost:5432"
elif docker-compose ps db --status running -q 2>/dev/null | grep -q .; then
  echo "PostgreSQL container is running, waiting for it to be ready..."
else
  echo "Starting PostgreSQL via Docker..."
  docker-compose up -d db
fi

# Check if RabbitMQ is accessible on localhost:5672
if nc -z localhost 5672 2>/dev/null; then
  echo "RabbitMQ is already accessible on localhost:5672"
elif docker-compose ps rabbitmq --status running -q 2>/dev/null | grep -q .; then
  echo "RabbitMQ container is running, waiting for it to be ready..."
else
  echo "Starting RabbitMQ via Docker..."
  docker-compose up -d rabbitmq
fi

# Wait for services to be ready
echo "Waiting for infrastructure services to be ready..."
until pg_isready -h localhost -p 5432 -U azuredocs_user -d azuredocs >/dev/null 2>&1; do
  echo "Waiting for PostgreSQL..."
  sleep 2
done
until nc -z localhost 5672 2>/dev/null; do
  echo "Waiting for RabbitMQ..."
  sleep 2
done
echo "Infrastructure services are ready."

# Load environment variables from .env file if it exists
if [ -f ".env" ]; then
  echo "Loading environment variables from .env file..."
  set -a
  source .env
  set +a
fi

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
if lsof -i :9000 -t >/dev/null 2>&1; then
  echo "Killing processes using port 9000 (bias scoring service)..."
  lsof -i :9000 -t | xargs kill -9
fi

# Start web UI
./scripts/start-webui.sh &
WEBUI_PID=$!

# Start queue worker
./scripts/start-worker.sh &
WORKER_PID=$!

# Start bias scoring service
echo "Starting bias scoring service..."
(cd services/bias-scoring-service && uvicorn main:app --host 0.0.0.0 --port 9000) > bias_scoring_service.log 2>&1 &
BIAS_SCORING_PID=$!

echo "Web UI running with PID $WEBUI_PID"
echo "Queue worker running with PID $WORKER_PID"
echo "Bias scoring service running with PID $BIAS_SCORING_PID (logs: bias_scoring_service.log)"

# Wait for user to stop with Ctrl-C
wait 