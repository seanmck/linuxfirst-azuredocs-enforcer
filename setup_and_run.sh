#!/bin/zsh
# setup_and_run.sh
# Script to set up a Python virtual environment, install dependencies, and run the orchestrator or web UI.

set -e
set -x  # Enable debug tracing

# --- Trap for cleanup on Ctrl-C or SIGTERM ---
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

# Check if --docker switch is passed
USE_DOCKER=false
if [[ "$1" == "--docker" ]]; then
  USE_DOCKER=true
  shift
fi

# Check if --wipe switch is passed
WIPE_DATA=false
if [[ "$1" == "--wipe" ]]; then
  WIPE_DATA=true
  shift
fi

# Check if --test switch is passed
TEST_MODE=false
if [[ "$1" == "--test" ]]; then
  TEST_MODE=true
  shift
fi

# Default to deploying the web UI if no argument is provided
if [[ -z "$1" && "$TEST_MODE" == false ]]; then
  set -- "--web"
fi

# Wipe database and RabbitMQ queues if --wipe is specified
if $WIPE_DATA; then
  echo "Wiping database and RabbitMQ queues..."
  
  if $USE_DOCKER; then
    # Get container names
    DB_CONTAINER=$(docker-compose ps -q db)
    RABBITMQ_CONTAINER=$(docker-compose ps -q rabbitmq)
    
    if [ -n "$DB_CONTAINER" ]; then
      echo "Clearing database..."
      docker exec "$DB_CONTAINER" psql "postgresql://azuredocs_user:azuredocs_pass@localhost:5432/azuredocs?sslmode=disable" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public; GRANT ALL ON SCHEMA public TO azuredocs_user; GRANT ALL ON SCHEMA public TO public;"
    fi
    
    if [ -n "$RABBITMQ_CONTAINER" ]; then
      echo "Clearing RabbitMQ queues..."
      docker exec "$RABBITMQ_CONTAINER" rabbitmqctl purge_queue scan_queue || true
      docker exec "$RABBITMQ_CONTAINER" rabbitmqctl purge_queue result_queue || true
    fi
  else
    # Local environment
    echo "Clearing database..."
    psql "postgresql://azuredocs_user:azuredocs_pass@localhost:5432/azuredocs?sslmode=disable" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public; GRANT ALL ON SCHEMA public TO azuredocs_user; GRANT ALL ON SCHEMA public TO public;" || true
    
    echo "Clearing RabbitMQ queues..."
    if command -v rabbitmqctl &> /dev/null; then
      rabbitmqctl purge_queue scan_queue || true
      rabbitmqctl purge_queue result_queue || true
    else
      echo "Note: rabbitmqctl not available locally. RabbitMQ queues will be cleared when Docker containers restart."
    fi
  fi
  
  echo "Data wipe completed."
fi

# Shut down Docker containers for web UI and scanner if --docker is not specified
if ! $USE_DOCKER; then
  echo "Stopping Docker containers for web UI and scanner to avoid port conflicts..."
  docker-compose stop webui scanner || true
fi

if $USE_DOCKER; then
  echo "Running services in Docker containers..."
  # Force rebuild of Docker images before starting services
  echo "Rebuilding Docker images..."
  docker-compose build
  docker-compose up -d
  sleep 5

  # Dynamically fetch container names to ensure correct interaction
  DB_CONTAINER=$(docker-compose ps -q db)
  WEBUI_CONTAINER=$(docker-compose ps -q webui)

  if [ -z "$DB_CONTAINER" ] || [ -z "$WEBUI_CONTAINER" ]; then
    echo "Error: Required containers are not running. Please check docker-compose logs."
    exit 1
  fi

  if ! docker exec "$DB_CONTAINER" psql "postgresql://azuredocs_user:azuredocs_pass@localhost:5432/azuredocs?sslmode=disable" -c "\\dt" | grep -q 'scans'; then
    echo "Initializing database tables..."
    docker exec "$WEBUI_CONTAINER" python webui/create_db.py
  fi

  if [[ "$1" == "--web" ]]; then
    echo "Starting the web UI in Docker..."
    docker exec -d "$WEBUI_CONTAINER" uvicorn webui.main:app --host 0.0.0.0 --port 8000
  else
    echo "Running orchestrator in Docker is not supported."
    exit 1
  fi
else
  echo "Running services locally..."
  
  # Ensure a virtual environment is created and activated for local development
  if [ ! -d ".venv" ]; then
    echo "Creating a virtual environment..."
    python3 -m venv .venv
  fi

  # Activate the virtual environment
  source .venv/bin/activate

  # Always install dependencies
  echo "Installing dependencies..."
  pip install -r requirements.txt

  # Ensure DB tables exist (auto-create if missing)
  if ! psql "postgresql://azuredocs_user:azuredocs_pass@localhost:5432/azuredocs?sslmode=disable" -c "\\dt" | grep -q 'scans'; then
    echo "Initializing database tables locally..."
    python webui/create_db.py
  fi

  # Ensure uvicorn is installed in the virtual environment
  if ! command -v uvicorn &> /dev/null; then
    echo "uvicorn not found in virtual environment. Installing..."
    pip install uvicorn
  fi

  echo "Setting PYTHONPATH to include the project root..."
  export PYTHONPATH=$(pwd):$PYTHONPATH
  echo "PYTHONPATH set to $PYTHONPATH"

  echo "Setting RABBITMQ_HOST to localhost..."
  export RABBITMQ_HOST=localhost
  echo "RABBITMQ_HOST set to $RABBITMQ_HOST"

  echo "Checking for existing queue worker processes..."
  if pgrep -f "crawler/queue_worker.py" > /dev/null; then
    echo "Killing existing queue worker processes..."
    pkill -f "crawler/queue_worker.py"
    echo "Existing queue worker processes terminated."
  else
    echo "No existing queue worker processes found."
  fi

  if $TEST_MODE; then
    echo "[TEST MODE] Starting web server in background..."
    # Kill any process using port 8000
    if lsof -i :8000 -t >/dev/null; then
      echo "Killing processes using port 8000..."
      lsof -i :8000 -t | xargs kill -9
      echo "Processes on port 8000 killed."
    else
      echo "No process is using port 8000."
    fi
    # Pass TEST_MODE=1 to the web UI process
    TEST_MODE=1 uvicorn webui.main:app --host 0.0.0.0 --port 8000 &
    WEB_PID=$!
    CLEANUP_PIDS+=$WEB_PID
    echo "Web server started with PID $WEB_PID. Waiting for it to be ready..."
    # Wait for port 8000 to be ready
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
    python3 crawler/queue_worker.py &
    WORKER_PID=$!
    CLEANUP_PIDS+=$WORKER_PID
    echo "[TEST MODE] Queue worker started with PID $WORKER_PID."
    # Wait for the worker to finish (or add your own test logic here)
    wait $WORKER_PID
    echo "[TEST MODE] Cleaning up web server..."
    kill $WEB_PID || true
    echo "[TEST MODE] Done."
    exit 0
  fi

  if [[ "$1" == "--web" ]]; then
    echo "Checking if the web app is already running..."
    # Kill any process using port 8000
    if lsof -i :8000 -t >/dev/null; then
      echo "Killing processes using port 8000..."
      lsof -i :8000 -t | xargs kill -9
      echo "Processes on port 8000 killed."
    else
      echo "No process is using port 8000."
    fi
    echo "Reached web server startup"
    echo "Starting the web app..."
    uvicorn webui.main:app --host 0.0.0.0 --port 8000
    echo "Web app started."
  else
    echo "Running queue worker..."
    python3 crawler/queue_worker.py > queue_worker.log 2>&1 &
    QUEUE_WORKER_PID=$!
    if ps -p $QUEUE_WORKER_PID > /dev/null; then
      echo "Queue worker started successfully with PID $QUEUE_WORKER_PID. Output is in queue_worker.log."
    else
      echo "Failed to start the queue worker."
      exit 1
    fi
  fi
fi
