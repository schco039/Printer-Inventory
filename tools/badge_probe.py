"""Prüfskript für PC/SC-Kartenleser (z. B. Gemalto Prox-SU).

Der Prox-SU ist ein Smartcard-Leser, keine Tastatur — er tippt nichts und ist
für den Browser unsichtbar. Dieses Skript spricht ihn über die richtige
Schnittstelle an und beantwortet drei Fragen:

  1. Wird der Leser gefunden?
  2. Erkennt er die Karte, und welche Nummer liefert er?
  3. Bleibt die Nummer bei jeder Lesung derselben Karte gleich?
     (Salto-Karten können eine zufällige UID senden — dann sind sie als
     Ausweis unbrauchbar.)

Aufruf (Windows, PowerShell):

    pip install pyscard
    python tools\badge_probe.py

Es wird nichts gespeichert und nichts gesendet.
"""

from __future__ import annotations

import sys

try:
    from smartcard.System import readers
    from smartcard.util import toHexString
except ImportError:
    print("Das Modul 'pyscard' fehlt. Bitte einmalig installieren:")
    print()
    print("    pip install pyscard")
    print()
    sys.exit(1)

from smartcard.Exceptions import CardConnectionException, NoCardException

# GET DATA — Standardbefehl, mit dem PC/SC-Leser die Seriennummer
# einer kontaktlosen Karte liefern.
APDU_UID = [0xFF, 0xCA, 0x00, 0x00, 0x00]

ANZAHL_LESUNGEN = 4


def hex_kompakt(daten) -> str:
    return toHexString(daten).replace(" ", "")


def main() -> int:
    liste = readers()
    print("=" * 62)
    print("Gefundene Kartenleser")
    print("=" * 62)
    if not liste:
        print("  KEINER.")
        print()
        print("  Prüfen: Ist der Leser eingesteckt? Läuft der Dienst")
        print("  'Smartcard' (SCardSvr)? In PowerShell als Administrator:")
        print("      Start-Service SCardSvr")
        return 1

    for i, r in enumerate(liste):
        print(f"  [{i}] {r}")

    leser = liste[0]
    if len(liste) > 1:
        print()
        antwort = input(f"Welcher Leser? [0-{len(liste)-1}], Enter für 0: ").strip()
        if antwort.isdigit() and int(antwort) < len(liste):
            leser = liste[int(antwort)]

    print()
    print("=" * 62)
    print(f"Karten lesen mit: {leser}")
    print("=" * 62)
    print(f"Bitte {ANZAHL_LESUNGEN}× DIESELBE Karte auflegen und wieder wegnehmen.")
    print("Zwischen den Lesungen die Karte kurz entfernen. Abbruch mit Strg+C.")
    print()

    gelesen: list[str] = []
    verbindung = leser.createConnection()

    try:
        while len(gelesen) < ANZAHL_LESUNGEN:
            try:
                verbindung.connect()
            except (NoCardException, CardConnectionException):
                continue

            try:
                atr = hex_kompakt(verbindung.getATR())
                daten, sw1, sw2 = verbindung.transmit(APDU_UID)
                nummer = hex_kompakt(daten)
                if (sw1, sw2) != (0x90, 0x00):
                    print(f"  Lesung {len(gelesen)+1}: Leser antwortet "
                          f"SW={sw1:02X}{sw2:02X} — Karte liefert keine Nummer über "
                          f"den Standardbefehl.")
                    print(f"               ATR: {atr}")
                else:
                    gelesen.append(nummer)
                    gleich = ""
                    if len(gelesen) > 1:
                        gleich = " (gleich wie vorher)" if gelesen[-1] == gelesen[-2] \
                                 else "  ← ANDERS als vorher!"
                    print(f"  Lesung {len(gelesen)}: {nummer}"
                          f"  [{len(daten)} Byte]{gleich}")
                    print(f"               ATR: {atr}")
            finally:
                try:
                    verbindung.disconnect()
                except Exception:
                    pass

            # Warten, bis die Karte weg ist
            while True:
                try:
                    verbindung.connect()
                    verbindung.disconnect()
                except Exception:
                    break

    except KeyboardInterrupt:
        print("\n  Abgebrochen.")

    print()
    print("=" * 62)
    print("Ergebnis")
    print("=" * 62)
    if not gelesen:
        print("  Keine Nummer gelesen.")
        print("  Möglich: Karte wird von diesem Leser nicht unterstützt")
        print("  (falsche Frequenz — 125 kHz gegenüber 13,56 MHz).")
        return 1

    verschieden = set(gelesen)
    print(f"  {len(gelesen)} Lesungen, {len(verschieden)} verschiedene Nummern.")
    print()
    if len(verschieden) == 1:
        print("  ✓ Die Nummer ist stabil — diese Karte ist als Ausweis brauchbar.")
        print(f"    Nummer: {gelesen[0]}")
    else:
        print("  ⚠ Die Nummer ändert sich bei jeder Lesung (zufällige UID).")
        print("    Diese Karte kann keine Person identifizieren.")
        for n in gelesen:
            print(f"      {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
