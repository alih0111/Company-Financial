from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(alias="DATABASE_URL")
    chromium_binary: str | None = Field(default=None, alias="CHROMIUM_BINARY")
    chromium_profile_dir: Path = Field(
        default=Path(".runtime/chromium-profile"),
        alias="CHROMIUM_PROFILE_DIR",
    )
    playwright_headless: bool = Field(default=False, alias="PLAYWRIGHT_HEADLESS")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    auto_create_schema: bool = Field(default=True, alias="AUTO_CREATE_SCHEMA")

    @field_validator("chromium_binary", mode="before")
    @classmethod
    def empty_binary_is_none(cls, value: object) -> object:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @property
    def resolved_profile_dir(self) -> Path:
        path = self.chromium_profile_dir
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path.resolve()

    @property
    def resolved_chromium_binary(self) -> Path | None:
        if not self.chromium_binary:
            return None
        path = Path(self.chromium_binary)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path.resolve()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
