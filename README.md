# SeenLens API

FastAPI + PostgreSQL + Redis/Celery backend (see `docs/technical-prd.md`). A modular monolith: one API,
background workers for scans, and a scheduler.

## Run locally

```bash
cp .env.example .env                  # set DATABASE_URL and JWT_SECRET_KEY; OPENROUTER_API_KEY for real engines
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload --port 8000
```

With `REDIS_URL` empty, scans run inside the API process (fine for development). Without
`OPENROUTER_API_KEY` every scan uses the simulated provider, and the API and dashboard label that data as simulated.

### With the job queue (production-like)

```bash
# set REDIS_URL in .env, then in separate terminals:
.venv/bin/celery -A app.worker.celery_app worker -Q scan -P threads --concurrency 4
.venv/bin/celery -A app.worker.celery_app beat      # exactly ONE instance
```

Use `-P threads`: scans are I/O-bound, and Celery's default prefork pool crashes on Python 3.14.
Beat queues three jobs: weekly scans for projects that enabled a schedule, a sweep that re-queues scans
whose job was lost, and a daily purge of raw answers older than `RAW_RESPONSE_RETENTION_DAYS`.

### With Docker

```bash
cd ../infrastructure/docker
export JWT_SECRET_KEY=$(openssl rand -hex 32)
docker compose up --build            # db, redis, migrate (one-shot), api :8000, worker, beat
```

## Tests and checks

```bash
.venv/bin/python -m pytest           # runs against DATABASE_URL; unique users per test, no cleanup needed
.venv/bin/alembic check              # fails if the models and migrations disagree
```

CI (`.github/workflows/ci.yml`) runs migrations on an empty database, `alembic check`, the backend tests, and
the frontend lint, type-check and build.

## Health

- `GET /health` is liveness (also reports `ai_enabled`).
- `GET /ready` is readiness: checks PostgreSQL and, when configured, Redis. It returns only `ok`, `failed` or
  `skipped`, never error details.

Logs are one JSON object per line with a `request_id` (also returned as `X-Request-ID`). Query strings,
headers and bodies are never logged. Set `SENTRY_DSN` for error monitoring. With `APP_ENV=production` the
app refuses to start with a weak `JWT_SECRET_KEY`.

## The product loop

register -> workspace (personal one is created) -> project -> competitors (max 5) -> `POST /prompts/generate` ->
review prompts -> `POST /scans` (queued; poll `GET /scans/{id}`) -> `GET /dashboard`, `/scans/{id}/results`,
`/citations`, `/competitors/analysis`, `/opportunities` -> `POST /experiments` (baseline) -> change the site ->
re-scan -> `POST /experiments/{id}/complete` -> `POST /reports` (share, export HTML/PDF, email).
Everything above lives under `/api/v1/projects/{project_id}/...`.

## Layout

| Module | Responsibility |
|---|---|
| `auth`, `users` | Register, login, rotating refresh tokens, logout, Argon2id hashing |
| `workspaces` | Workspaces, roles (owner/admin/member), members. Every project query is scoped to membership |
| `projects`, `competitors` | Business setup |
| `prompts` | Prompt Discovery Agent (LLM) + template fallback; project prompts and per-scan snapshots |
| `providers` | OpenRouter engines (ChatGPT, Perplexity, Gemini models) and the simulated provider |
| `scans` | Queue, execution with retry backoff (30s/2m/10m), resume, idempotency, per-engine caps, daily limit, retention |
| `worker` | Celery app and tasks (scan, scheduler, sweeper, purge) |
| `schedules` | Weekly scan schedule per project; scheduler only queues work |
| `analysis` | Mention vs recommendation, position, sentiment, competitors (LLM + rules), citations |
| `metrics` | Deterministic metrics per scan, engine and competitor; dashboard and analytics APIs |
| `opportunities` | Evidence-based gap detection (7 types), SSRF-safe site audit, status tracking |
| `experiments` | Baseline and follow-up snapshots with before/after comparison |
| `reports` | Weekly/monthly/manual reports, share links, HTML/PDF export, Resend email |
| `waitlist` | Public landing-page signups (idempotent, rate limited) |
| `common` | Config, database, errors, rate limiting, safe HTTP fetcher, observability |

## Known limits

- Adding a workspace member works for existing accounts only; email invitations are not built.
- Scan and report IDs are integers (the PRD sketches UUIDs); routes are nested under `/projects/{id}/...`.
- Billing and the "ask my AI visibility" chat are intentionally not built (PRD section 99).
