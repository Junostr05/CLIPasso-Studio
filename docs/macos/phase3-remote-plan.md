# Phase 3 · Handy-Fernbedienung in der Mac-App – Umsetzungsplan

**Ziel:** Die Mac-App bedient dieselbe Handy-Seite wie die Windows-App (`resources/phone/`). Das Handy kann
dieselben Dinge, und die Sicherheit ist dieselbe.
- Es gelten dieselbe API wie `gui/phone_api.py` und dieselben Regeln wie `gui/remote.py`:
  - Zugriff nur aus dem Heimnetz (auf Wunsch auch aus dem Tailnet).
  - Zugangscode aus dem QR-Code, danach als Cookie.
  - Änderungen brauchen den Code zusätzlich im Header `X-Access`.
  - Die PIN wird gebremst: pro Adresse, und für alle, wenn viele falsche PINs kommen.
  - Uploads sind begrenzt und müssen Bilder sein.
  - Kein Pfad vom Handy wird gelesen.
- **Swift macht alles.** Python rechnet nur, was es auch sonst rechnet (Aufträge, Masken, Pinselstile, Simplify).
- PIN und Zugangscode liegen im Schlüsselbund, nie in `settings.json`, Logs oder Diagnosen.

**Spec:** `docs/macos/plan.md` §6 (Zeile „Handy-Fernsteuerung“) · Python: `gui/remote.py`, `gui/phone.py`,
`gui/phone_api.py`, `gui/phone_ui.py` · Tests: `tests/test_phone.py`, `tests/test_phone_studio.py`,
`tests/test_phone_export.py`

## Regeln

- Die Seite selbst wird nicht kopiert oder geändert. Die App liefert dieselben Dateien aus `resources/phone/` aus
  (im Bundle unter `Resources/phone`). Icons, Schriften und `tokens.css` kommen wie bei Python.
- Jede Antwort ist so, wie `phone_api.py` sie gibt: dieselben Schlüssel und dieselben Fehlertexte. Geprüft wird das
  gegen Fixtures, die `tools/make_mac_fixtures.py` mit den Python-Funktionen erzeugt.
- Alles, was das Handy ändert, geht durch dieselben Modelle wie die Fenster (`AppModel`, `StudioModel`,
  `QueueModel` …). Das Fenster zeigt die Änderung sofort, und die Seite hört davon über `/api/events`.

## Schritte

- [x] **R1 · Grundlagen in StudioCore** (`Sources/StudioCore/Remote/`)
  - `RemoteAccess`: `allowedClient` (privat, link-local, loopback, IPv4 in IPv6; Tailnet 100.64/10 nur mit
    Schalter), Zugangscode (`token_urlsafe(18)`) und PIN (6 Ziffern).
  - `PinGuard`: 5 Versuche, dann 30 s Wartezeit, die sich bis 3600 s verdoppelt; 20 falsche PINs in 600 s sperren alle.
  - `RemotePage`: `index.html` und `login.html` gefüllt (Sprache, JSON-Konfiguration mit `<`, `>` und `&` als `\u003c` usw., Icons inline,
    Farben der Leiste), `tokens.css`, Manifest.
  - `RemoteEvents`: Revision, höchstens 8 Ströme (der älteste geht), Ping nach 15 s.
  - Tests gegen Fixtures (Seiten byte-gleich, Adressen, PIN-Bremse mit eigener Uhr).
- [x] **R2 · Der Server** (`RemoteServer`, Network.framework)
  - HTTP/1.1 mit Content-Length, `HEAD`, Server-Sent Events.
  - Wege wie `_Handler`: `/`, `/login`, öffentliche Dateien, Schriften, `/api/get|file|do`, `/api/status`,
    `/api/preview.svg`, `/api/events`, `/api/upload`, `/api/details`.
  - Kopfzeilen: CSP, `nosniff`, `no-referrer`, `no-store`.
  - Die Fälle aus `tests/test_phone.py` als Swift-Tests über echte Verbindungen (URLSession).
- [x] **R3 · In der App**
  - Einstellungen: Ein/Aus, Port, Tailnet, QR-Code (Core Image), Adresse, PIN neu.
  - Schlüsselbund.
  - Die Brücke zu `AppModel` (Aufrufe auf dem Main Actor, 20 s Zeitlimit → 503 „busy“).
  - Ein Upload geht in die Warteschlange oder ins Studio.
- [x] **R4 · Studio vom Handy** (`get_studio`, `get_schema`, `do_set`, `do_method`, `do_preset`, Start, Pause,
  Abbrechen, `file_sketch`, `file_input`, `set_image`, Voreinstellungen)
- [x] **R5 · Warteschlange, Ergebnisse, Galerie** (`get_queue`, `do_move`, `do_retry`, `do_run_next`,
  `get_results`, `do_fav`, `do_album`, `do_info`, `file_result`, `file_download`)
- [ ] **R6 · Der Rest**
  - [x] Maske und Detail-Pinsel (`do_mask_*`, `set_details`, `file_details`, `do_face`).
  - [x] Export (`get_export_info`, `do_export`, `get_export`, `file_export`, `do_cancel_export`).
  - [x] Modelle (`get_models` mit den Modellen nach Aufgabe aus der Engine-Abfrage `model_roles`,
    `do_download_models` als Download des Fensters, `do_cancel_download`, `do_remove_model`) und was im Studio
    fehlt (`missing`, `missing_mb`, je Methode).
  - [x] App-Einstellungen: die Sprache. Wach halten, Mitteilungen und Updates kommen mit ihren Teilen der App.
  - [ ] Vergleichen, Schritte, Vereinfachen – sobald die Mac-App sie hat.
  - Updates folgen mit Phase „Updates“.
- [x] **R7 · Testplan** (`docs/macos/testplan-mac.md`, Abschnitt Handy: iPhone und Android, QR-Code, PIN,
  Upload mit HEIC)
