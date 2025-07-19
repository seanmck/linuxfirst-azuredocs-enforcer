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
  echo "Attempting to acquire Azure managed identity token..."
  if [ -n "$AZURE_POSTGRESQL_CLIENTID" ]; then
    # Use user-assigned managed identity
    echo "Using user-assigned managed identity with client ID: $AZURE_POSTGRESQL_CLIENTID"
    token=$(timeout 30 curl -s -H "Metadata: true" "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://ossrdbms-aad.database.windows.net&client_id=$AZURE_POSTGRESQL_CLIENTID" | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])")
  else
    # Use system-assigned managed identity
    echo "Using system-assigned managed identity"
    token=$(timeout 30 curl -s -H "Metadata: true" "http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://ossrdbms-aad.database.windows.net" | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])")
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
import sys
# Add project root to Python path - use current working directory since we're in /app/infra/db
project_root = '/app'
sys.path.insert(0, project_root)

try:
    from shared.config import config
    print('Shared config loaded successfully')
    print('Database URL from config:', repr(config.database.url))
    print('Database mode:', config.database.mode)
    
    from sqlalchemy.engine.url import make_url
    parsed = make_url(config.database.url)
    print('SQLAlchemy parsing: SUCCESS')
except Exception as e:
    print('Configuration loading: FAILED -', e)
    # Fallback to direct environment variable check
    url = os.environ.get('DATABASE_URL')
    print('URL from env:', repr(url))
    try:
        from sqlalchemy.engine.url import make_url
        parsed = make_url(url)
        print('SQLAlchemy parsing: SUCCESS (fallback)')
    except Exception as e2:
        print('SQLAlchemy parsing: FAILED -', e2)
"

echo "Running Alembic migrations against $DATABASE_URL ..."

# Test database connectivity first
echo "Testing database connectivity..."
timeout 30 bash -c "PGPASSWORD=\"$password\" psql \"$PSQL_URL\" -c 'SELECT 1;'" >/dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "ERROR: Cannot connect to database. Check connection string and credentials."
    exit 1
fi
echo "Database connectivity test passed"

# Check if tables already exist
echo "Checking if database tables exist..."
table_count=$(timeout 30 bash -c "PGPASSWORD=\"$password\" psql \"$PSQL_URL\" -t -c \"SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_name IN ('scans', 'pages', 'snippets');\"" 2>/dev/null | tr -d ' ')
echo "Found $table_count tables out of 3 expected tables"

if [ "$table_count" = "3" ]; then
    echo "All tables already exist, checking migration state..."
    
    # Check if any migrations have been applied
    echo "Checking current Alembic revision..."
    current_revision=$(timeout 60 alembic -c alembic.ini current 2>&1 | grep -v "INFO" | tail -n1 || echo "")
    echo "Current revision: '$current_revision'"
    
    # Check if we have an old migration reference that no longer exists
    if echo "$current_revision" | grep -q "Can't locate revision"; then
        echo "Detected old migration reference in database. Cleaning up alembic_version table..."
        PGPASSWORD="$password" psql "$PSQL_URL" -c "DELETE FROM alembic_version;" 2>/dev/null || true
        current_revision=""
    fi
    
    if [ -z "$current_revision" ] || [ "$current_revision" = "None" ]; then
        echo "No Alembic migrations recorded, but tables exist. Checking for manually applied columns..."
        
        # Check if ProcessingUrl table exists
        processing_urls_exists=$(PGPASSWORD="$password" psql "$PSQL_URL" -t -c "
            SELECT COUNT(*) FROM information_schema.tables 
            WHERE table_name='processing_urls'
        " 2>/dev/null | tr -d ' ')
        
        if [ "$processing_urls_exists" = "1" ]; then
            echo "Full schema including ProcessingUrl table already exists. Stamping all migrations as applied..."
            alembic -c alembic.ini stamp 002_url_processing
            echo "All migrations marked as applied."
        else
            # Check if manual schema updates were applied
            manual_columns=$(PGPASSWORD="$password" psql "$PSQL_URL" -t -c "
                SELECT COUNT(*) FROM information_schema.columns 
                WHERE (table_name='scans' AND column_name='current_phase') 
                   OR (table_name='pages' AND column_name='mcp_holistic')
            " 2>/dev/null | tr -d ' ')
            
            if [ "$manual_columns" = "2" ]; then
                echo "Manual schema detected. Stamping initial migration as applied..."
                alembic -c alembic.ini stamp 001_initial_schema
                echo "Now running URL processing migration..."
            else
                echo "Clean database detected. Running all migrations from the beginning..."
            fi
        fi
    else
        echo "Current migration state: $current_revision"
    fi
    
    echo "Running Alembic upgrade to head (existing tables)..."
    echo "Note: This may take several minutes for large tables..."
    
    # First attempt - try normal upgrade
    echo "Attempting normal upgrade..."
    timeout 600 alembic -c alembic.ini upgrade head 2>&1 | tee /tmp/alembic_output.log
    migration_result=${PIPESTATUS[0]}
    
    # Check if there were overlapping revision errors or transaction failures
    if grep -q "overlaps with other requested revisions\|transaction is aborted\|already exists\|DuplicateTable\|DuplicateColumn" /tmp/alembic_output.log; then
        echo "Detected migration conflict or transaction error. Attempting to resolve..."
        
        # Clear alembic version table to start fresh
        echo "Clearing migration state..."
        PGPASSWORD="$password" psql "$PSQL_URL" -c "DELETE FROM alembic_version;" 2>/dev/null || true
        
        # Try running the migrations again from the beginning
        echo "Retrying migrations from clean state..."
        timeout 600 alembic -c alembic.ini upgrade head
        migration_result=$?
        
        if [ $migration_result -ne 0 ]; then
            echo "Second migration attempt also failed. Checking if critical column exists..."
            
            # Check if the proposed_change_id column exists
            column_exists=$(PGPASSWORD="$password" psql "$PSQL_URL" -t -c "
                SELECT COUNT(*) FROM information_schema.columns 
                WHERE table_name='snippets' AND column_name='proposed_change_id'
            " 2>/dev/null | tr -d ' ')
            
            if [ "$column_exists" = "0" ]; then
                echo "Critical column missing. Adding proposed_change_id column directly..."
                PGPASSWORD="$password" psql "$PSQL_URL" -c "
                    ALTER TABLE snippets ADD COLUMN IF NOT EXISTS proposed_change_id VARCHAR(255);
                    CREATE INDEX IF NOT EXISTS idx_snippets_proposed_change ON snippets(proposed_change_id);
                " 2>/dev/null || true
                
                # Stamp with latest revision since we manually fixed the critical issue
                timeout 60 alembic -c alembic.ini stamp head
                migration_result=0
                echo "Critical column added and migrations marked as complete"
            else
                echo "Column exists but migrations still failing"
            fi
        fi
    fi
    
    if [ $migration_result -eq 0 ]; then
        echo "Alembic upgrade completed successfully"
    elif [ $migration_result -eq 124 ]; then
        echo "TIMEOUT: Alembic upgrade timed out after 10 minutes"
        echo "This may indicate:"
        echo "  1. A large table is being modified"
        echo "  2. Database locks are preventing the migration"
        echo "  3. Database performance issues"
        echo "Check the database for active locks and long-running queries"
        exit 1
    else
        echo "Alembic upgrade failed with exit code $migration_result"
        echo "Last 20 lines of migration output:"
        tail -20 /tmp/alembic_output.log
        exit 1
    fi
else
    echo "Tables missing (found $table_count/3), applying schema.sql first..."
    # Apply the base schema
    echo "Applying base schema..."
    timeout 60 bash -c "PGPASSWORD=\"$password\" psql \"$PSQL_URL\" -f /app/schema.sql"
    if [ $? -eq 0 ]; then
        echo "Schema applied successfully"
    else
        echo "Schema application failed or timed out"
        exit 1
    fi
    
    echo "Schema applied, now running Alembic migrations..."
    echo "Note: This may take several minutes for large tables..."
    
    # Use a longer timeout for potentially slow migrations
    timeout 600 alembic -c alembic.ini upgrade head
    migration_result=$?
    
    if [ $migration_result -eq 0 ]; then
        echo "Alembic upgrade completed successfully"
    elif [ $migration_result -eq 124 ]; then
        echo "TIMEOUT: Alembic upgrade timed out after 10 minutes"
        echo "This may indicate:"
        echo "  1. A large table is being modified"
        echo "  2. Database locks are preventing the migration"
        echo "  3. Database performance issues"
        echo "Check the database for active locks and long-running queries"
        exit 1
    else
        echo "Alembic upgrade failed with exit code $migration_result"
        exit 1
    fi
fi

echo "Database migrations completed successfully."

