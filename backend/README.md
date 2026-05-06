# SentryGate Backend

Minimal FastAPI backend scaffold for SentryGate Step 1.1.

## Setup

```bash
uv sync
```

## Verification

Run from this `backend/` directory:

```bash
uv run pytest
uv run ruff check .
uv run mypy app
uv run uvicorn app.main:app --reload
```

The health endpoint should return:

```json
{"status":"ok","service":"sentrygate"}
```
