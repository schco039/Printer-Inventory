"""PIN-Verfahren.

Ein vierstelliger PIN hat 10 000 Möglichkeiten. Kein Hashverfahren der Welt
macht das gegen automatisiertes Durchprobieren sicher — der eigentliche Schutz
ist die Sperre nach mehreren Fehlversuchen (siehe `pruefe_anmeldung`).
Gespeichert wird trotzdem gehasht, damit ein Blick in die Datenbank nicht
sämtliche PINs offenlegt.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from app.models import AppUser

ITERATIONEN = 200_000
PIN_LAENGE_MIN = 4
PIN_LAENGE_MAX = 12

# Sperre: nach so vielen Fehlversuchen für so lange
MAX_ECHECS = 5
SPERRE_MINUTEN = 5


class PinFehler(ValueError):
    """Fachlicher Fehler mit Meldung für die Oberfläche."""


def pin_pruefen_format(pin: str) -> str:
    """Nur Ziffern, Länge im erlaubten Bereich."""
    pin = (pin or "").strip()
    if not pin.isdigit():
        raise PinFehler("Le code ne peut contenir que des chiffres.")
    if not PIN_LAENGE_MIN <= len(pin) <= PIN_LAENGE_MAX:
        raise PinFehler(
            f"Le code doit comporter entre {PIN_LAENGE_MIN} et {PIN_LAENGE_MAX} chiffres."
        )
    return pin


def pin_hashen(pin: str) -> str:
    """PBKDF2-SHA256 mit zufälligem Salz. Format: algo$iter$salz$hash."""
    pin = pin_pruefen_format(pin)
    salz = secrets.token_hex(16)
    roh = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salz), ITERATIONEN)
    return f"pbkdf2_sha256${ITERATIONEN}${salz}${roh.hex()}"


def pin_stimmt(pin: str, gespeichert: str | None) -> bool:
    if not gespeichert or not pin:
        return False
    try:
        algo, iterationen, salz, erwartet = gespeichert.split("$")
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    roh = hashlib.pbkdf2_hmac(
        "sha256", pin.encode(), bytes.fromhex(salz), int(iterationen)
    )
    return hmac.compare_digest(roh.hex(), erwartet)


def pin_erzeugen(laenge: int = 4) -> str:
    """Zufälliger PIN für neue Personen — gleichverteilt, nicht 'raten-freundlich'."""
    return "".join(str(secrets.randbelow(10)) for _ in range(laenge))


# ─────────────────────────── Anmeldung ───────────────────────────────


def ist_gesperrt(user: AppUser, jetzt: datetime | None = None) -> bool:
    if user.bloque_jusqua is None:
        return False
    return (jetzt or datetime.now()) < user.bloque_jusqua


def sperre_restsekunden(user: AppUser, jetzt: datetime | None = None) -> int:
    if not ist_gesperrt(user, jetzt):
        return 0
    return max(1, int((user.bloque_jusqua - (jetzt or datetime.now())).total_seconds()))


def pruefe_anmeldung(user: AppUser | None, pin: str) -> tuple[bool, str]:
    """PIN prüfen und die Fehlversuchszählung fortschreiben.

    Gibt (erfolgreich, Meldung) zurück. Der Aufrufer muss committen.
    """
    if user is None or not user.actif:
        return False, "Identifiants incorrects."
    if not user.pin_hash:
        return False, "Aucun code n'est défini pour cette personne."
    if ist_gesperrt(user):
        return False, (
            f"Compte bloqué encore {sperre_restsekunden(user)} secondes "
            "après plusieurs essais incorrects."
        )

    if pin_stimmt(pin, user.pin_hash):
        user.echecs = 0
        user.bloque_jusqua = None
        return True, ""

    user.echecs = (user.echecs or 0) + 1
    if user.echecs >= MAX_ECHECS:
        user.bloque_jusqua = datetime.now() + timedelta(minutes=SPERRE_MINUTEN)
        user.echecs = 0
        return False, (
            f"Trop d'essais incorrects — compte bloqué {SPERRE_MINUTEN} minutes."
        )
    reste = MAX_ECHECS - user.echecs
    return False, f"Code incorrect. Encore {reste} essai(s) avant blocage."
