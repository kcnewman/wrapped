from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("data")
    log_level: str = "INFO"
    lastfm_api_key: str = field(default="", repr=False)
    telegram_token: str = field(default="", repr=False)
    telegram_owner_chat_id: str = field(default="", repr=False)
    smtp_password: str = field(default="", repr=False)
    smtp_user: str = field(default="", repr=False)
    owner_username: str = field(default="", repr=False)
    owner_password: str = field(default="", repr=False)

    @property
    def database_path(self) -> Path:
        return self.data_dir / "wrapped.db"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def job_lock_path(self) -> Path:
        return self.data_dir / "jobs.lock"

    @property
    def redactions(self) -> tuple[str, ...]:
        return (
            self.lastfm_api_key,
            self.telegram_token,
            self.smtp_password,
            self.smtp_user,
            self.telegram_owner_chat_id,
            self.owner_password,
        )


def load_settings() -> Settings:
    """Called by entrypoints only; importing configuration has no side effects."""
    load_dotenv()
    return Settings(
        data_dir=Path(os.getenv("WRAPPED_DATA_DIR", "data")),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        lastfm_api_key=os.getenv("LASTFM_API_KEY", ""),
        telegram_token=os.getenv("TELEGRAM_TOKEN", ""),
        telegram_owner_chat_id=os.getenv("TELEGRAM_OWNER_CHAT_ID", ""),
        smtp_password=os.getenv("SMTP_PASSWORD", ""),
        smtp_user=os.getenv("SMTP_USER", ""),
        owner_username=os.getenv("OWNER_USERNAME", ""),
        owner_password=os.getenv("OWNER_PASSWORD", ""),
    )
