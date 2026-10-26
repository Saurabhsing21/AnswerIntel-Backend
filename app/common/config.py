from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_env: str = "development"
    # Launch mode: only the waitlist endpoint answers; every other API route is 404 (the website is the product).
    waitlist_only: bool = False
    sentry_dsn: str = ""  # empty = error monitoring off

    database_url: str

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 30  # PRD 6

    # AI gateway. Empty key = simulated provider (clearly labelled in the API and UI).
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # Swap an engine's model without a code change: "claude=anthropic/claude-sonnet-4.5,grok=x-ai/grok-4". The engines
    # themselves are listed in app/providers/models.py.
    engine_models: str = ""
    # Google AI Mode answers through DataForSEO's SERP API. Empty login = the engine is off.
    dataforseo_login: str = ""
    dataforseo_password: str = ""

    # Free website check: a few unbranded prompts on two engines (about $0.09 each). The daily cap bounds cost.
    # Off until launch: while off the public endpoint answers 404, so nobody can run paid AI calls through it.
    free_check_enabled: bool = False
    free_checks_per_day: int = 100
    free_checks_per_client: int = 3
    free_check_prompts: int = 5
    free_check_engines: str = "chatgpt_search,perplexity"
    prompt_model: str = "openai/gpt-5.4-mini"  # one call per project, so quality wins here
    analysis_model: str = "openai/gpt-5.4-nano"  # runs on every answer
    provider_timeout_seconds: float = 90
    provider_max_retries: int = 2
    scan_concurrency: int = 4
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

    raw_response_retention_days: int = 730  # ceiling; each plan keeps less or equal (PRD 88). Aggregates are kept

    # Hard ceilings per project. Each workspace's plan sets its own limits below these (app/billing/plans.py).
    max_competitors: int = 100
    max_active_prompts: int = 700

    cors_origins: str = "http://localhost:3000"

    # Report email delivery (Resend). Empty key = sending is disabled and the API says so.
    # Google Identity Services web client ID. Empty = "Continue with Google" is hidden.
    google_client_id: str = ""
    resend_api_key: str = ""
    email_from: str = "SeenLens <reports@seenlens.com>"

    # Billing (Stripe). Empty secret key = checkout and portal are disabled and the API says so.
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_starter_monthly: str = ""
    stripe_price_starter_yearly: str = ""
    stripe_price_growth_monthly: str = ""
    stripe_price_growth_yearly: str = ""
    stripe_price_pro_monthly: str = ""
    stripe_price_pro_yearly: str = ""
    app_base_url: str = "http://localhost:3000"  # where Stripe sends people back after Checkout and the Portal

    model_config = {
        "env_file": ".env",
        "extra": "ignore",
    }

    @model_validator(mode="after")
    def reject_weak_production_secrets(self):
        # A guessable signing secret lets anyone mint valid tokens, so production refuses to boot with one.
        if self.app_env == "production" and (len(self.jwt_secret_key) < 32 or "change-this" in self.jwt_secret_key.lower()):
            raise ValueError("JWT_SECRET_KEY must be a random value of at least 32 characters when APP_ENV=production.")
        # Billing on without a webhook secret would take payments that never reach the workspace's plan.
        if self.app_env == "production" and self.stripe_secret_key and not self.stripe_webhook_secret:
            raise ValueError("STRIPE_WEBHOOK_SECRET is required when STRIPE_SECRET_KEY is set and APP_ENV=production.")
        # Without a key every scan is simulated and prompts come from templates: never acceptable for paying users.
        # The waitlist-only launch site has no scans, so it may run without one.
        if self.app_env == "production" and not self.waitlist_only and not self.openrouter_api_key.strip():
            raise ValueError("OPENROUTER_API_KEY is required when APP_ENV=production (unless WAITLIST_ONLY=true).")
        return self

    @property
    def retry_delays(self) -> list[float]:
        return [float(d) for d in self.provider_retry_delays.split(",") if d.strip()]

    @property
    def google_ai_enabled(self) -> bool:
        return bool(self.dataforseo_login.strip() and self.dataforseo_password.strip())

    @property
    def billing_enabled(self) -> bool:
        return bool(self.stripe_secret_key.strip())

    @property
    def ai_enabled(self) -> bool:
        return bool(self.openrouter_api_key.strip())


settings = Settings()
