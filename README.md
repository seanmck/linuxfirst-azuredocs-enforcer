# Linux-first Azure Docs Enforcer

## Overview

This project crawls Azure documentation websites, extracts code snippets, and scores them using heuristics and LLMs to detect Windows bias in documentation. It helps ensure Azure documentation provides cross-platform examples and doesn't favor Windows-only solutions.

## Features

- **Web-based Dashboard**: Modern web UI for managing scans and viewing results
- **Intelligent Bias Detection**: Uses both heuristics and AI to detect Windows-specific patterns
- **Concurrent Scan Support**: Handle multiple scans simultaneously with proper isolation
- **Flexible AI Integration**: Works with Azure OpenAI or falls back to heuristic detection
- **Real-time Progress**: Live updates during scan execution
- **Admin Controls**: Secure admin interface for managing scans and schedules

## Directory Structure

### Service-Based Architecture
- `services/`: Microservices with clear boundaries
  - `services/web/`: FastAPI web interface and dashboard
  - `services/worker/`: Background processing and crawling service
  - `services/bias-scoring-service/`: AI-powered bias detection and scoring service
- `shared/`: Common code shared across services
  - `shared/models.py`: Database models
  - `shared/config.py`: Centralized configuration
  - `shared/utils/`: Shared utilities
- `packages/`: Legacy packages being phased out
  - `packages/extractor/`: HTML parsing and snippet extraction
  - `packages/scorer/`: Pre-filtering and LLM-based scoring
- `infra/`: Infrastructure code (Azure, K8s, Docker, DB migrations)
- `scripts/`: Development and deployment scripts

## Quick Start

### Option 1: Local Development

1. **Clone and setup:**
   ```sh
   git clone <repository-url>
   cd linuxfirst-azuredocs-enforcer
   ./setup_and_run.sh --web
   ```

2. **Access the web UI:**
   - Open http://localhost:8000
   - Admin dashboard: http://localhost:8000/admin (password: admin123)

### Option 2: Docker

1. **Start with Docker:**
   ```sh
   ./setup_and_run.sh --docker --web
   ```

2. **Access the web UI:**
   - Open http://localhost:8000

## Configuration

### Azure OpenAI Integration (Optional)

For enhanced bias detection, you can configure Azure OpenAI:

1. Set environment variables:
   ```sh
   export AZURE_OPENAI_KEY="your-api-key"
   export AZURE_OPENAI_ENDPOINT="https://your-resource.openai.azure.com/"
   export AZURE_OPENAI_DEPLOYMENT="your-deployment-name"
   ```

2. Restart the application:
   ```sh
   ./setup_and_run.sh --web
   ```

**Note:** The system works without Azure OpenAI credentials using heuristic detection.

See [AZURE_OPENAI_SETUP.md](AZURE_OPENAI_SETUP.md) for detailed setup instructions.

## Usage

### Web Interface

1. **Start a scan:**
   - Go to Admin Dashboard → Manual Scan
   - Choose scan type (Manual, Targeted, Full)
   - Optionally specify a target URL
   - Click "Start Scan"

2. **View results:**
   - Dashboard shows recent scans and flagged snippets
   - Click on any scan to see detailed results
   - View bias analysis and suggested alternatives

### Command Line

Run services directly:
```sh
# Web service
cd services/web && python src/main.py

# Worker service
cd services/worker && python src/queue_worker.py
```

## Scan Types

- **Manual**: Starts from Azure Virtual Machines docs (default)
- **Targeted**: Starts from Azure App Service docs
- **Full**: Starts from Azure root and crawls extensively

## Bias Detection

The system detects various types of Windows bias:

- PowerShell-only commands
- Windows-specific paths and commands
- Windows registry references
- Windows service management
- Missing Linux/macOS alternatives
- Windows-specific syntax and tools

## Extending

- **New services**: Create new directories in `services/` with their own `src/` and `Dockerfile`
- **Web UI features**: Add endpoints in `services/web/src/routes/`
- **Worker functionality**: Extend `services/worker/src/` components
- **Shared components**: Add to `shared/` for cross-service functionality
- **Configuration**: Update `shared/config.py` for new settings
- **Database changes**: Add models to `shared/models.py` and create migrations

## Troubleshooting

### Common Issues

1. **Port conflicts**: The script automatically stops conflicting Docker containers
2. **Missing dependencies**: Run `./setup_and_run.sh --web` to install automatically
3. **Database issues**: Use `./setup_and_run.sh --wipe --web` to reset everything
4. **LLM errors**: Check [AZURE_OPENAI_SETUP.md](AZURE_OPENAI_SETUP.md) for API setup

### Logs

- Web UI logs: Check terminal output when running locally
- Docker logs: `docker-compose logs webui`
- Queue worker logs: Check terminal output or Docker logs

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test with `./setup_and_run.sh --web`
5. Submit a pull request
