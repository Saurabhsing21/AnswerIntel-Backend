from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30

    # AI gateway. Empty key = simulated provider (clearly labelled in the API and UI).
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # engine_key=openrouter/model-slug, comma separated. Keys map to display names.
    scan_engines: str = (
        "chatgpt=openai/gpt-5.4-mini,"
        "perplexity=perplexity/sonar,"
        "gemini=google/gemini-3.8-flash"
    )
    prompt_model: str = "openai/gpt-5.4-mini"
    analysis_model: str = "openai/gpt-5.4-mini"
    provider_timeout_seconds: float = 90
    provider_max_retries: int = 2
    scan_concurrency: int = 4
    # Seconds to wait before each retry of a failed provider call (PRD 59). Three delays = three retries.
    provider_retry_delays: str = "30,120,600"
    provider_max_parallel_per_engine: int = 2
    max_scans_per_day: int = 20  # per project (PRD 60-61)
    rate_limit_enabled: bool = True
    login_rate_limit_per_minute: int = 5  # per IP (PRD 60)
    api_rate_limit_per_minute: int = 100  # per user (PRD 60)
    waitlist_rate_limit_per_minute: int = 10  # per IP; the endpoint is public
    # Empty = run scans in-process (local dev). Set = Celery workers on Redis (PRD 56).
    redis_url: str = ""

    max_competitors: int = 5
    max_active_prompts: int = 50

    cors_origins: str = "http://localhost:3000"

    # Report email delivery (Resend). Empty key = sending is disabled and the API says so.
    resend_api_key: str = ""
    email_from: str = "AnswerIntel <reports@answerintel.app>"

    model_config = {
        "env_file": ".env",
        "extra": "ignore",
    }

    @property
    def retry_delays(self) -> list[float]:
        return [float(d) for d in self.provider_retry_delays.split(",") if d.strip()]

    @property
    def ai_enabled(self) -> bool:
        return bool(self.openrouter_api_key.strip())


settings = Settings()
