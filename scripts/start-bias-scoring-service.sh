#!/bin/bash
# Start the Bias Scoring Service for holistic page bias scoring

if [ ! -f .env ]; then
  echo "No .env file found. Please copy .env.example to .env and fill in your AOAI credentials."
  exit 1
fi

# Load .env file into environment
set -a
source .env
set +a

# Ensure a virtual environment is created and activated for local development
if [ ! -d ".venv" ]; then
  echo "Creating a virtual environment..."
  python3 -m venv .venv
fi

# Activate venv if exists
if [ -d ".venv" ]; then
  source .venv/bin/activate
fi

# Install Bias Scoring Service dependencies
pip install -r services/bias-scoring-service/requirements.txt

# Change to services/bias-scoring-service directory and start server
cd services/bias-scoring-service
export PYTHONPATH=$(pwd):$PYTHONPATH

exec uvicorn main:app --reload --host 0.0.0.0 --port 9000
