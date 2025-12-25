from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    anthropic_api_key: str | None = None
    debug: bool = False
    github_webhook_secret: str | None = None
    github_token: str | None = None
    rate_limiting: bool = False
    rate_limit_requests: int = 120
    rate_limit_duration_in_seconds: int = 60
