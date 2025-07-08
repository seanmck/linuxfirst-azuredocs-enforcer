#!/bin/bash
# Script to dump local Postgres schema and import it into the Dockerized Postgres DB

set -e

# Local DB credentials
LOCAL_DB_USER="azuredocs_user"
LOCAL_DB_PASS="azuredocs_pass"
LOCAL_DB_NAME="azuredocs"
LOCAL_DB_HOST="localhost"

# Docker Compose service and DB credentials
DOCKER_DB_SERVICE="db"
DOCKER_DB_USER="azuredocs_user"
DOCKER_DB_NAME="azuredocs"

# 1. Dump local schema
export PGPASSWORD="$LOCAL_DB_PASS"
echo "Dumping local schema..."
pg_dump -h "$LOCAL_DB_HOST" -U "$LOCAL_DB_USER" -d "$LOCAL_DB_NAME" --schema-only > schema.sql

# 2. Copy schema.sql into the db container
echo "Copying schema.sql into the db container..."
docker compose cp schema.sql $DOCKER_DB_SERVICE:/schema.sql

# 3. Import schema into Dockerized Postgres
echo "Importing schema into Dockerized Postgres..."
docker compose exec -T $DOCKER_DB_SERVICE psql -U "$DOCKER_DB_USER" -d "$DOCKER_DB_NAME" -f /schema.sql

echo "Schema import complete."
