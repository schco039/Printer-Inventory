"""Konfiguration aus Umgebungsvariablen (.env)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Verzeichnis für DB, Uploads und Backups. Im Container: /data
    data_dir: Path = Path("./data")

    # Secret für Badge-HMAC und Sessions. MUSS in Produktion gesetzt sein.
    app_secret: str = "dev-only-insecure-secret"

    default_locale: str = "fr"
    tz: str = "Europe/Luxembourg"

    # Tägliches SQLite-Backup (in Tests abgeschaltet)
    backup_enabled: bool = True

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path.as_posix()}"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.upload_dir, self.backup_dir):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
