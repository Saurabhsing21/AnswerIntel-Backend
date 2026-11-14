from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_env: str = "development"
    # Launch mode: only the waitlist endpoint answers; every other API route is 404 (the website is the product).
    waitlist_only: bool = False
    sentry_dsn: str = ""  # empty = error monitoring off
    # Comma-separated emails that may open the /admin cost pages (verified accounts only). Empty = nobody.
    admin_emails: str = ""

    # Neon writes plain postgresql:// URLs to the repo-root .env.local; the pooled one serves the app, the direct
    # (unpooled) one runs migrations.
    database_url: str
    database_url_unpooled: str = ""

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 30  # PRD 6

    # AI gateway. Empty key = AI features answer 503 AI_UNAVAILABLE; production refuses to boot without one.
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # Swap an engine's model without a code change: "claude=anthropic/claude-sonnet-4.5,grok=x-ai/grok-4". The engines
    # themselves are listed in app/providers/models.py.
    engine_models: str = ""
    # Google AI Mode answers through DataForSEO's SERP API. Empty login = the engine is off.
    dataforseo_login: str = ""
    dataforseo_password: str = ""

    # Spend guardrails. Daily budget: all AI spend per UTC day except the free check's (0 = no limit). It grows with
    # paying users: this flat amount plus daily_budget_share_of_paid_cap x the sum of every paying workspace's cap.
    # Workspace cap: this share of what the workspace pays a month (a yearly price over 12): 62% on monthly and yearly
    # plans, so AI plus Paddle's fee (at most 7.5%) stays under 70% and we keep at least 30% (the cost rule, see
    # app/billing/plans.py); plans priced at 0 use the flat dollar cap. The free check has its own daily
    # budget, so anonymous traffic can never pause paid scans.
    daily_ai_budget_usd: float = 10.0
    daily_budget_share_of_paid_cap: float = 0.1
    workspace_cost_cap_ratio: float = 0.62
    workspace_cost_cap_ratio_yearly: float = 0.62
    free_workspace_cost_cap_usd: float = 1.0
    free_check_daily_budget_usd: float = 5.0  # 0 = no limit

    # Free website check: a few unbranded prompts on two engines (about $0.09 each). The daily cap bounds cost.
    # Off until launch: while off the public endpoint answers 404, so nobody can run paid AI calls through it.
    free_check_enabled: bool = False
    free_checks_per_day: int = 100
    free_checks_per_client: int = 3
    free_check_prompts: int = 5
    free_check_engines: str = "chatgpt_search,perplexity"
    prompt_model: str = "openai/gpt-5.4-mini"  # one call per project, so quality wins here
    analysis_model: str = "openai/gpt-5.4-nano"  # runs on every answer
    competitor_model: str = "openai/gpt-5.4-nano"  # one web-search call per new project to suggest 8 competitors
    provider_timeout_seconds: float = 90
    provider_max_retries: int = 2
    scan_concurrency: int = 4
    # Connection pool, sized for 4 concurrent scans in one Celery process, each holding a session plus
    # scan_concurrency workers writing the cost ledger: 4 * (1 + 4) = 20 steady, 10 overflow headroom.
    db_pool_size: int = 20
    db_max_overflow: int = 10
    db_pool_timeout_seconds: float = 10  # short, so a busy pool cannot stall a scan for the 30s default
    # Seconds to wait before each retry of a failed provider call (PRD 59). Three delays = three retries.
    provider_retry_delays: str = "30,120,600"
    provider_max_parallel_per_engine: int = 2
    max_scans_per_day: int = 20  # per project (PRD 60-61); plans set a lower per-workspace limit
    rate_limit_enabled: bool = True
    login_rate_limit_per_minute: int = 5  # per IP (PRD 60)
    api_rate_limit_per_minute: int = 100  # per user (PRD 60)
    waitlist_rate_limit_per_minute: int = 10  # per IP; the endpoint is public
    # Empty = run scans in-process (local dev). Set = Celery workers on Redis (PRD 56).
    redis_url: str = ""
    # Single-server production (no Redis/Celery): scans run in the API process. Opt in explicitly so a real
    # production deploy does not fall back to in-process by accident. Weekly scans then need an external cron.
    run_scans_in_process: bool = False

    raw_response_retention_days: int = 730  # ceiling; each plan keeps less or equal (PRD 88). Aggregates are kept

    # Hard ceilings per project. Each workspace's plan sets its own limits below these (app/billing/plans.py).
    max_competitors: int = 100
    max_active_prompts: int = 700

    cors_origins: str = "http://localhost:3000"
    # Shared with the website's server (same value there). Requests carrying it may name the visitor's address in
    # X-Client-IP, so rate limits count per visitor instead of per website server. Empty = only the connecting address.
    proxy_shared_secret: str = ""

    # Report email delivery (Resend). Empty key = sending is disabled and the API says so.
    # Google Identity Services web client ID. Empty = "Continue with Google" is hidden.
    google_client_id: str = ""
    resend_api_key: str = ""
    email_from: str = "Seenlense <saurabh@seenlense.com>"

    # Billing (Paddle). Checkout runs in the browser; payments reach a workspace through the signed webhook, so an
    # empty PADDLE_WEBHOOK_SECRET means billing is off. PADDLE_API_KEY powers the portal and plan changes.
    paddle_env: str = ""  # sandbox | production; required once a Paddle key or secret is set, never guessed
    paddle_api_key: str = ""
    paddle_webhook_secret: str = ""
    # Accept webhooks only from Paddle's published addresses (on top of the signature). The caller's address is what
    # uvicorn resolves from X-Forwarded-For (--proxy-headers), so FORWARDED_ALLOW_IPS must cover the host's proxy.
    paddle_webhook_ip_check: bool = True
    # File storage (Cloudflare R2). Any value missing = report PDFs stay in the database.
    r2_account_id: str = ""
    r2_bucket: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    app_base_url: str = "http://localhost:3000"  # links in billing emails and the customer portal's way back

    model_config = {
        "env_file": (".env", "../.env.local"),  # later files win: Neon's .env.local overrides backend/.env
        "extra": "ignore",
    }

    @field_validator("database_url", "database_url_unpooled")
    @classmethod
    def use_psycopg_driver(cls, url: str) -> str:
        return "postgresql+psycopg://" + url.removeprefix("postgresql://") if url.startswith("postgresql://") else url

    @model_validator(mode="after")
    def reject_weak_production_secrets(self):
        # A guessable signing secret lets anyone mint valid tokens, so production refuses to boot with one.
        if self.app_env == "production" and (len(self.jwt_secret_key) < 32 or "change-this" in self.jwt_secret_key.lower()):
            raise ValueError("JWT_SECRET_KEY must be a random value of at least 32 characters when APP_ENV=production.")
        # Never guess the Paddle environment: the wrong one sends requests to the wrong account.
        if (self.paddle_api_key or self.paddle_webhook_secret) and self.paddle_env not in ("sandbox", "production"):
            raise ValueError("PADDLE_ENV must be sandbox or production when a Paddle key or webhook secret is set.")
        if self.app_env == "production" and self.billing_enabled and self.paddle_env != "production":
            raise ValueError("PADDLE_ENV must be production when APP_ENV=production.")
        # Without a key no scan or AI feature can run: never acceptable for paying users.
        # The waitlist-only launch site has no scans, so it may run without one.
        if self.app_env == "production" and not self.waitlist_only and not self.openrouter_api_key.strip():
            raise ValueError("OPENROUTER_API_KEY is required when APP_ENV=production (unless WAITLIST_ONLY=true).")
        # Without a queue, scans run inside the API process: a deploy or restart cuts them off, and their retry waits
        # hold the API's threads. The waitlist-only site runs no scans.
        if (self.app_env == "production" and not self.waitlist_only
                and not self.redis_url.strip() and not self.run_scans_in_process):
            raise ValueError(
                "In production set REDIS_URL (Celery workers) or RUN_SCANS_IN_PROCESS=true (single server), "
                "unless WAITLIST_ONLY=true."
            )
        return self

    @property
    def retry_delays(self) -> list[float]:
        return [float(d) for d in self.provider_retry_delays.split(",") if d.strip()]

    @property
    def google_ai_enabled(self) -> bool:
        return bool(self.dataforseo_login.strip() and self.dataforseo_password.strip())

    @property
    def billing_enabled(self) -> bool:
        return bool(self.paddle_webhook_secret.strip())

    @property
    def r2_enabled(self) -> bool:
        return all(v.strip() for v in (self.r2_account_id, self.r2_bucket, self.r2_access_key_id, self.r2_secret_access_key))

    @property
    def ai_enabled(self) -> bool:
        return bool(self.openrouter_api_key.strip())


settings = Settings()
