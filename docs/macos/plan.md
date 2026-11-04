# CLIPasso Studio für macOS – Plan (Phase 0)

Stand: 3. November 2026 · Basis: `main` v4.2.4 (f0ed122) · Branch: `claude/zealous-einstein-6vb48i`

Dieser Plan ist zur Freigabe gedacht. Bis zur Freigabe gibt es keinen Produktcode. Die offenen Entscheidungen
stehen in Abschnitt 11.

---

## 1. Was ich verstanden habe

**Von dir vorgegeben**
- Eine native macOS-App in SwiftUI. Alles, was in Swift gut geht, wird in Swift geschrieben. Python rechnet nur
  noch die Skizzen: die vier Methoden, Masken, CLIP-Score, „Vereinfachen“ und die Pinselstile.
- Die Qt-App ist die fachliche Vorlage. Umgesetzt wird Schritt für Schritt.
- Die Parameter werden nicht in Swift abgeschrieben, sondern als JSON aus `settings_schema.py` exportiert.
- Auftragsordner haben auf Mac und Windows dasselbe Format.
- Windows-Build und Release-Ablauf bleiben unverändert.
- Gebaut wird auf einem macOS-Runner von GitHub Actions. Es ist kein Mac über Remote Control verbunden
  (`list_computer_folders` ist leer).

**Meine Annahmen (bitte korrigieren, falls falsch)**
- Die Mac-App benutzt dieselben Orte wie `paths.py` unter macOS: `~/Library/Application Support/CLIPassoStudio`
  für Daten und Modelle, `~/Documents/CLIPasso Studio` für Ergebnisse. Das Repository ist öffentlich, die
  macOS-Runner kosten also nichts.
- Neue Texte, die nur der Mac braucht, kommen als `ui.mac.*` in `de.json` und `en.json`. Die Windows-App ignoriert
  sie.
- Englisch bleibt beim Wort „Preset“, so wie `en.json` es heute schon hat. Im Deutschen heißt es „Voreinstellung“.

**Woran wir den Erfolg messen**
1. Ein Auftrag läuft vom Mac aus, mit Live-Skizze, Pause und Abbrechen.
2. Ein Ordner, den die Python-App erzeugt hat, öffnet sich in der Mac-Galerie, auch mit Windows-Pfaden.
3. Was die Mac-App schreibt, liest die Python-App wieder.
4. Die exportierte PNG-Datei gleicht der aus der Qt-App, geprüft Pixel für Pixel mit Toleranz.
5. Der Kontrast wird gemessen: Text mindestens 4,5 : 1, Bedienteile mindestens 3 : 1.

---

## 2. Architektur

```
┌──────────────────────── CLIPasso Studio.app ────────────────────────┐
│  SwiftUI-App (nur macOS)                                             │
│    @Observable-Modelle auf dem MainActor: Studio, Galerie, Modelle   │
│  StudioCore (Swift-Package, ohne AppKit und SwiftUI)                 │
│    EngineClient   (actor): Hilfsprozess starten, überwachen, neu     │
│                            starten, Ausgabe lesen                    │
│    JobQueue       (actor): Reihenfolge, automatisch weiter,          │
│                            Pause, Abbruch, Fortsetzen                │
│    GalleryIndex   (actor): Ordner einlesen, suchen, filtern,         │
│                            sortieren                                 │
│    JobFolder, MetaStore:   Ordnerformat lesen und schreiben          │
│    ModelCatalog, ModelDownloader: fortsetzen, SHA-256, Platz,        │
│                            löschen                                   │
│    ParamSchema:            schema.json, Regeln „aktiv, wenn …“       │
│    SketchSVG:              SVG lesen und zeichnen (Core Graphics)    │
└────────────────────────────────┬─────────────────────────────────────┘
                     JSON-Zeilen │ stdin / stdout   (stderr = Protokolltext)
┌────────────────────────────────┴─────────────────────────────────────┐
│  python -m clipasso_studio.headless          (neu, ohne Qt)          │
│    → engine/runner.py  JobRunner, Worker-Prozesse, warmer Worker     │
│    → engine/methods/*  · model_store.convert · importance · scoring  │
└──────────────────────────────────────────────────────────────────────┘
```

**Warum ein Hilfsprozess mit JSON-Zeilen.** Ich habe drei Wege verglichen:

| Weg | Vorteil | Nachteil | |
|---|---|---|---|
| **A · `Process` + Pipes, JSON-Zeilen** | Ein Absturz von PyTorch trifft nur den Hilfsprozess. `runner.py` bleibt, wie er ist. Lässt sich auch unter Linux testen. | Das Protokoll muss gepflegt werden. | **Empfohlen** |
| B · XPC-Dienst | launchd startet ihn neu. | Braucht trotzdem eine Swift-Hülle, die Python startet. Ohne Sandbox bringt er keinen Gewinn. Nicht unter Linux testbar. | |
| C · Python im App-Prozess (C-API) | Kein Protokoll nötig. | Wenn der Speicher ausgeht oder PyTorch abstürzt, stürzt die App mit ab. GIL und MainActor geraten sich in die Quere. `spawn` aus dem App-Binary ist heikel. | |

**Aufbau im Repository**
```
macos/
  Package.swift                StudioCore + StudioCoreTests (swift build / swift test, auch unter Linux)
  Sources/StudioCore/…
  Tests/StudioCoreTests/…      Fixtures, die Python erzeugt (Abschnitt 5)
  App/CLIPassoStudio.xcodeproj App-Ziel; Ordner werden synchronisiert (Xcode 16+), bindet StudioCore lokal ein
  App/CLIPassoStudio/…         SwiftUI
  scripts/                     build_python.sh · make_app.sh · make_dmg.sh
clipasso_studio/headless/      neu: __main__.py · protocol.py · server.py · export.py
tests/test_headless_*.py       neu
.github/workflows/macos.yml    neu (build.yml bleibt unverändert)
```

---

## 3. Protokoll (Version 1)

- **Transport:** UTF-8, ein JSON-Objekt pro Zeile.
  - Auf **stdin** kommen die Anfragen.
  - Auf **stdout** gehen Antworten und Ereignisse.
  - **stderr** ist freier Protokolltext. Swift behält davon die letzten 2000 Zeilen für die Diagnose.
- **stdout bleibt sauber.** Der Hilfsprozess behält den echten stdout-Deskriptor für sich. fd 1 lenkt er auf
  stderr um, bevor die Worker starten. Kein `print` in einer Bibliothek kann so das Protokoll zerstören.
- **Anfrage:** `{"id": 12, "op": "start", "args": {…}}`
- **Antwort:** `{"id": 12, "ok": true, "result": {…}}` oder
  `{"id": 12, "ok": false, "error": {"code": "model_missing", "message": "…", "model": "clip:RN101"}}`
- **Ereignis:** `{"event": "iteration", "job": "j3", "data": {…}}`

| op | Phase | Zweck |
|---|---|---|
| `hello` | 1 | Protokoll, App-Version, PyTorch-Version, Geräte (`mps`, `cpu`) |
| `schema` | 1 | wie `--export-schema` (Abschnitt 4), für Prüfungen zur Laufzeit |
| `start` | 1 | `target`, `settings`, `output_root`; dazu `resume_dir` für *Fortsetzen*. Antwort: `job_dir`, `job` |
| `pause` · `resume` · `cancel` | 1 | wirken auf den laufenden Auftrag |
| `shutdown` | 1 | Auftrag als „unterbrochen“ markieren, Worker beenden, Prozess beenden |
| `convert_model` | 1b | Rohdatei, die Swift geladen hat → gespeichertes Format (`model_store.convert`, braucht PyTorch) |
| `smaller_settings` · `rerun_scene_cell` | 3 | Regeln, die heute in Python stehen, abgeschrieben wird nichts |
| `clip_score` · `importance` · `mask` · `brush_render` · `selftest` | 3 | die übrigen Rechen-Teile |

- **Ereignisse:** Sie heißen wie in der Engine und tragen dieselben Felder: `job_start`, `stage`, `input`,
  `attention`, `condition`, `iteration`, `preview` (SVG-Text), `seed_done`, `log`, `warning`, `error`,
  `job_done`, `job_failed`, `job_ended`.
  - Bytes werden als Base64 übertragen (`png_b64`).
  - `iteration` wird auf höchstens 10 pro Sekunde und Skizze gedrosselt. Die letzte Meldung einer Skizze kommt
    immer an.
- **Lebenszyklus:**
  - Schließt sich stdin (die App ist weg), bricht der Hilfsprozess ab, markiert den Auftrag als „unterbrochen“
    (wie `JobRunner.kill`) und endet innerhalb von 5 s.
  - Stirbt der Hilfsprozess während eines Auftrags, startet Swift ihn neu: nach 1 s, 2 s, 4 s … höchstens 30 s.
    Nach 3 Abstürzen in 2 Minuten hört Swift auf und zeigt den Fehler.
  - Der Auftrag lässt sich dann *fortsetzen*.
- **Version:** `hello` meldet `protocol: 1`. Weicht die Hauptversion ab, startet Swift keinen Auftrag.

---

## 4. Parameter und Voreinstellungen als JSON

`python -m clipasso_studio.headless --export-schema schema.json` läuft beim Bauen. Die Datei kommt in die `.app`.
Sie enthält pro Methode:

- **Parameter:** `key`, `kind`, `default`, `min`, `max`, `step`, `decimals`, `choices`, `group`, `advanced`, `hidden`
- **Textschlüssel:** `label`, `help`, `choice.*`, schon aufgelöst wie `param_text_key`
- **Ordnung:** Gruppen und Voreinstellungen
- **`enabled_if`:** die Regel, als Ausdruck

**Die Regeln „aktiv, wenn …“** sind heute Lambdas. Die lassen sich nicht exportieren.
- **Umbau:** Ich ersetze sie in `settings_schema.py` durch einen kleinen deklarativen Typ, zum Beispiel
  `All(On("attention_init"), Eq("saliency_model", "clip"))`.
- **Aufrufbar wie bisher:** Der Typ bleibt aufrufbar. Qt-App, CLI und `is_enabled` ändern sich nicht.
- **Absicherung:** Vor dem Umbau schreibt ein Test die alten Ergebnisse für alle Parameter und etwa 2000 erzeugte
  Einstellungen fest. Nach dem Umbau müssen sie gleich sein. Swift wertet dieselben Ausdrücke aus und wird gegen
  dieselbe Wahrheitstabelle getestet.
- **`normalize`:** Das letzte Wort hat Python, denn `start` normalisiert. Swift begrenzt die Regler nur mit den
  exportierten Grenzen.

---

## 5. Auftragsordner – dasselbe Format

**Swift liest** alles, was `engine/jobs.py` schreibt:
- `job_state.json`, `job.json`, `meta.json`
- `<lauf>/result.json`, `<lauf>/best_iter.svg|png`, `edited.svg`, `<lauf>_best.svg`
- `input/`, `mask-edited.png`, `cell_seeds.json`

**Swift schreibt** nur:
- `meta.json` mit Favorit, Titel, Notizen, Schlagwörtern, Alben und Bewertungen (`META_KEYS`)
- den Status in `job_state.json` (zum Beispiel „unterbrochen“)

Beides atomar (tmp + rename) und im selben JSON-Stil (`indent=2`; bei `meta.json` Umlaute unmaskiert). Die
Zwischenstände (`checkpoint.pt`) fasst nur Python an.

**Pfade:** Die Ordner speichern absolute Pfade, auch Windows-Pfade wie `C:\Users\…\camel_…\best_iter.svg`. Swift
übernimmt `rebase()` genau, mit Backslashes und Laufwerksbuchstaben.

**Tests:**
- `tools/make_mac_fixtures.py` baut mit den Funktionen aus `jobs.py` echte Ordner: fertig, unterbrochen,
  SceneSketch, Version 2.x mit `source.*`, mit Windows-Pfaden. Swift testet daran.
- Danach schreibt Swift `meta.json`, und ein Python-Schritt im Workflow liest sie mit `jobs.read_meta`
  zurück.

**Was nicht im Ordner steht:** Die Reihenfolge der Alben und die eigenen Voreinstellungen stehen in der
`settings.json` der App. Die Mac-App übernimmt sie in Phase 3 beim Einspielen einer Sicherung.

---

## 6. Welche Funktion wo läuft

| Funktion der Qt-App | Künftig | Grund |
|---|---|---|
| Bild öffnen, ziehen, einfügen, zuletzt benutzt, Beispiele | Swift | Dateidialog, Drag & Drop, Zwischenablage. HEIC liest ImageIO selbst, `pi-heif` entfällt |
| Kamera | Swift | AVFoundation |
| Bild zuschneiden, drehen | Swift | reine Bildoperationen (Core Graphics) |
| Maske berechnen | Python | U2Net und BiRefNet laufen in PyTorch |
| Maske nachbessern, Detailpinsel | Swift malt, Python legt ab | Der Ablageort hängt vom Bildinhalt ab (`masking.edited_mask_path`) |
| Porträt-Modus (Gesichter) | Python | BlazeFace in PyTorch |
| Methode, Voreinstellung, eigene Voreinstellungen | Swift | aus `schema.json` |
| *Anpassen* (alle Parameter) | Swift | Regler aus `schema.json`, nichts abgeschrieben |
| Live-Skizze, Auswahl der Skizzen eines Auftrags | Swift | `preview` liefert SVG. Die Pfade sind einfach (M/L/Q/C/Z, runde Enden), Core Graphics zeichnet sie gleich |
| Ansichten Aufmerksamkeit, Maske, Bedingung | Swift zeigt, Python rechnet | PNG aus den Ereignissen |
| Skizze bearbeiten (Radierer, Stift, Striche) | Swift | Vektorarbeit an `edited.svg` |
| Zwischenstände, beste Skizze wählen | Swift | Dateien wie `jobs.set_best_run` |
| SceneSketch-Matrix, Zelle neu rechnen | Swift zeigt, Python (`rerun_scene_cell`) | Die Regeln kennt `settings_schema` |
| Vereinfachen (Wichtigkeit der Striche) | Python | braucht CLIP |
| CLIP-Score | Python | braucht CLIP |
| Pinselstile | Python | bis Swift sie nachweislich gleich zeichnet |
| Papier | Swift | Core Graphics, mit Pixelvergleich gegen Qt |
| Vergleichen (mehrere Methoden) | Swift steuert, Python rechnet | |
| Warteschlange, automatisch weiter, „wenn fertig“ | Swift (`actor`) | |
| Pause, Abbrechen, Fortsetzen, Fortschritt, Restzeit | Swift | Die Restzeit kommt aus den `iteration`-Ereignissen der Engine |
| Bei Speichermangel kleiner rechnen | Python (`smaller_settings`) | Regel über Parameter, nicht abschreiben |
| Galerie: suchen, filtern, sortieren, Favoriten, Alben, Titel, Schlagwörter, Notizen, Bewertungen | Swift | nur Dateien |
| Betrachter, Diashow | Swift | |
| Export SVG (Farbe, Strichbreite, Hintergrund) | Swift | Text |
| Export PNG, PDF | Swift | Core Graphics |
| Export GIF | Swift | ImageIO |
| Export MP4 | Swift | AVFoundation |
| Export WebP | Python (Pillow) | ImageIO kann WebP nur lesen |
| Drucken | Swift | NSPrintOperation / PDF |
| Modelle: Liste, Download, Fortsetzen, Prüfsumme, Platz, Löschen, Import, Ordner verschieben | Swift | URLSession, Dateien |
| Modell nach dem Download umwandeln | Python (`convert_model`) | fp16, TorchScript → state_dict, safetensors: braucht PyTorch |
| Selbsttest | Swift zeigt, Python rechnet | |
| Einstellungen der App | Swift | dieselbe `settings.json` am selben Ort und mit denselben Schlüsseln. Geheimnisse liegen im Schlüsselbund |
| Ordner beobachten (Hot-Folder) | Swift | FSEvents |
| Mitteilung bei fertigem Auftrag | Swift | UserNotifications |
| Energiesparmodus verhindern | Swift | `ProcessInfo.beginActivity` / IOPMAssertion |
| Fortschritt in der Taskleiste | Swift | Fortschritt am Dock-Symbol |
| Telegram | Swift | URLSession. `telegram_token` liegt im Schlüsselbund |
| Handy-Fernsteuerung | Swift | Network.framework. Dieselbe Seite aus `resources/phone/`, dieselbe API wie `phone_api.py`, PIN und Zugangscode im Schlüsselbund |
| Updates | Swift | hängt am Signieren (Abschnitt 11) |
| Sicherung und Wiederherstellung | Swift | dasselbe Zip-Format wie `backup.py` |
| Fehlerbericht, Diagnose | Swift; Python liefert Gerät und Versionen | ohne `telegram_token`, `remote_token`, `remote_pin` |
| Erste Schritte (Tour) | Swift | |
| GPU-Laufzeit | entfällt | nur CUDA unter Windows |
| Einzelinstanz | entfällt | Das macht macOS selbst |

---

## 7. Gerät: `mps`

- **Heute:** Die Engine kennt `device` ∈ {`auto`, `cpu`, `cuda`} (`pipeline.resolve_device` und einige Stellen in
  `masking.py` und den Methoden).
- **Neu:**
  - Die Wahl `mps` kommt dazu. Fehlt MPS, rechnet die Engine mit Warnung auf der CPU, wie heute bei `cuda`.
  - `auto` wählt `cuda` → `mps` → `cpu`. `mps` gilt aber nur für die Methoden, bei denen es **gemessen**
    schneller ist und gleich gut bleibt (Liste `MPS_AUTO` im Code, gefüllt aus der Messung).
  - Der Hilfsprozess setzt `PYTORCH_ENABLE_MPS_FALLBACK=1`, damit fehlende Operationen auf der CPU laufen.
- **Kompatibilität:** Ein Mac-Auftrag mit `mps`, den man unter Windows öffnet, darf nicht scheitern. Deshalb kennt
  das Schema `mps` überall. Die Qt-App zeigt die Wahl nur unter macOS.
- **Messung:** `tools/bench_device.py` rechnet jede Methode an `benchmarks/images` auf `cpu` und auf `mps` und
  misst die Sekunden pro Iteration, die Gesamtzeit und den CLIP-Score – zusätzlich bewertet derselbe CLIP-Richter auf
  der CPU jede Skizze (`cpu_clip_score`), weil jedes Gerät sonst seine eigenen Skizzen benotet. Läuft im macOS-Workflow
  auf Anforderung (*Run workflow* oder `[bench]` in der Commit-Nachricht).
- **Gemessen** (GitHub-Runner `macos-26`, Apple Silicon, MPS vorhanden; je Bild ein Durchlauf, 200 Iterationen):

  | Methode | CPU | MPS | CPU-Richter: CPU / MPS |
  |---|---|---|---|
  | CLIPasso | 1,37–1,72 s/Iteration | 3,80–9,21 s/Iteration (2,6–6,7× langsamer) | 47,0–53,1 / 49,8–53,1 |
  | SwiftSketch | 0,040–0,090 s/Schritt | 0,020–0,048 s/Schritt (2–3×) | 60,8–69,7 / 60,1–67,9 |

  - CLIPasso auf MPS: Der erste Fehler (`view size is not compatible …`) kam vom `channels_last`-Layout – CLIP
    nutzt es jetzt nur noch auf CPU und NVIDIA. Danach fehlt MPS eine Operation
    (`_upsample_bilinear2d_aa_backward`, die Ableitung der geglätteten Verkleinerung in den Augmentierungen); mit
    `PYTORCH_ENABLE_MPS_FALLBACK=1` (setzt die Engine) rechnet sie auf der CPU – die Tests laufen damit, aber jede
    Iteration wird 2,6–6,7× langsamer als auf der CPU allein.
  - SwiftSketch auf MPS: 2–3× schneller, aber der CPU-Richter bewertet die Skizzen auf allen drei Bildern etwas
    schlechter (−0,7 bis −5,7). Gleich gut ist das nicht.
  - **Auffällig:** Der CLIP-Score, den ein Auftrag auf MPS selbst berechnet, liegt bei 90–96 für Skizzen, die der
    CPU-Richter mit 50–68 bewertet (CLIPasso 90,9 / 92,8 gegen 53,1 / 49,8) – als sähe CLIP auf MPS alle Bilder fast
    gleich. Weil dieser Score unter mehreren Skizzen die beste auswählt, rechnet ihn die Engine bei einem MPS-Auftrag
    jetzt auf der CPU (`scoring.get_scorer`). Die Messung vergleicht außerdem die CLIP-Merkmale derselben Bilder auf
    MPS und CPU (Kosinus, `clip_embedding` / `clip_pairs`), damit sich die Ursache eingrenzen lässt.
  - **Folge:** `MPS_AUTO` bleibt leer – *Auto* rechnet auf dem Mac auf der CPU; *mps* lässt sich pro Auftrag
    wählen.

---

## 8. Python und PyTorch in der `.app`

- **Python:** CPython 3.12 aus *python-build-standalone* (aarch64-apple-darwin, `install_only_stripped`). Diese
  Builds lassen sich verschieben. Version und SHA-256 sind festgeschrieben.
- **Pakete:**
  - torch 2.11.0, torchvision 0.26.0 sowie numpy, pillow, ftfy, regex, psutil
  - diffusers, transformers, tokenizers, safetensors, huggingface_hub, accelerate (für ControlSketch)
  - **ohne** PySide6, segno, imageio-ffmpeg und pi-heif. Diese Aufgaben übernimmt Swift.
  - Festgeschrieben mit Hashes in `requirements/lock-macos.txt` (neu).
- **Ort:**
  - `Contents/Resources/python/`: Interpreter und site-packages
  - `Contents/Resources/engine/clipasso_studio/`: nur die Engine, `settings_schema`, `paths`, `logs`, `fileops`,
    `headless` und die Ressourcen der Engine
- **Start:** `python3 -s -m clipasso_studio.headless` mit bereinigter Umgebung, `PYTHONPATH` auf `engine/` und
  `CLIPASSO_DOWNLOADS_DIR` auf den Modellordner.
- **Verkleinern:** `torch/include`, `torch/testing/_internal`, `torch/bin` und die Testordner kommen raus. Danach
  läuft `compileall`.
- **Signieren:** Jede `.dylib`/`.so` wird von innen nach außen signiert. Auf Apple Silicon reicht ohne Account
  eine Ad-hoc-Signatur, mit Account folgt die Developer-ID-Signatur.

**Größe, gemessen** an den heutigen macOS-arm64-Wheels, entpackt:

| Teil | MB |
|---|---|
| torch 2.11.0, davon `libtorch_cpu.dylib` 217 MB | 345 |
| transformers 49 · sympy 27 · diffusers 26 · numpy 19 · pillow 13 · tokenizers 10 · torchvision 6 · Rest ≈ 25 | ≈ 175 |
| site-packages zusammen, nach dem Verkleinern (−≈ 40 MB) | **≈ 480** |
| Python selbst (wird in der CI gemessen) | ≈ 60–80 |
| Swift-App | ≈ 15 |
| **`.app` ohne Modelle** | **≈ 560** |
| **DMG** (komprimiert, wird in der CI gemessen) | **≈ 200–250** |
| *zum Vergleich:* die 6 Modelle, die der Windows-Build mitliefert (CLIP RN101 + ViT-B/32, U2Net, DINO, VGG, BlazeFace) | +≈ 800 → `.app` ≈ 1,4 GB |

---

## 9. Swift-Seite: Grundsätze

Nach den Skills *swiftui-macos* und *liquid-glass*:
- **Sprache:** Swift 6.2 mit strikter Concurrency. Das App-Ziel ist per Voreinstellung auf dem MainActor isoliert.
  StudioCore arbeitet mit `actor`s und `Sendable`-Werten.
- **Kein `DispatchQueue` für Logik.** Ereignisse fließen als `AsyncStream` in die Modelle und werden mit `.task`
  an den Lebenszyklus der View gebunden.
- **`@Observable`-Modelle**, schmal geschnitten. Häufige Werte wie Fortschritt und Live-SVG liegen in eigenen,
  kleinen Objekten. So zeichnet ein Iterationsereignis nur die Fortschrittsleiste und die Skizze neu.
- **Liquid Glass nur für die Systemleisten:**
  - `NavigationSplitView` mit Seitenleiste (Studio · Galerie · Modelle) und Symbolleiste.
  - Die Auftragsleiste unten ist eine Systemleiste mit Standardknöpfen: *Skizze erstellen* als einzige
    hervorgehobene Aktion, dazu *Pause* und *Abbrechen*.
  - Kein Glas auf Karten, der Leinwand oder Listen. Der Linter des Skills läuft in der CI.
- **Farben:** Die Inhaltsebene benutzt die Tokens aus `theme.py`, dunkel und hell.
  - `tools/export_mac_tokens.py` erzeugt daraus `Tokens.swift`. Ein pytest prüft, dass die Datei aktuell ist.
  - Ein Swift-Test misst dieselben Kontrastpaare wie `test_theme_contrast.py`.
- **Bedienung:**
  - Jede Aktion ist per Tastatur erreichbar, Kürzel über `Commands`.
  - Jedes Bedienteil ohne sichtbaren Text hat einen VoiceOver-Namen.
  - Die Live-Skizze hat eine Beschreibung, zum Beispiel „Skizze, 16 Striche, Schritt 340 von 2001“.
  - „Bewegung reduzieren“ wird beachtet.

---

## 10. Phasen und erster Stand

**Phase 1 · Rechnung (Python, pytest hier im Container)**
- `clipasso_studio/headless`: Protokoll, Server, `--export-schema`, `--export-models`
- `start`, `pause`, `resume`, `cancel`, `shutdown`; dabei Fortschritt und Live-SVG
- Umbau der Regeln „aktiv, wenn …“ mit Gleichheitstest
- Tests:
  - Protokoll mit einem Stub-Runner (schnell)
  - ein echter kleiner CLIPasso-Auftrag auf der CPU, mit den Modellen, die `tools/fetch_models.py` lädt
  - Absturz und Neustart, stdin-Ende, Drosselung
- Danach `mps` und `tools/bench_device.py`

**Phase 1b · StudioCore (Swift-Package)**
- Inhalt: EngineClient, JobQueue, JobFolder/MetaStore, GalleryIndex, ModelCatalog/Downloader, ParamSchema,
  SketchSVG (nur Parsen)
- Geprüft hier mit der Linux-Toolchain (Swift 6.2 lässt sich laden), dazu auf dem macOS-Runner
- Prüfung der Fixtures in beide Richtungen

**Phase 2 · erster Stand der App** – mein Vorschlag:
- **Studio:**
  - *1 · Bild* (öffnen, ziehen, einfügen), *2 · Methode* (alle vier), *3 · Voreinstellung* (Schnell, Standard,
    Qualität) und *Anpassen* mit allen Parametern
  - In der Mitte die Live-Skizze, darunter die Skizzen des Auftrags
  - Unten: *Skizze erstellen*, *Pause* und *Weiter*, *Abbrechen*, Fortschritt und Restzeit
  - Unterbrochene Aufträge *fortsetzen*
- **Galerie:** Raster, Suche (Titel, Dateiname, Schlagwörter, Notizen, Methode), Filter nach Methode, Sortierung,
  im Studio öffnen
- **Export:** SVG und PNG
- **Modelle laden, wenn ein Auftrag sie braucht:** Abfrage mit Größe, Fortschritt, Fortsetzen und Prüfsumme. Das
  ist zusätzlich zu deiner Liste, aber ohne mitgelieferte Modelle läuft sonst kein einziger Auftrag.
- **Einstellungen:** Ausgabeordner, Sprache (Deutsch/Englisch), Erscheinungsbild (System, Hell, Dunkel)
- **Nicht im ersten Stand:** Warteschlangen-Seite (intern gibt es sie schon), Skizze bearbeiten,
  SceneSketch-Matrix (SceneSketch rechnet, gezeigt wird die beste Zelle), weitere Exporte, Masken und
  Detailpinsel, Vergleichen, Handy, Updates, Hot-Folder, Mitteilungen, Sicherung, Telegram, Drucken

**Phase 3 · der Rest**
- `macos.yml` baut `.app` und DMG als Artefakt. Das Gerüst dafür entsteht schon in Phase 1b, sobald es etwas zu
  bauen gibt.
- Danach in dieser Reihenfolge:
  1. Warteschlange, Bearbeiten der Skizze, SceneSketch-Matrix
  2. alle Exporte
  3. Masken und Detailpinsel
  4. Handy-Fernsteuerung
  5. Updates
  6. Rest der Tabelle

**Später, nur als Messung:** Masken über Core ML, SwiftSketch über MLX Swift. Übernommen wird ein Teil nur, wenn er
schneller ist und die Ergebnisse gleich gut bleiben.

**Der CI-Workflow `macos.yml`**
- **Auslöser:** Push auf diesen Branch (Pfade `macos/**`, `clipasso_studio/**`) und von Hand
- **Jobs:**
  1. `swift test` unter Linux
  2. `swift test` und `pytest tests/test_headless_*` auf macOS (arm64), dazu die Geräte-Messung
  3. `xcodebuild` (Build und Tests) mit Xcode 26 oder neuer; der Workflow wählt die neueste vorhandene Version
  4. Python einpacken, Ad-hoc-Signatur, DMG
  5. Artefakt `.dmg` mit gemessener Größe im Protokoll

---

## 11. Entscheidungen

**Getroffen am 3. November 2026, Plan freigegeben:**
- **macOS:** Ziel macOS 26, nur Apple Silicon. Gebaut wird mit dem 27-SDK, sobald der Runner Xcode 27 hat, sonst
  mit Xcode 26. APIs, die es erst ab 27 gibt, laufen hinter `#available`.
- **Signieren:** Kein Account. Die App bleibt unsigniert (ad hoc), mit Hinweis zu Gatekeeper. Updates: Die App
  meldet die neue Version und öffnet den Download.
- **Erster Stand:** größer als vorgeschlagen, also Abschnitt 10 und dazu die Seiten **Warteschlange** und
  **Modelle**.
- **Modelle:** Keine mitliefern, nur BlazeFace. Alle anderen lädt die App beim ersten Gebrauch.

Die ursprünglichen Fragen und Optionen:

1. **Mindest-Version von macOS.** Ich stimme deinem Vorschlag zu: **macOS 26, nur Apple Silicon.**
   - Es geht ohnehin nicht anders: PyTorch baut seit 2.3 nichts mehr für Intel-Macs. Die 2.11-Wheels gibt es nur
     für arm64.
   - macOS 26 bringt Liquid Glass und die aktuellen SwiftUI-APIs ohne `#available`-Zweige.
   - Der Preis: Wer noch macOS 15 hat, ist draußen.
2. **Signieren und Notarisieren.** Hast du einen Apple-Developer-Account (99 € im Jahr)?
   - **Ja:** Ich baue die Developer-ID-Signatur und die Notarisierung in den Workflow. Die Schlüssel kommen als
     Secrets ins Repository. Updates können dann still im Hintergrund laufen.
   - **Nein:** Die App bleibt unsigniert (nur ad hoc). Seit macOS 15 öffnet sie sich nicht mehr per Rechtsklick.
     Man muss in *Systemeinstellungen → Datenschutz & Sicherheit → Trotzdem öffnen* gehen (oder
     `xattr -dr com.apple.quarantine`). Ein Hinweis dazu kommt ins DMG und in die README. Updates heißen dann:
     Die App meldet die neue Version und öffnet den Download, die Installation läuft von Hand.
3. **Umfang des ersten Stands:** wie in Abschnitt 10 (deine Liste plus „Modelle laden bei Bedarf“), kleiner oder
   größer?
4. **Modelle mitliefern?** Ich empfehle, keine mitzuliefern. Alle werden beim ersten Gebrauch geladen: Das DMG
   bleibt bei ≈ 0,2 GB statt ≈ 1 GB, und der erste CLIPasso-Auftrag lädt ≈ 0,8 GB. BlazeFace (0,4 MB) liefere ich
   trotzdem mit.

## 12. Risiken

- **Ich ändere `settings_schema.py`** (Regeln „aktiv, wenn …“ und `mps`). Das ist Code, den auch Windows benutzt.
  Abgesichert wird es durch den Gleichheitstest und die bestehenden Tests. `build.yml`, `manifest.py` und
  `packaging/` fasse ich nicht an.
- **`multiprocessing` mit `spawn`** in einer verschobenen Python-Installation: Ich prüfe das im ersten CI-Lauf mit
  einem echten Auftrag in der gebauten `.app`.
- **MPS auf dem Runner:** siehe Abschnitt 7.
- **Ohne Signatur prüft Gatekeeper jede mitgelieferte `.dylib`.** Ich teste, ob die ad hoc signierte App nach dem
  Download aus dem Artefakt startet.
