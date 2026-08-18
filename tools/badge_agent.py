"""Lesedienst für PC/SC-Kartenleser (z. B. Gemalto Prox-SU).

Ein PC/SC-Leser ist kein Tastaturgerät: er tippt nichts und ist für den Browser
unsichtbar. Dieser kleine Dienst liest die Karte über die richtige
Schnittstelle und meldet die UID an den Server. Die Weboberfläche fragt dort
kurz zyklisch nach und bucht dann selbst.

Läuft auf dem Kiosk-Rechner (Raspberry Pi) und/oder am Verwaltungs-PC.

Installation
------------
    pip install pyscard

Aufruf
------
    python badge_agent.py --server http://192.168.1.10:8080 --token GEHEIM

    Weitere Schalter:
      --station kiosk      Name dieser Station, falls mehrere Leser existieren.
                           Die zugehörige Seite ruft man dann mit
                           ?station=kiosk auf.
      --reader Contactless Teil des Lesernamens, falls mehrere vorhanden sind.
      --once               Eine Karte lesen, ausgeben und beenden (Test).

Auf dem Raspberry Pi zusätzlich nötig:  sudo apt install pcscd
Als Dienst einrichten: siehe tools/lgk-badge-agent.service
"""

from __future__ import annotations

import argparse
import sys
import time

try:
    from smartcard.System import readers
    from smartcard.util import toHexString
except ImportError:
    print("Modul 'pyscard' fehlt.  pip install pyscard", file=sys.stderr)
    raise SystemExit(1)

import urllib.error
import urllib.parse
import urllib.request

# GET DATA: Standardbefehl für die Seriennummer kontaktloser Karten
APDU_UID = [0xFF, 0xCA, 0x00, 0x00, 0x00]


def leser_waehlen(muster: str):
    """Passenden Leser suchen, bis einer auftaucht."""
    gemeldet = False
    while True:
        gefunden = [r for r in readers() if muster.lower() in str(r).lower()]
        if gefunden:
            return gefunden[0]
        if not gemeldet:
            vorhanden = [str(r) for r in readers()]
            print(f"Kein Leser mit '{muster}' gefunden. Vorhanden: {vorhanden or 'keiner'}")
            print("Warte auf den Leser…")
            gemeldet = True
        time.sleep(3)


def uid_lesen(verbindung) -> str | None:
    try:
        verbindung.connect()
    except Exception:
        return None
    try:
        daten, sw1, sw2 = verbindung.transmit(APDU_UID)
        if (sw1, sw2) != (0x90, 0x00) or not daten:
            return None
        return toHexString(daten).replace(" ", "")
    except Exception:
        # Karte wurde während des Lesens weggezogen — kein Grund zur Sorge
        return None
    finally:
        try:
            verbindung.disconnect()
        except Exception:
            pass


def warten_bis_weg(verbindung) -> None:
    while True:
        try:
            verbindung.connect()
            verbindung.disconnect()
            time.sleep(0.2)
        except Exception:
            return


def melden(server: str, token: str, station: str, uid: str) -> bool:
    """Meldung an den Server — bewusst nur mit der Standardbibliothek,
    damit auf dem Raspberry Pi allein pyscard nachinstalliert werden muss."""
    daten = urllib.parse.urlencode({"uid": uid, "station": station}).encode()
    anfrage = urllib.request.Request(
        f"{server.rstrip('/')}/api/badge/scan",
        data=daten,
        headers={
            "X-Badge-Token": token,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(anfrage, timeout=5) as antwort:
            return antwort.status == 200
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            print("  Server lehnt den Token ab (BADGE_AGENT_TOKEN prüfen).")
        elif exc.code == 503:
            print("  Auf dem Server ist BADGE_AGENT_TOKEN nicht gesetzt.")
        else:
            print(f"  Server antwortet {exc.code}")
        return False
    except (urllib.error.URLError, OSError) as exc:
        print(f"  Server nicht erreichbar: {exc}")
        return False


def main() -> int:
    p = argparse.ArgumentParser(description="Kartenleser-Dienst für das Tonerlager")
    p.add_argument("--server", required=True, help="z. B. http://192.168.1.10:8080")
    p.add_argument("--token", required=True, help="Wert von BADGE_AGENT_TOKEN")
    p.add_argument("--station", default="default")
    p.add_argument("--reader", default="Contactless")
    p.add_argument("--once", action="store_true", help="eine Karte lesen und beenden")
    args = p.parse_args()

    leser = leser_waehlen(args.reader)
    print(f"Leser:   {leser}")
    print(f"Server:  {args.server}   Station: {args.station}")
    print("Bereit. Karten auflegen. Beenden mit Strg+C.\n")

    verbindung = leser.createConnection()
    letzte = None

    while True:
        uid = uid_lesen(verbindung)
        if uid and uid != letzte:
            letzte = uid
            gemeldet = melden(args.server, args.token, args.station, uid)
            print(f"Karte gelesen ({len(uid)//2} Byte) — "
                  f"{'an den Server gemeldet' if gemeldet else 'NICHT gemeldet'}")
            if args.once:
                return 0 if gemeldet else 1
            warten_bis_weg(verbindung)
            letzte = None
        time.sleep(0.25)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nBeendet.")
