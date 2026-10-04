from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30

    openrouter_api_key: str

    model_config = {
        "env_file": ".env",
        "extra": "ignore",
    }


settings = Settings()