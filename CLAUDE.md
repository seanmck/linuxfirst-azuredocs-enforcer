# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A microservices-based Python application that scans Azure documentation repositories (via GitHub) to detect Windows bias in code snippets. Uses heuristics and Azure OpenAI LLM scoring to ensure cross-platform documentation.

## Development Commands

### Local Development
```bash
./scripts/start-dev.sh            # Setup venv, start infra (db, rabbitmq), run all services
```

**Note:** When running services manually (not via start-dev.sh), set PYTHONPATH first:
```bash
export PYTHONPATH=$(pwd):$PYTHONPATH
```

### Running Individual Services
```bash
# Web UI (port 8000)
cd services/web && python src/main.py

# Worker (requires RabbitMQ)
cd services/worker && python src/queue_worker.py

# Bias Scoring Service (port 9000)
cd services/bias-scoring-service && python main.py
```

### Docker Compose
```bash
docker-compose up                 # All services
docker-compose up web             # Web UI only (port 8010 -> 8000)
docker-compose logs -f web        # Follow web service logs
```

### Database Migrations
```bash
cd infra/db
alembic -c alembic.ini revision --autogenerate -m "description"
alembic -c alembic.ini upgrade head
```

### Testing
```bash
./scripts/run-tests.sh            # Integration tests (starts web + worker)
```

## Architecture

### Three Microservices
1. **Web Service** (`services/web/`): FastAPI dashboard and REST API (port 8000)
2. **Worker Service** (`services/worker/`): Background job processor consuming from RabbitMQ
3. **Bias Scoring Service** (`services/bias-scoring-service/`): Azure OpenAI integration (port 9000)

### Shared Code
- `shared/models.py`: SQLAlchemy models (Scan, Page, Snippet, BiasSnapshot, etc.)
- `shared/config.py`: Centralized configuration with `Config.from_env()`
- `shared/utils/`: Database helpers, logging, metrics, URL parsing

### Legacy Packages (being phased out)
- `packages/scorer/llm_client.py`: Azure OpenAI wrapper with rate limiting
- `packages/scorer/heuristics.py`: Rule-based Windows bias detection
- `packages/extractor/parser.py`: HTML/Markdown snippet extraction

### Communication
- **Database**: PostgreSQL via SQLAlchemy 2.0+
- **Message Queue**: RabbitMQ for job distribution
- **Cache**: Redis for session/state caching

### Web Routes Structure
Routes are in `services/web/src/routes/`:
- `admin.py`: Admin dashboard endpoints
- `scan.py`: Scan management
- `llm.py`: LLM scoring endpoints
- `docpage.py`: Document page display
- `docset.py`: Documentation set queries
- `auth.py`: GitHub OAuth authentication
- `feedback.py`: User feedback collection
- `websocket.py`: Real-time scan progress

### Service Ports
- **Web UI**: 8000 (local), 8010 (Docker host → 8000 container)
- **Bias Scoring**: 9000
- **PostgreSQL**: 5432
- **RabbitMQ**: 5672 (AMQP), 15672 (management UI)

## Key Environment Variables

```bash
# Database
DATABASE_URL=postgresql://user:pass@host:5432/dbname

# Azure OpenAI (optional - falls back to heuristics)
AZURE_OPENAI_KEY=your-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-35-turbo
AZURE_OPENAI_CLIENTID=client-id  # For managed identity (alternative to API key)
AZURE_OPENAI_RPM=60               # Rate limit requests per minute
LLM_BATCH_SIZE=5                  # Snippets per LLM request

# RabbitMQ
RABBITMQ_HOST=localhost

# GitHub OAuth (optional)
GITHUB_CLIENT_ID=xxx
GITHUB_CLIENT_SECRET=xxx
```

## Configuration Pattern

All configuration uses dataclasses in `shared/config.py`:
```python
from shared.config import config

# Access config sections
config.database.url
config.azure_openai.is_available
config.rabbitmq.host
```

Repository list is in `config/repos.yaml`.

## Database Models

Key tables in `shared/models.py`:
- **Scan**: Scan execution with progress tracking, phase timestamps, cancellation support
- **Page**: Individual documentation pages with content hashing, processing locks
- **Snippet**: Code snippets with LLM scores
- **FileProcessingHistory**: Track processed files with commit SHA for incremental scans

## Kubernetes Deployment

Uses Kustomize with base + overlays:
```
infra/k8s/
├── base/           # Base K8s resources
└── overlays/
    ├── dev/
    ├── test/
    └── prod/
```

KEDA autoscaling is configured for workers based on RabbitMQ queue depth.
