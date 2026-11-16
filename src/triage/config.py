from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class HelpdeskSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    helpdesk_base_url: str
    helpdesk_api_key: SecretStr
    candidate_email: str
    helpdesk_requests_per_second: float = Field(default=4.0, gt=0, le=5)
    helpdesk_timeout_seconds: float = Field(default=20.0, gt=0, le=120)

    @field_validator("helpdesk_base_url")
    @classmethod
    def _https_without_trailing_slash(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("must be an https:// URL")
        return value.rstrip("/")

    @field_validator("helpdesk_api_key")
    @classmethod
    def _key_is_present(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("is empty")
        return value

    @field_validator("candidate_email")
    @classmethod
    def _looks_like_an_email_address(cls, value: str) -> str:
        value = value.strip()
        local, at, domain = value.partition("@")
        if not (local and at and "." in domain) or any(char.isspace() for char in value):
            raise ValueError("must be the email address you applied with")
        return value


class ModelSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    groq_api_key: SecretStr
    gemini_api_key: SecretStr

    @field_validator("groq_api_key", "gemini_api_key")
    @classmethod
    def _key_is_present(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("is empty")
        return value


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: SecretStr

    @field_validator("database_url")
    @classmethod
    def _postgres_url(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().startswith(("postgresql://", "postgres://")):
            raise ValueError("must be a postgresql:// URL")
        return value
