#!/bin/bash
# Run Alembic migrations against the configured database (e.g., Azure PostgreSQL)
# Usage: ./migrate.sh
# Optionally set DB connection parts as env vars if DATABASE_URL is not set.

set -e

cd "$(dirname "$0")"

echo "Environment variables check:"
echo "AZURE_POSTGRESQL_CONNECTIONSTRING: ${AZURE_POSTGRESQL_CONNECTIONSTRING:-(not set)}"
echo "AZURE_POSTGRESQL_CLIENTID: ${AZURE_POSTGRESQL_CLIENTID:-(not set)}"
echo "DATABASE_URL before processing: ${DATABASE_URL:-(not set)}"

if [ -n "$AZURE_POSTGRESQL_CONNECTIONSTRING" ]; then  
  # Acquire an access token using Azure Instance Metadata Service (IMDS)
  if [ -n "$AZURE_POSTGRESQL_CLIENTID" ]; then
    # Use user-assigned managed identity
    token=$(curl -s -H "Metadata: true" "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://ossrdbms-aad.database.windows.net&client_id=$AZURE_POSTGRESQL_CLIENTID" | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])")
  else
    # Use system-assigned managed identity
    token=$(curl -s -H "Metadata: true" "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://ossrdbms-aad.database.windows.net" | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])")
  fi
  if [ -z "$token" ]; then
    echo "Failed to acquire access token for managed identity."
    exit 1
  fi
  # URL-encode the token for use as a password
  password=$(python3 -c "import urllib.parse, sys; print(urllib.parse.quote_plus(sys.argv[1]))" "$token")
  export PGPASSWORD="$password"

  # Parse connection string and build DATABASE_URL for Alembic
  # Handle libpq format: dbname=... host=... port=... sslmode=... user=...
  user=$(echo "$AZURE_POSTGRESQL_CONNECTIONSTRING" | sed -n 's/.*user=\([^ ]*\).*/\1/p')
  host=$(echo "$AZURE_POSTGRESQL_CONNECTIONSTRING" | sed -n 's/.*host=\([^ ]*\).*/\1/p')
  dbname=$(echo "$AZURE_POSTGRESQL_CONNECTIONSTRING" | sed -n 's/.*dbname=\([^ ]*\).*/\1/p')
  port=$(echo "$AZURE_POSTGRESQL_CONNECTIONSTRING" | sed -n 's/.*port=\([^ ]*\).*/\1/p')
  sslmode=$(echo "$AZURE_POSTGRESQL_CONNECTIONSTRING" | sed -n 's/.*sslmode=\([^ ]*\).*/\1/p')
  # Don't put the token in the URL - use PGPASSWORD environment variable instead
  export DATABASE_URL="postgresql+psycopg2://$user@$host:$port/$dbname?sslmode=$sslmode"
  # Create a separate URL for psql (without the +psycopg2 driver specification)
  export PSQL_URL="postgresql://$user@$host:$port/$dbname?sslmode=$sslmode"
  echo "PGPASSWORD set from managed identity access token."
  echo "Parsed connection details:"
  echo "  User: $user"
  echo "  Host: $host"
  echo "  Port: $port"
  echo "  Database: $dbname"
  echo "  SSL Mode: $sslmode"
else
  echo "AZURE_POSTGRESQL_CONNECTIONSTRING not set, checking for direct DATABASE_URL..."
fi

if [ -z "$DATABASE_URL" ]; then
  echo "ERROR: DATABASE_URL is not set. Please set either DATABASE_URL or AZURE_POSTGRESQL_CONNECTIONSTRING."
  exit 1
fi

# If PSQL_URL wasn't set above (when parsing AZURE_POSTGRESQL_CONNECTIONSTRING), 
# create it from DATABASE_URL by removing the +psycopg2 driver specification
if [ -z "$PSQL_URL" ]; then
  export PSQL_URL=$(echo "$DATABASE_URL" | sed 's/postgresql+psycopg2:/postgresql:/')
fi

echo "Using DATABASE_URL: >$DATABASE_URL<"
echo "Using PSQL_URL: >$PSQL_URL<"
echo "DATABASE_URL length: ${#DATABASE_URL}"

echo "Testing DATABASE_URL with Python:"
python3 -c "
import os
from sqlalchemy.engine.url import make_url
url = os.environ.get('DATABASE_URL')
print('URL from env:', repr(url))
try:
    parsed = make_url(url)
    print('SQLAlchemy parsing: SUCCESS')
except Exception as e:
    print('SQLAlchemy parsing: FAILED -', e)
"

echo "Running Alembic migrations against $DATABASE_URL ..."

# Check if tables already exist
table_count=$(PGPASSWORD="$password" psql "$PSQL_URL" -t -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_name IN ('scans', 'pages', 'snippets');" 2>/dev/null | tr -d ' ')

if [ "$table_count" = "3" ]; then
    echo "All tables already exist, running Alembic migrations..."
    alembic -c alembic.ini upgrade head
else
    echo "Tables missing (found $table_count/3), applying schema.sql first..."
    # Apply the base schema
    PGPASSWORD="$password" psql "$PSQL_URL" -f /app/schema.sql
    
    echo "Schema applied, now running Alembic migrations..."
    alembic -c alembic.ini upgrade head
fi

# Add the mcp_holistic column if it doesn't exist (this is a needed migration)
echo "Checking for required schema updates..."
PGPASSWORD="$password" psql "$PSQL_URL" -c "
DO \$\$ 
BEGIN
    IF NOT EXISTS (
        SELECT column_name FROM information_schema.columns 
        WHERE table_name='pages' AND column_name='mcp_holistic'
    ) THEN
        ALTER TABLE pages ADD COLUMN mcp_holistic JSONB;
        RAISE NOTICE 'Added mcp_holistic column to pages table.';
    ELSE
        RAISE NOTICE 'mcp_holistic column already exists.';
    END IF;
END \$\$;
"

# Add progress tracking columns to scans table
echo "Adding progress tracking columns to scans table..."
PGPASSWORD="$password" psql "$PSQL_URL" -c "
DO \$\$ 
BEGIN
    -- Add current_phase column
    IF NOT EXISTS (
        SELECT column_name FROM information_schema.columns 
        WHERE table_name='scans' AND column_name='current_phase'
    ) THEN
        ALTER TABLE scans ADD COLUMN current_phase VARCHAR;
        RAISE NOTICE 'Added current_phase column to scans table.';
    END IF;

    -- Add current_page_url column
    IF NOT EXISTS (
        SELECT column_name FROM information_schema.columns 
        WHERE table_name='scans' AND column_name='current_page_url'
    ) THEN
        ALTER TABLE scans ADD COLUMN current_page_url VARCHAR;
        RAISE NOTICE 'Added current_page_url column to scans table.';
    END IF;

    -- Add total_pages_found column
    IF NOT EXISTS (
        SELECT column_name FROM information_schema.columns 
        WHERE table_name='scans' AND column_name='total_pages_found'
    ) THEN
        ALTER TABLE scans ADD COLUMN total_pages_found INTEGER DEFAULT 0;
        RAISE NOTICE 'Added total_pages_found column to scans table.';
    END IF;

    -- Add pages_processed column
    IF NOT EXISTS (
        SELECT column_name FROM information_schema.columns 
        WHERE table_name='scans' AND column_name='pages_processed'
    ) THEN
        ALTER TABLE scans ADD COLUMN pages_processed INTEGER DEFAULT 0;
        RAISE NOTICE 'Added pages_processed column to scans table.';
    END IF;

    -- Add snippets_processed column
    IF NOT EXISTS (
        SELECT column_name FROM information_schema.columns 
        WHERE table_name='scans' AND column_name='snippets_processed'
    ) THEN
        ALTER TABLE scans ADD COLUMN snippets_processed INTEGER DEFAULT 0;
        RAISE NOTICE 'Added snippets_processed column to scans table.';
    END IF;

    -- Add phase_progress column
    IF NOT EXISTS (
        SELECT column_name FROM information_schema.columns 
        WHERE table_name='scans' AND column_name='phase_progress'
    ) THEN
        ALTER TABLE scans ADD COLUMN phase_progress JSONB;
        RAISE NOTICE 'Added phase_progress column to scans table.';
    END IF;

    -- Add error_log column
    IF NOT EXISTS (
        SELECT column_name FROM information_schema.columns 
        WHERE table_name='scans' AND column_name='error_log'
    ) THEN
        ALTER TABLE scans ADD COLUMN error_log JSONB;
        RAISE NOTICE 'Added error_log column to scans table.';
    END IF;

    -- Add phase_timestamps column
    IF NOT EXISTS (
        SELECT column_name FROM information_schema.columns 
        WHERE table_name='scans' AND column_name='phase_timestamps'
    ) THEN
        ALTER TABLE scans ADD COLUMN phase_timestamps JSONB;
        RAISE NOTICE 'Added phase_timestamps column to scans table.';
    END IF;

    -- Add estimated_completion column
    IF NOT EXISTS (
        SELECT column_name FROM information_schema.columns 
        WHERE table_name='scans' AND column_name='estimated_completion'
    ) THEN
        ALTER TABLE scans ADD COLUMN estimated_completion TIMESTAMP;
        RAISE NOTICE 'Added estimated_completion column to scans table.';
    END IF;

    -- Add performance_metrics column
    IF NOT EXISTS (
        SELECT column_name FROM information_schema.columns 
        WHERE table_name='scans' AND column_name='performance_metrics'
    ) THEN
        ALTER TABLE scans ADD COLUMN performance_metrics JSONB;
        RAISE NOTICE 'Added performance_metrics column to scans table.';
    END IF;
END \$\$;
"

# Add change detection columns to pages table
echo "Adding change detection columns to pages table..."
PGPASSWORD="$password" psql "$PSQL_URL" -c "
DO \$\$ 
BEGIN
    -- Add content_hash column
    IF NOT EXISTS (
        SELECT column_name FROM information_schema.columns 
        WHERE table_name='pages' AND column_name='content_hash'
    ) THEN
        ALTER TABLE pages ADD COLUMN content_hash VARCHAR;
        RAISE NOTICE 'Added content_hash column to pages table.';
    END IF;

    -- Add last_modified column
    IF NOT EXISTS (
        SELECT column_name FROM information_schema.columns 
        WHERE table_name='pages' AND column_name='last_modified'
    ) THEN
        ALTER TABLE pages ADD COLUMN last_modified TIMESTAMP;
        RAISE NOTICE 'Added last_modified column to pages table.';
    END IF;

    -- Add github_sha column
    IF NOT EXISTS (
        SELECT column_name FROM information_schema.columns 
        WHERE table_name='pages' AND column_name='github_sha'
    ) THEN
        ALTER TABLE pages ADD COLUMN github_sha VARCHAR;
        RAISE NOTICE 'Added github_sha column to pages table.';
    END IF;

    -- Add last_scanned_at column
    IF NOT EXISTS (
        SELECT column_name FROM information_schema.columns 
        WHERE table_name='pages' AND column_name='last_scanned_at'
    ) THEN
        ALTER TABLE pages ADD COLUMN last_scanned_at TIMESTAMP;
        RAISE NOTICE 'Added last_scanned_at column to pages table.';
    END IF;
END \$\$;
"

# Add scan cancellation columns to scans table
echo "Adding scan cancellation columns to scans table..."
PGPASSWORD="$password" psql "$PSQL_URL" -c "
DO \$\$ 
BEGIN
    -- Add cancellation_requested column
    IF NOT EXISTS (
        SELECT column_name FROM information_schema.columns 
        WHERE table_name='scans' AND column_name='cancellation_requested'
    ) THEN
        ALTER TABLE scans ADD COLUMN cancellation_requested BOOLEAN DEFAULT FALSE;
        RAISE NOTICE 'Added cancellation_requested column to scans table.';
    END IF;

    -- Add cancellation_requested_at column
    IF NOT EXISTS (
        SELECT column_name FROM information_schema.columns 
        WHERE table_name='scans' AND column_name='cancellation_requested_at'
    ) THEN
        ALTER TABLE scans ADD COLUMN cancellation_requested_at TIMESTAMP;
        RAISE NOTICE 'Added cancellation_requested_at column to scans table.';
    END IF;

    -- Add cancellation_reason column
    IF NOT EXISTS (
        SELECT column_name FROM information_schema.columns 
        WHERE table_name='scans' AND column_name='cancellation_reason'
    ) THEN
        ALTER TABLE scans ADD COLUMN cancellation_reason VARCHAR;
        RAISE NOTICE 'Added cancellation_reason column to scans table.';
    END IF;
END \$\$;
"

echo "Schema updates completed."
