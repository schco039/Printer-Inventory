"""Badge-Hashing (M4).

Die rohe Karten-UID wird **nie** gespeichert und nie protokolliert. Gespeichert
wird nur HMAC-SHA256(UID, APP_SECRET). Damit ist die Datenbank auch bei
Diebstahl kein Werkzeug zum Klonen von Karten.

Wird APP_SECRET nachträglich geändert, passen alle gespeicherten Hashes nicht
mehr und sämtliche Badges müssen neu angelernt werden.
"""

from __future__ import annotations

import hmac
import re
from hashlib import sha256

from app.config import get_settings

# Reader liefern die UID je nach Modell mit Trennzeichen oder in Kleinschreibung.
_CLEAN = re.compile(r"[^0-9A-Za-z]")


def normalize_uid(raw: str) -> str:
    """Trennzeichen entfernen und vereinheitlichen: '04:a2:1b' == '04A21B'."""
    return _CLEAN.sub("", raw or "").upper()


def badge_hash(raw_uid: str) -> str:
    """HMAC der UID. Leere Eingabe ergibt einen leeren Hash (kein Treffer)."""
    uid = normalize_uid(raw_uid)
    if not uid:
        return ""
    secret = get_settings().app_secret.encode("utf-8")
    return hmac.new(secret, uid.encode("utf-8"), sha256).hexdigest()
