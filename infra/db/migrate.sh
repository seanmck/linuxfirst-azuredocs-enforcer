#!/bin/bash
# Run Alembic migrations against the configured database (e.g., Azure PostgreSQL)
# Usage: ./migrate.sh
# Optionally set DB connection parts as env vars if DATABASE_URL is not set.

set -e

cd "$(dirname "$0")"

if [ -z "$DATABASE_URL" ]; then
  # Try to build DATABASE_URL from components
  if [ -n "$DB_USER" ] && [ -n "$DB_PASS" ] && [ -n "$DB_HOST" ] && [ -n "$DB_NAME" ]; then
    export DATABASE_URL='postgresql://$DB_USER:$DB_PASS@$DB_HOST:5432/$DB_NAME'
    echo "DATABASE_URL built from components: $DATABASE_URL"
  else
    echo "Error: DATABASE_URL environment variable is not set."
    echo "Set DATABASE_URL, or set DB_USER, DB_PASS, DB_HOST, and DB_NAME."
    echo "Example: export DB_USER=user DB_PASS=pass DB_HOST=host DB_NAME=dbname"
    exit 1
  fi
fi

echo "Using DATABASE_URL: >$DATABASE_URL<"

echo "Running Alembic migrations against $DATABASE_URL ..."
alembic -c alembic.ini upgrade head
