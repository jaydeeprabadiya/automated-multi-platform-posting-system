from functools import lru_cache
from typing import Optional

from pydantic import SecretStr, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Centralized application configuration.

    Loads configuration from environment variables
    and .env file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application Settings
    app_name: str = "Automated Multi-Platform Posting System"
    app_version: str = "1.0.0"
    debug: bool = False

    # HTTP Client Settings
    http_timeout: float = Field(default=30.0, gt=0)
    max_retries: int = Field(default=2, ge=0, le=5)

    # Facebook Configuration
    facebook_page_id: Optional[str] = None
    facebook_access_token: Optional[SecretStr] = None

    # Instagram Configuration
    instagram_user_id: Optional[str] = None
    instagram_access_token: Optional[SecretStr] = None

    # LinkedIn Configuration
    linkedin_author_urn: Optional[str] = None
    linkedin_access_token: Optional[SecretStr] = None

    # X (Twitter) Configuration
    x_access_token: Optional[SecretStr] = None

    # Reddit Configuration
    reddit_client_id: Optional[str] = None
    reddit_client_secret: Optional[SecretStr] = None
    reddit_username: Optional[str] = None
    reddit_password: Optional[SecretStr] = None
    reddit_user_agent: Optional[str] = None

    # Bluesky Configuration
    bluesky_handle: Optional[str] = None
    bluesky_app_password: Optional[SecretStr] = None

    # Mastodon Configuration
    mastodon_base_url: str = "https://mastodon.social"
    mastodon_client_id: Optional[str] = None
    mastodon_client_secret: Optional[SecretStr] = None
    mastodon_access_token: Optional[SecretStr] = None

    # Telegram Configuration
    telegram_bot_token: Optional[SecretStr] = None
    telegram_channel_id: Optional[str] = None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return a cached application settings instance.
    """
    return Settings()