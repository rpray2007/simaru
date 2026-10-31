# Simaru

Generative social simulation of a place and a policy. Agents notice events (System 1 / TypeSafe Jev), sometimes deliberate (System 2), spread information through social circles, and update a shared world. One sweep is one simulated week.

This repository is the AgentSimCity MVP described in [`generative-social-simulation-technical-spec.md`](generative-social-simulation-technical-spec.md).

## Requirements

- Python 3.12+
- PostgreSQL 16 with `pgvector` (or Docker)
- Node.js 20+ (for the web UI)
- A [TypeSafe](https://docs.typesafe.ai/api) API key for hosted Jev (System 1)

Optional:

- [Ollama](https://ollama.com) with `llama3.2:3b` and `nomic-embed-text` for live LLM / embedding roles
- Local [openjev-server](https://github.com/loopai-hq/openjev-server) on port 3000 instead of hosted Jev

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
```

Edit `.env` (this file is gitignored — do not commit it):

```bash
SIM_DATABASE_URL=postgresql+psycopg://sim:sim@localhost:5432/sim
TYPESAFE_API_KEY=your_key_here
```

Start Postgres:

```bash
docker compose up -d postgres
```

Create tables (from the repo root, with the venv active):

```bash
export SIM_DATABASE_URL=postgresql+psycopg://sim:sim@localhost:5432/sim
python -c "from sim.db.bootstrap import create_all; create_all()"
```

## Run

API (port 8000):

```bash
export PYTHONPATH=.
python -m uvicorn sim.api.app:app --host 127.0.0.1 --port 8000
```

Web UI (port 5173, proxies `/api` to the backend):

```bash
cd web
npm install
npm run dev
```

Default model roles are in `config/defaults.yaml`: System 1 uses `typesafe-hosted` (`jev-latest`). LLM roles default to deterministic stubs; point them at `llama3.2-3b` in that file when Ollama is running.

## Tests

```bash
PYTHONPATH=. pytest
```

Postgres-backed tests skip if `SIM_DATABASE_URL` is unreachable.

## Layout

```
config/     defaults.yaml, models.yaml
sim/        engine, agents, System 1 adapter, LLM gateway, API
web/        React + Vite UI
tests/      unit and integration tests
```

## Secrets

Copy `.env.example` to `.env` and fill in keys locally. `.gitignore` excludes `.env`, virtualenvs, `node_modules`, and local model weights. Never put API keys in YAML or the README.
