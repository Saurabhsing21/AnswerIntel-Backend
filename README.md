# SeenLense API

FastAPI + PostgreSQL + Redis/Celery backend (see `docs/technical-prd.md`). A modular monolith: one API,
background workers for scans, and a scheduler.

## Run locally

```bash
cp .env.example .env                  # set DATABASE_URL and JWT_SECRET_KEY; OPENROUTER_API_KEY for real engines
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/alembic upgrade head
(cd pdf-renderer && npm ci && npm run build)   # the PDF report renderer; needs Node 20+
.venv/bin/uvicorn app.main:app --reload --port 8000
```

With `REDIS_URL` empty, scans run inside the API process (fine for development; production refuses to start
without it unless `WAITLIST_ONLY=true`). Without `OPENROUTER_API_KEY` scans and other AI features answer
503 `AI_UNAVAILABLE`; the tests install a simulated provider of their own.

### With the job queue (production-like)

```bash
# set REDIS_URL in .env, then in separate terminals:
.venv/bin/celery -A app.worker.celery_app worker -Q scan -P threads --concurrency 4
.venv/bin/celery -A app.worker.celery_app worker -Q reports -P threads --concurrency 2   # report PDFs
.venv/bin/celery -A app.worker.celery_app beat      # exactly ONE instance
```

Every new report gets its PDF drawn once by the `reports` worker (`app/reports/pdf_jobs.py`): the rules in
`app/reports/document.py` decide what each page says, and `pdf-renderer/` (React PDF) draws it in about a second.
Downloads are then served from the database; the export answers 202 while a PDF is still being drawn.

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

register (from a pricing plan) -> Paddle checkout -> workspace subscribed -> project -> competitors (plan limit) -> `POST /prompts/generate` ->
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
| `billing` | Plans and entitlements (every limit), Paddle webhook (mirrors subscriptions and customers), customer portal, plan change, billing emails |
| `common` | Config, database, errors, rate limiting, safe HTTP fetcher, observability |

## Billing (Paddle)

There is no free plan (only the one-off free check on the website). A new workspace can do nothing until it pays for Starter ($20), Growth ($50) or Pro ($100) a month through Paddle
(the website's pricing buttons open Paddle's checkout, after sign-up for new visitors; an unpaid account sees a
"Complete your subscription" step). Workspaces that existed before billing got a one-time 14-day trial that
runs out on its own. Each plan has a prompt pool shared by its projects and a monthly AI-answer allowance (prompt × engine) that
every scan draws from; that allowance is what bounds model cost. Limits live in `app/billing/plans.py`; prices live in Paddle.

How it works: checkout runs in the browser (Paddle.js, overlay) with `custom_data.workspace_id`. Paddle's signed
webhook (`POST /api/v1/billing/webhook`) is the only thing that grants a plan: `subscription.*` events are mirrored onto
the workspace's `subscriptions` row (keyed by Paddle id, older copies never overwrite newer ones), `customer.*` onto
`paddle_customers`, duplicates are skipped by event id. Each Paddle price carries `{"plan", "interval"}` in its
custom_data, which is how a subscription maps to a plan. Access: `active` and `trialing` grant it, a scheduled cancel
keeps it until Paddle actually cancels, `past_due` keeps it for a 7-day grace, `paused` and `canceled` make the
workspace read-only. The owner opens Paddle's customer portal (`/billing/portal`: invoices, card, cancel) and changes
plan in the app (`/billing/change`, prorated by Paddle).

Setup:

1. Set `PADDLE_ENV=sandbox`, `PADDLE_API_KEY` (pdl_sdbx_apikey_..., needs subscription, customer portal and price read
   access) and `PADDLE_WEBHOOK_SECRET`. Without the secret billing is off.
2. Webhooks: create a notification destination (Paddle > Developer tools > Notifications) for
   `<API URL>/api/v1/billing/webhook` with `subscription.*`, `customer.created`, `customer.updated` and
   `transaction.completed`, and copy its secret. Locally, expose port 8000 with `ngrok http 8000`.
3. Frontend: `NEXT_PUBLIC_PADDLE_ENV` and `NEXT_PUBLIC_PADDLE_CLIENT_TOKEN`; price ids per environment are in
   `frontend/lib/billing/paddle.ts`.
4. Try it: subscribe with 4242 4242 4242 4242 (declined: 4000 0000 0000 0002), then change plan and cancel in the portal.

A failed payment emails the owners from the webhook. Celery beat also sends "trial ends in 3 days" and "trial
ended" emails daily (`billing.trial_notices`), only for the legacy trials. Both use Resend and are skipped when it is not configured.

## Measurement

- ChatGPT and Gemini answer with their native web search (`WEB_SEARCH_ENGINES`), Perplexity always searches, and
  every engine is told the project's market, so answers match what people see in the apps.
- Google AI Mode is a fourth engine through DataForSEO's SERP API: set `DATAFORSEO_LOGIN` and `DATAFORSEO_PASSWORD`
  (from app.dataforseo.com/api-access, about $0.004 per answer). Empty = the engine is off.
- Each verdict keeps the sentence from the answer behind it; rates carry a 95% margin and changes are flagged when
  they are within run-to-run noise (dashboard and experiments).
- `POST /api/v1/free-check` is a public, one-off check (5 unbranded prompts on ChatGPT and Perplexity, about $0.09).
  The same site is answered from cache for 24 hours; `FREE_CHECKS_PER_DAY` caps total cost.

## Known limits

- Workspace invitations by email work (14-day link; the invitee must register or log in with the invited address). Adding an existing account skips the link.
- Scan and report IDs are integers (the PRD sketches UUIDs); routes are nested under `/projects/{id}/...`.
- The "ask my AI visibility" chat is intentionally not built (PRD section 99).
- Billing has no tax/GST invoicing yet.
