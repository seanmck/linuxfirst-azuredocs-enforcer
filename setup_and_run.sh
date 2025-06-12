#!/bin/zsh
# setup_and_run.sh
# Script to set up a Python virtual environment, install dependencies, and run the orchestrator or web UI.

set -e

# 0. Start Postgres if not running
if ! docker ps | grep -q 'linuxfirst-azuredocs-enforcer_db'; then
  echo "Starting Postgres via docker-compose..."
  docker-compose up -d db
  sleep 3
fi

# 0. Optionally wipe results if --wipe is passed
if [[ "$1" == "--wipe" ]]; then
  echo "Wiping previous results in results/ ..."
  rm -f results/flagged_snippets.json results/flagged_snippets.csv results/scan_progress.json
  shift
fi

# 1. Create virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

# 2. Activate virtual environment
source .venv/bin/activate

# 3. Install dependencies (suppress 'already satisfied' and other pip output except errors)
pip install --upgrade pip > /dev/null 2>&1
pip install -r requirements.txt > /dev/null 2>&1

# 3.1. Ensure python-multipart is installed for FastAPI form support
pip install python-multipart > /dev/null 2>&1

# 3.2. Ensure DB tables exist (auto-create if missing)
if ! psql "postgresql://azuredocs_user:azuredocs_pass@localhost:5432/azuredocs?sslmode=disable" -c "\dt" | grep -q 'scans'; then
  echo "Initializing database tables..."
  python webui/create_db.py
fi

# 3.5. Only show LLM reminder if any required env var is missing
if [[ -z "$AZURE_OPENAI_KEY" || -z "$AZURE_OPENAI_ENDPOINT" || -z "$AZURE_OPENAI_DEPLOYMENT" ]]; then
  echo "\nIf you want to use LLM scoring, make sure to set your Azure OpenAI key, endpoint, and deployment:"
  echo "  export AZURE_OPENAI_KEY=your-key-here"
  echo "  export AZURE_OPENAI_ENDPOINT=https://<your-resource-name>.openai.azure.com/"
  echo "  export AZURE_OPENAI_DEPLOYMENT=your-deployment-name"
fi

# 4. Run orchestrator or web UI based on argument
if [[ "$1" == "--web" ]]; then
  echo "Starting web UI at http://localhost:8000 ..."
  uvicorn webui.main:app --reload
else
  python orchestrator.py "$@"
fi
