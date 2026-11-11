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

register (from a pricing plan) -> Cashfree checkout -> workspace subscribed -> project -> competitors (plan limit) -> `POST /prompts/generate` ->
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
| `billing` | Plans and entitlements (every limit), Cashfree checkout, plan change and cancel, webhook, billing emails |
| `common` | Config, database, errors, rate limiting, safe HTTP fetcher, observability |

## Billing (Cashfree)

There is no free plan (only the one-off free check on the website). A new workspace can do nothing until it pays for Starter ($20), Growth ($50) or Pro ($100) a month through Cashfree Subscriptions
(the website's pricing buttons go to `/register?plan=...`, which continues straight to checkout; an unpaid account
sees a "Complete your subscription" step). Workspaces that existed before billing got a one-time 14-day trial that
runs out on its own. Each plan has a prompt pool shared by its projects and a monthly AI-answer allowance (prompt × engine) that
every scan draws from; that allowance is what bounds model cost. Limits and prices live in `app/billing/plans.py`. Without `CASHFREE_CLIENT_ID`/`CASHFREE_CLIENT_SECRET` checkout says billing is off.

How it works: checkout creates a Cashfree subscription on a periodic plan (`seenlense_<plan>_<interval>_usd<price>`,
created in Cashfree on first use, so a price change makes a new plan and never edits a live one) and the browser opens
Cashfree's hosted checkout. The authorisation charges the first period in full; Cashfree charges every renewal itself.
Cashfree requires a phone number, asked once at the first checkout. There is no customer portal: the owner changes
plan (`/billing/change`, Cashfree `CHANGE_PLAN`, new limits now and new price from the next renewal) or cancels
(`/billing/cancel`, everything keeps working until the paid period ends) in the app.

Setup:

1. Put the test keys in `CASHFREE_CLIENT_ID`/`CASHFREE_CLIENT_SECRET` with `CASHFREE_ENV=sandbox`. Charging in USD needs
   International Payments enabled on the account (sandbox allows it).
2. Webhooks: in the Cashfree dashboard (Developers -> Webhooks, Subscriptions) add `<API URL>/api/v1/billing/webhook`
   (Cashfree calls the API directly, not through the Next.js proxy). Locally, expose port 8000 with
   `ngrok http 8000` and use the ngrok URL. Events used: `SUBSCRIPTION_STATUS_CHANGED`, `SUBSCRIPTION_AUTH_STATUS`,
   `SUBSCRIPTION_PAYMENT_SUCCESS`, `SUBSCRIPTION_PAYMENT_FAILED`.
3. Set `APP_BASE_URL` to the dashboard URL (checkout returns there).
4. Try it: subscribe and approve the sandbox payment (plan flips to the paid tier), change plan, cancel (stays active
   until the period ends). A failed renewal makes it past due with a 7-day grace, then read-only.

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
