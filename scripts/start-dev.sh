#!/bin/bash
# scripts/start-dev.sh
# Starts all development services in Docker containers with hot-reloading.
#
# Prerequisites:
#   - Docker and docker-compose installed
#   - docker-compose.override.yml exists (copy from docker-compose.override.yml.example)
#   - .env file exists with required environment variables (optional)
#
# Usage:
#   ./scripts/start-dev.sh
#
# Services started:
#   - db (PostgreSQL on port 5432)
#   - rabbitmq (ports 5672, 15672)
#   - web (port 8010 -> 8000, with hot-reload)
#   - worker (queue_worker with hot-reload)
#   - document_worker (with hot-reload)
#   - bias_scoring_service (port 9000, with hot-reload)
#
# Press Ctrl+C to stop all services.

set -e

cd "$(dirname "$0")/.."

# Ensure .env file exists (docker-compose requires it if referenced in env_file)
if [ ! -f ".env" ]; then
  echo "Creating empty .env file..."
  echo "# Add your environment variables here" > .env
  echo "# See .env.example for available options" >> .env
fi

# Check for docker-compose.override.yml
if [ ! -f "docker-compose.override.yml" ]; then
  echo "docker-compose.override.yml not found."
  echo "Copying from docker-compose.override.yml.example..."
  cp docker-compose.override.yml.example docker-compose.override.yml
fi

# Stop any existing containers to free up ports
docker-compose down 2>/dev/null || true

# Stop any containers using our required ports (from other projects or standalone)
for port in 5432 5672 15672 8010 9000; do
  container_id=$(docker ps -q --filter "publish=$port")
  if [ -n "$container_id" ]; then
    echo "Stopping container using port $port..."
    docker stop $container_id 2>/dev/null || true
  fi
done

echo "Building and starting all services..."
echo "Web UI will be available at: http://localhost:8010"
echo "RabbitMQ management: http://localhost:15672 (guest/guest)"
echo ""
echo "Press Ctrl+C to stop all services."
echo ""

# Run database migrations first (db-migrate depends on db being healthy)
echo "Running database migrations..."
docker-compose up --build db-migrate

# Start all services (excluding db-migrate which already ran)
docker-compose up --build
