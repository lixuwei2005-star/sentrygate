# Step 1 Backend Scaffold Spec

## Goal

Create the initial backend scaffold for SentryGate.

This step should only create the backend foundation. Do not implement policy engine, privacy masking, risk scoring, MCP server, LM Studio, audit storage, safe tool wrappers, or frontend yet.

## Requirements

### Backend Stack

Use:

- Python 3.11
- FastAPI
- uv
- pytest
- ruff
- mypy
- Pydantic

### Directory Structure

Create:

```text
backend/
|-- app/
|   |-- __init__.py
|   |-- main.py
|   |-- core/
|   |   |-- __init__.py
|   |   `-- config.py
|   |-- privacy/
|   |   `-- __init__.py
|   |-- risk/
|   |   `-- __init__.py
|   |-- audit/
|   |   `-- __init__.py
|   |-- tools/
|   |   `-- __init__.py
|   `-- mcp/
|       `-- __init__.py
|-- tests/
|   |-- __init__.py
|   `-- test_health.py
|-- pyproject.toml
`-- README.md
```

### FastAPI App

Implement:

- `GET /health`

Expected response:

```json
{
  "status": "ok",
  "service": "sentrygate"
}
```

## Quality Tools

Configure:

- pytest
- ruff
- mypy

The following commands should work from `backend/`:

```bash
uv sync
uv run pytest
uv run ruff check .
uv run mypy app
uv run uvicorn app.main:app --reload
```

## Acceptance Criteria

- The backend project can install dependencies with `uv sync`.
- `GET /health` returns HTTP 200 and the expected JSON body.
- `uv run pytest` passes.
- `uv run ruff check .` passes.
- `uv run mypy app` passes.
- `uv run uvicorn app.main:app --reload` starts the development server.
- The scaffold contains the directory structure listed above.
- No policy engine, privacy masking engine, risk scoring engine, MCP server, LM Studio client, audit storage, safe tool wrappers, or frontend code is implemented in this step.

## Completion Checklist

- [ ] Backend scaffold exists under `backend/`.
- [ ] `pyproject.toml` defines project metadata, dependencies, and tool configuration.
- [ ] `app.main` exposes the FastAPI application.
- [ ] `/health` endpoint returns the expected JSON.
- [ ] Health endpoint test exists and passes.
- [ ] pytest, ruff, and mypy commands pass.
- [ ] Development server starts with uvicorn.
- [ ] README exists only as an initial backend README.
- [ ] Business logic is intentionally deferred to later steps.

## Constraints

- Keep this step simple.
- Do not implement business logic yet.
- Do not add database logic yet.
- Do not add MCP server logic yet.
- Do not add frontend yet.
- Use typed Python.
- Keep code easy to extend.
