# DB Migrations

This directory contains Alembic migrations and configuration for the database schema, independent of any specific app or service.

- To generate a migration: `alembic -c alembic.ini revision --autogenerate -m "message"`
- To apply migrations: `alembic -c alembic.ini upgrade head`

The `env.py` is configured to import models from the `webui` package. Adjust as needed if you move models elsewhere.
