"""Tägliches Backup der SQLite-Datenbank (M6).

Bewusst ohne zusätzliche Abhängigkeit: ein Hintergrund-Thread, der bis zur
nächsten Backup-Zeit schläft. `VACUUM INTO` erzeugt eine konsistente Kopie
auch bei laufendem Betrieb.

Das ersetzt kein externes Backup — `./data` gehört zusätzlich in die
Sicherung des Servers.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import text

from app.config import get_settings
from app.db import engine

log = logging.getLogger("lgk.backup")

BACKUP_HOUR = 2
KEEP_DAYS = 14


def run_backup() -> Path | None:
    settings = get_settings()
    settings.ensure_dirs()
    target = settings.backup_dir / f"db-{datetime.now():%Y-%m-%d}.sqlite"

    try:
        if target.exists():
            target.unlink()
        with engine.connect() as conn:
            conn.execute(text("VACUUM INTO :path"), {"path": target.as_posix()})
        log.info("Sauvegarde écrite : %s", target.name)
    except Exception:  # noqa: BLE001 - Backup darf den Betrieb nie stoppen
        log.exception("Échec de la sauvegarde")
        return None

    _prune(settings.backup_dir)
    return target


def _prune(directory: Path) -> None:
    limite = datetime.now() - timedelta(days=KEEP_DAYS)
    for old in directory.glob("db-*.sqlite"):
        try:
            if datetime.fromtimestamp(old.stat().st_mtime) < limite:
                old.unlink()
        except OSError:
            pass


def _seconds_until_next_run() -> float:
    now = datetime.now()
    nxt = now.replace(hour=BACKUP_HOUR, minute=0, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=1)
    return (nxt - now).total_seconds()


def _loop(stop: threading.Event) -> None:
    while not stop.wait(_seconds_until_next_run()):
        run_backup()


def start_scheduler() -> threading.Event:
    stop = threading.Event()
    thread = threading.Thread(target=_loop, args=(stop,), name="backup", daemon=True)
    thread.start()
    log.info("Sauvegarde quotidienne programmée à %02d:00", BACKUP_HOUR)
    return stop
