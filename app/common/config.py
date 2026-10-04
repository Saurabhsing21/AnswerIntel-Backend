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

    max_competitors: int = 5
    max_active_prompts: int = 50

    cors_origins: str = "http://localhost:3000"

    model_config = {
        "env_file": ".env",
        "extra": "ignore",
    }

    @property
    def ai_enabled(self) -> bool:
        return bool(self.openrouter_api_key.strip())


settings = Settings()
