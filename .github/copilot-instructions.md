# GitHub Copilot Instructions

This file provides guidance to GitHub Copilot when working with the Linux-first Azure Docs Enforcer project.

## Project Overview

A microservices-based Python application that scans Azure documentation repositories to detect Windows bias in code snippets. The system uses heuristics and Azure OpenAI LLM scoring to ensure cross-platform documentation.

## Technology Stack

- **Language**: Python 3.9+
- **Web Framework**: FastAPI with Jinja2 templates
- **Database**: PostgreSQL with SQLAlchemy 2.0+ (async support)
- **Message Queue**: RabbitMQ for job distribution
- **Cache**: Redis for session/state management
- **AI/ML**: Azure OpenAI for bias detection (optional, falls back to heuristics)
- **Deployment**: Docker, Kubernetes with Kustomize, KEDA for autoscaling
- **Migration Tool**: Alembic for database migrations

## Architecture

### Microservices Structure
- `services/web/`: FastAPI dashboard and REST API (port 8000)
- `services/worker/`: Background job processor consuming from RabbitMQ
- `services/bias-scoring-service/`: Azure OpenAI integration (port 9000)
- `shared/`: Common code shared across all services
- `infra/`: Infrastructure code (K8s, DB migrations)

### Key Principles
- Each service is independently deployable with its own Dockerfile
- Shared models and utilities live in `shared/` directory
- Configuration is centralized in `shared/config.py` using dataclasses
- Database models use SQLAlchemy 2.0+ async patterns

## Development Setup

### Environment Setup
```bash
# Always set PYTHONPATH when running services manually
export PYTHONPATH=$(pwd):$PYTHONPATH

# Quick start with all services
./scripts/start-dev.sh

# Individual services
cd services/web && python src/main.py
cd services/worker && python src/queue_worker.py
cd services/bias-scoring-service && python main.py
```

### Docker Development
```bash
docker-compose up              # All services
docker-compose up web          # Web UI only (port 8010 -> 8000)
docker-compose logs -f web     # Follow logs
```

### Database Migrations
```bash
cd infra/db
alembic -c alembic.ini revision --autogenerate -m "description"
alembic -c alembic.ini upgrade head
```

## Coding Standards

### Python Style
- Follow PEP 8 conventions
- Use type hints for all function signatures
- Prefer async/await for I/O operations
- Use dataclasses for configuration and data structures
- Keep functions focused and single-purpose

### Import Organization
```python
# Standard library imports
import os
from typing import Optional, List

# Third-party imports
from fastapi import FastAPI, Depends
from sqlalchemy.ext.asyncio import AsyncSession

# Local imports
from shared.models import Scan, Page, Snippet
from shared.config import config
from shared.utils.database import get_session
```

### Configuration Access
```python
# Always use the centralized config
from shared.config import config

# Access config sections
config.database.url
config.azure_openai.is_available
config.rabbitmq.host
```

### Database Patterns

#### Model Definition (shared/models.py)
```python
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, DateTime

class Base(DeclarativeBase):
    pass

class Scan(Base):
    __tablename__ = "scans"
    
    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

#### Async Database Access
```python
from shared.utils.database import get_session
from sqlalchemy import select

async def get_scan(scan_id: int) -> Optional[Scan]:
    async with get_session() as session:
        result = await session.execute(
            select(Scan).where(Scan.id == scan_id)
        )
        return result.scalar_one_or_none()
```

### Error Handling
- Use custom exceptions from `shared/exceptions.py`
- Always include context in error messages
- Log errors with appropriate severity levels
- Return meaningful HTTP status codes in FastAPI routes

### FastAPI Routes
- Organize routes by feature in `services/web/src/routes/`
- Use dependency injection for database sessions
- Include proper response models
- Add OpenAPI documentation with descriptions

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from shared.utils.database import get_session

router = APIRouter(prefix="/scans", tags=["scans"])

@router.get("/{scan_id}", response_model=ScanResponse)
async def get_scan(
    scan_id: int,
    session: AsyncSession = Depends(get_session)
) -> ScanResponse:
    """Retrieve a specific scan by ID."""
    # Implementation
```

### Background Jobs (Worker Service)
- Process jobs from RabbitMQ queue
- Update database with job progress
- Handle job failures gracefully with retries
- Use proper logging for debugging

## Testing

### Running Tests
```bash
./scripts/run-tests.sh    # Integration tests (starts web + worker)
```

### Test Patterns
- No existing test infrastructure currently
- When adding tests, use pytest with async support
- Mock external services (Azure OpenAI, GitHub API)
- Test database operations with test fixtures
- Ensure tests clean up resources

## Common Patterns

### Repository List
- Repository configuration is in `config/repos.yaml`
- Each repository has owner, name, and documentation paths

### Bias Detection
- Heuristics in legacy `packages/scorer/heuristics.py`
- LLM scoring via bias-scoring-service
- Batch processing for efficiency (LLM_BATCH_SIZE env var)

### Progress Tracking
- Scans track phases: setup, crawling, extracting, scoring, complete
- Real-time updates via WebSocket in `services/web/src/routes/websocket.py`
- Database fields: started_at, crawl_phase_at, extraction_phase_at, scoring_phase_at, completed_at

## Security Considerations

- Never commit secrets or API keys
- Use environment variables for sensitive configuration
- Azure OpenAI supports both API key and managed identity (AZURE_OPENAI_CLIENTID)
- GitHub OAuth credentials are optional for authentication

## Performance

- Use async database operations throughout
- Batch LLM requests to stay within rate limits
- KEDA autoscaling for workers based on RabbitMQ queue depth
- Connection pooling for PostgreSQL

## Git Workflow

- No direct git commands for commits/pushes
- Changes are committed automatically by the development workflow
- Always use `.gitignore` to exclude build artifacts, `node_modules`, `__pycache__`, etc.

## Prohibited Actions

- Don't modify working code unless required for the task
- Don't remove or disable existing tests
- Don't add unnecessary dependencies
- Don't change database models without creating migrations
- Don't introduce breaking changes to shared models
- Don't commit temporary files or build artifacts

## Common Pitfalls

1. **PYTHONPATH**: Always set `PYTHONPATH=$(pwd):$PYTHONPATH` when running services manually
2. **Database Sessions**: Always use `async with get_session()` for proper cleanup
3. **Config Access**: Use `shared/config.py`, not environment variables directly
4. **Ports**: Web (8000), Bias Scoring (9000), PostgreSQL (5432), RabbitMQ (5672)
5. **Legacy Code**: `packages/` directory is being phased out, prefer `shared/` and service-specific code

## File Locations

### Adding New Features
- Web UI endpoints → `services/web/src/routes/`
- Background jobs → `services/worker/src/`
- Shared models → `shared/models.py`
- Shared utilities → `shared/utils/`
- Configuration → `shared/config.py`
- Database migrations → `infra/db/alembic/versions/`

### Infrastructure
- Kubernetes manifests → `infra/k8s/`
- Docker Compose → `docker-compose.yml` (root)
- Scripts → `scripts/`

## External Services

- **Azure OpenAI**: Optional for advanced bias detection
- **GitHub API**: For repository scanning
- **PostgreSQL**: Primary data store
- **RabbitMQ**: Job queue for distributed processing
- **Redis**: Session and state caching

## Documentation

- Update README.md for user-facing changes
- Update CLAUDE.md for development workflow changes
- Add docstrings to new functions and classes
- Comment complex logic or non-obvious implementations
