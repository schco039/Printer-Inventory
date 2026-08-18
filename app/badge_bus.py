"""Vermittlung zwischen Kartenleser und Browser (PC/SC-Leser).

Ein PC/SC-Leser wie der Gemalto Prox-SU tippt nichts und ist für den Browser
unsichtbar. Ein kleiner Dienst am Gerät (tools/badge_agent.py) liest die Karte
und meldet die UID an den Server; die Seite im Browser fragt hier kurz zyklisch
nach, ob gerade eine Karte gelesen wurde.

Die rohe UID wird sofort zu ihrem HMAC verrechnet und verworfen — sie verlässt
den Server nie wieder. Der Browser bekommt nur ein kurzlebiges Einmal-Ticket.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass

# Wie lange eine Lesung auf ihre Abholung wartet
TTL_LESUNG = 20.0
# Wie lange ein ausgegebenes Ticket gültig ist
TTL_TICKET = 90.0

STATION_STANDARD = "default"


@dataclass
class _Lesung:
    digest: str
    zeit: float


_lock = threading.Lock()
_lesungen: dict[str, _Lesung] = {}
_tickets: dict[str, tuple[str, float]] = {}


def _aufraeumen(jetzt: float) -> None:
    for station, lesung in list(_lesungen.items()):
        if jetzt - lesung.zeit > TTL_LESUNG:
            del _lesungen[station]
    for ticket, (_digest, zeit) in list(_tickets.items()):
        if jetzt - zeit > TTL_TICKET:
            del _tickets[ticket]


def melden(station: str, digest: str) -> None:
    """Der Lesedienst meldet eine Karte. Ältere Lesung wird ersetzt."""
    jetzt = time.time()
    with _lock:
        _aufraeumen(jetzt)
        _lesungen[station or STATION_STANDARD] = _Lesung(digest=digest, zeit=jetzt)


def abholen(station: str) -> str | None:
    """Wartende Lesung in ein Einmal-Ticket verwandeln. Verbraucht die Lesung."""
    jetzt = time.time()
    with _lock:
        _aufraeumen(jetzt)
        lesung = _lesungen.pop(station or STATION_STANDARD, None)
        if lesung is None:
            return None
        ticket = secrets.token_urlsafe(24)
        _tickets[ticket] = (lesung.digest, jetzt)
        return ticket


def einloesen(ticket: str) -> str | None:
    """Ticket gegen den Badge-Hash tauschen. Jedes Ticket gilt nur einmal."""
    if not ticket:
        return None
    jetzt = time.time()
    with _lock:
        _aufraeumen(jetzt)
        eintrag = _tickets.pop(ticket, None)
        if eintrag is None:
            return None
        return eintrag[0]


def leeren() -> None:
    """Nur für Tests."""
    with _lock:
        _lesungen.clear()
        _tickets.clear()
