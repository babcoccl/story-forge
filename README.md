# StoryForge

An AI-powered story generation system using a multi-agent pipeline with local LLMs (llama.cpp).

## Architecture

StoryForge uses a pipeline of specialized agents to generate coherent, creative fiction:

1. **Sampler Agent** — Selects compatible story components from the library
2. **Planner Agent** — Designs story outline, chapters, and scene beats
3. **Scene Writer Agent** — Writes prose for each scene
4. **Continuity Agent** — Ensures consistency across scenes and chapters
5. **Judge Agent** — Evaluates scene quality and triggers retries
6. **Wordsmith Agent** — Polishes final prose for style and flow

## Prerequisites

- Ubuntu 24.04
- Python 3.12+
- PostgreSQL 17
- llama.cpp server (started separately)

## Quick Start

```bash
# 1. Install system packages (if not already present)
sudo apt update
sudo apt install -y postgresql postgresql-contrib python3-pip python3-venv build-essential

# 2. Create virtual environment and install dependencies
make install

# 3. Copy environment file and configure
cp .env.example .env
# Edit .env: set your DB password, confirm LLM_BASE_URL matches your llama.cpp server

# 4. Bootstrap PostgreSQL (creates user + database)
make db-bootstrap

# 5. Run database migrations
make upgrade

# 6. Start the API server
make run-dev
```

Visit http://localhost:8000/health → should return `{"status": "ok"}`

## Project Structure

```
story-forge/
├── backend/          # FastAPI application
│   ├── app/
│   │   ├── api/      # API routers
│   │   ├── core/     # Configuration, logging, events
│   │   ├── db/       # SQLAlchemy engine + session
│   │   ├── models/   # ORM models
│   │   ├── schemas/  # Pydantic schemas
│   │   ├── services/ # Business logic services
│   │   ├── agents/   # LLM agent implementations
│   │   └── orchestrator/  # Pipeline orchestration
│   └── alembic/      # Database migrations
├── frontend/         # Web UI (future)
└── infra/            # Infrastructure scripts
```

## Development

```bash
# Install dev dependencies
make install-dev

# Run linter
make lint

# Format code
make format

# Run tests
make test
```

## Database

Migrations are managed with Alembic:

```bash
# Generate a new migration
make migrate msg="description_of_changes"

# Apply pending migrations
make upgrade

# Rollback one migration
make downgrade
```

## License

MIT