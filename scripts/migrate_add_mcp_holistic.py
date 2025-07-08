"""
Migration script to add mcp_holistic column to pages table (Postgres version).
"""
from sqlalchemy import create_engine, text
import os

# Use DATABASE_URL from environment or default to localhost for host execution
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://azuredocs_user:azuredocs_pass@localhost:5432/azuredocs')
engine = create_engine(DATABASE_URL)
print(f"Connecting to DB: {engine.url}")

with engine.connect() as conn:
    # Print current database and server address
    db_info = conn.execute(text("SELECT current_database(), inet_server_addr()::text")).fetchone()
    print(f"Connected to database: {db_info[0]}, server address: {db_info[1]}")
    # Check if column exists
    result = conn.execute(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name='pages' AND column_name='mcp_holistic';
    """))
    if not result.fetchone():
        conn.execute(text('ALTER TABLE pages ADD COLUMN mcp_holistic JSONB'))
        print("Added mcp_holistic column to pages table.")
    else:
        print("mcp_holistic column already exists.")
