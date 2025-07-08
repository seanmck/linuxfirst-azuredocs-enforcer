#!/bin/zsh
# scripts/manage-data.sh
# Wipes database and RabbitMQ queues.

set -e
set -x

USE_DOCKER=false
if [[ "$1" == "--docker" ]]; then
  USE_DOCKER=true
fi

if $USE_DOCKER; then
  echo "Wiping data in Docker containers..."
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
  echo "Wiping local data..."
  echo "Clearing database..."
  psql "postgresql://azuredocs_user:azuredocs_pass@localhost:5432/azuredocs?sslmode=disable" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public; GRANT ALL ON SCHEMA public TO azuredocs_user; GRANT ALL ON SCHEMA public TO public;" || true
  
  echo "Clearing RabbitMQ queues..."
  if command -v rabbitmqctl &> /dev/null; then
    rabbitmqctl purge_queue scan_queue || true
    rabbitmqctl purge_queue result_queue || true
  else
    echo "Note: rabbitmqctl not found locally. Assuming Docker-based RabbitMQ."
  fi
fi

echo "Data wipe completed." 