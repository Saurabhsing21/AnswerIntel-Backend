# AnswerIntel API

FastAPI + PostgreSQL backend for the AnswerIntel MVP (see `docs/technical-prd.md`).
Redis, Celery and Kafka are intentionally skipped for the MVP: scans run as FastAPI
background tasks inside the API process and the dashboard polls their progress.

## Run

```bash
cp .env.example .env            # then set JWT_SECRET_KEY (and OPENROUTER_API_KEY for real engines)
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload --port 8000
```

`GET /health` reports `ai_enabled`. Without `OPENROUTER_API_KEY` every scan uses the
simulated provider; scans, the API and the dashboard all label that data as simulated.

## Tests

```bash
.venv/bin/python -m pytest
```

Runs against the database in `DATABASE_URL` (unique users per test, no cleanup needed).

## MVP loop

register -> project -> competitors (max 5) -> `POST /prompts/generate` -> review/edit prompts ->
`POST /scans` (queued, runs in background) -> poll `GET /scans/{id}` -> `GET /dashboard`,
`/scans/{id}/results`, `/citations`, `/competitors/analysis`, `/opportunities`.

## Layout

| Module | Responsibility |
|---|---|
| `auth`, `users` | Register, login (JWT), Argon2id hashing |
| `projects`, `competitors` | Business setup, owner-scoped |
| `prompts` | Prompt Discovery Agent (LLM) + template fallback; project prompts and per-scan snapshots |
| `providers` | OpenRouter engines (ChatGPT, Perplexity, Gemini models) and the simulated provider |
| `scans` | Queue, background execution, retries, partial/failed status, progress |
| `analysis` | Mention vs recommendation, position, sentiment, competitors (LLM + rules), citations |
| `metrics` | Deterministic metrics per scan, engine and competitor; dashboard and analytics APIs |
| `opportunities` | Evidence-based gap detection and status tracking |
