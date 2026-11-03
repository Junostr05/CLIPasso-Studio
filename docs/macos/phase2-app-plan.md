# Phase 2 · Die SwiftUI-App (erster Stand) – Umsetzungsplan

> **Für ausführende Agenten:** Pflicht-Skills sind superpowers:executing-plans, superpowers:test-driven-development,
> swiftui-macos (Referenzen `observation.md`, `data.md`, `views.md`, `platform.md`, `accessibility.md`) und
> liquid-glass (Referenzen 01, 05, 08; Linter `scripts/check_glass.py --target 26.0` auf jede View-Datei). Für Texte
> gilt der Skill ux-copy, für die Prüfung accessibility-review. Schritte mit `- [ ]` abhaken.

**Ziel:** Eine unsignierte `CLIPasso Studio.app` (DMG als CI-Artefakt) für macOS 26 auf Apple Silicon mit Studio,
Warteschlange, Galerie, Modellen und Einstellungen. Der erste Stand ist der in `plan.md` §10 und §11 („größer“).

**Architektur:** Das App-Ziel (`macos/App`, Xcode-Projekt mit synchronisierten Ordnern) enthält nur Views und dünne
`@Observable @MainActor`-Modelle. Die Arbeit macht StudioCore (Phase 1b). Die Engine ist das mitgelieferte Python
(`Contents/Resources/python`, `engine/`).
- Liquid Glass gibt es nur in den Systemleisten:
  - `NavigationSplitView` mit Seitenleiste
  - Symbolleiste
  - die Auftragsleiste als `safeAreaBar(edge: .bottom)` mit Standardknöpfen
- Die Inhaltsebene benutzt die Tokens aus `theme.py`.

**Spec:** `docs/macos/plan.md` · Vorgänger: `phase1-engine-plan.md`, `phase1b-core-plan.md`

## Globale Vorgaben

- **Plattform:** macOS 26 (Deployment Target 26.0), arm64, Swift 6, App-Ziel mit `SWIFT_DEFAULT_ACTOR_ISOLATION = MainActor`.
  APIs von macOS 27 nur hinter `#available(macOS 27, *)`. Gebaut wird mit der neuesten Xcode-Version des Runners.
- **Texte** nur aus `de.json` und `en.json` (eigene als `ui.mac.*`): **Bild**, **Auftrag**, **Voreinstellung**. Sprache
  wie `settings.json` → `language` (`auto` | `de` | `en`).
- **Einstellungen:** `~/Library/Application Support/CLIPassoStudio/settings.json` mit den Schlüsseln der Python-App
  (`output_dir`, `models_dir`, `language`, `theme`, `queue`, `albums`). Geheimnisse kommen nie dorthin und nie ins Log.
- **Kontrast:** Text mindestens 4,5 : 1, Bedienteile mindestens 3 : 1, in beiden Themes, mit denselben Paaren wie
  `tests/test_theme_contrast.py`.
- **Bedienung:** Jede Aktion geht per Tastatur. Jedes Bedienteil ohne sichtbaren Text hat einen VoiceOver-Namen.
  „Bewegung reduzieren“ wird beachtet.
- **Glas:** nie Glas auf Glas, kein `glassEffect` auf Karten, Leinwand oder Listen. Der Glas-Linter läuft ohne Fehler.
- **Nicht im ersten Stand:** Skizze bearbeiten, Masken, Detailpinsel, Vergleichen, Handy, Updates, Hot-Folder,
  Mitteilungen, Sicherung, Telegram, Drucken, weitere Exporte (Phase 3).

## Review-Fokus

1. **Kein Python in der `.app`, oder es startet nicht:** Das Studio meldet „Rechnung nicht verfügbar“ samt
   stderr-Auszug, statt zu hängen → Task 4.
2. **Ein Bild mit Umlauten im Pfad** (`~/Bilder/Möwe.png`) rechnet → Task 6, als Test der App-Logik.
3. **Ein fehlendes Modell** (das erste Mal SwiftSketch) führt zum Download-Dialog und danach zum Start → Task 7.
4. **Dunkel ↔ hell während eines Auftrags:** Die Live-Skizze bleibt auf weißem Papier → Task 5, Snapshot beider Themes.
5. **VoiceOver auf der Leinwand:** „Skizze, 16 Striche, Schritt 340 von 2001“ → Task 6.

---

### Task 1: Tokens, Texte und Kontrast in StudioCore
- **Neu:**
  - `tools/export_mac_tokens.py`: Paletten, Abstände und Radien aus `gui/theme.py` sowie die Kontrastpaare aus
    `tests/test_theme_contrast.py` → `macos/Sources/StudioCore/Resources/tokens.json`
  - `StudioCore/Design/Tokens.swift`: Paletten mit Namen wie in `Palette`, `contrast(_:_:)` nach WCAG
  - `StudioCore/Text/Texts.swift`: `Texts(language:)` lädt `de.json`/`en.json` aus dem Bundle; `tr(key, params)` mit
    `{name}`-Ersetzung wie `gui/i18n.py`; Zahlen mit dem Dezimalzeichen der Sprache, wie `i18n.number` und
    `i18n.size`
- **Tests:**
  - `TokensTests.everyPairMeetsItsBar` (4,5 bzw. 3 aus `tokens.json`)
  - `TextsTests.placeholdersAndFallback` (ein fehlender Schlüssel → der englische Text, sonst der Schlüssel)
  - `TextsTests.numbersLikePython` (Fälle aus einer Fixture, die `i18n.number` und `i18n.size` erzeugt)
  - pytest `test_mac_tokens_current`

### Task 2: Xcode-Projekt, App-Gerüst, CI-Job `app`
- **Neu:**
  - `macos/App/CLIPassoStudio.xcodeproj`: synchronisierte Ordner `App/CLIPassoStudio`, Abhängigkeit StudioCore
    (lokal), Info.plist (Name, Bundle-ID `de.junostr05.clipasso-studio`, `LSMinimumSystemVersion 26.0`, Kategorie
    Grafik), ein Test-Ziel `CLIPassoStudioTests`
  - `CLIPassoStudioApp.swift`: `WindowGroup` mit `NavigationSplitView` (Studio · Warteschlange · Galerie · Modelle ·
    Einstellungen; Symbole wie in `resources/icons`, als SF Symbols), `Commands` mit ⌘O Bild öffnen, ⌘↩ Skizze
    erstellen, ⌘. Abbrechen
  - `AppModel` (`@Observable @MainActor`): besitzt `EngineClient`, `JobQueue`, `GalleryIndex`, `ModelDownloader`
    und `AppSettings`
- **CI:** In `macos.yml` kommt der Job `app` dazu: `xcodebuild -scheme CLIPassoStudio build test`, der Glas-Linter
  über `App/`, und das Artefakt `.app` (zunächst ohne Python).
- **Test:** `AppModelTests.startsWithoutEngine` (kein Python gefunden → Zustand `failed` mit Text, kein Absturz)

### Task 3: Einstellungen (Python-kompatibel)
- **Neu:** `StudioCore/Settings/AppSettings.swift`
  - liest und schreibt `settings.json` mit `PyJSON`
  - legt beim Schreiben `.bak` an wie `AppSettings._backup`
  - liest `.bak`, wenn die Hauptdatei kaputt ist (`paths.read_settings_file`)
  - kennt die Ordner `outputDir` (Standard `~/Documents/CLIPasso Studio`) und `modelsDir`
- **Tests:**
  - `AppSettingsTests.readsWhatPythonWrote` (Fixture)
  - `keepsUnknownKeys`
  - `damagedFileFallsBackToBackup`
  - `secretsNeverLogged` (die Beschreibung des Objekts nennt keine Geheimnisse)

### Task 4: Python in der `.app`
- **Neu:**
  - `macos/scripts/build_python.sh`: python-build-standalone 3.12 (Version und SHA-256 festgeschrieben),
    `pip install -r requirements/macos.txt --require-hashes` (aus `requirements/lock-macos.txt`, erzeugt mit
    `pip-compile` auf dem Runner), dann verkleinern (`torch/include`, `torch/testing/_internal`, `torch/bin`,
    `__pycache__`) und `compileall`
  - `macos/scripts/make_app.sh`: kopiert `python/` und `engine/clipasso_studio` (ohne `gui/` außer `methods_ui.py`),
    die Exporte `schema.json` und `models.json`, `resources/i18n`, BlazeFace. Danach ad hoc signieren, von innen
    nach außen: `codesign --force --sign - --timestamp=none`
  - `macos/scripts/make_dmg.sh`: DMG mit Hinweis zu Gatekeeper (Deutsch/Englisch)
- **App:** `EngineLaunch.bundled()` → `Contents/Resources/python/bin/python3 -s -m clipasso_studio.headless`,
  Umgebung bereinigt (`PYTHONPATH`, `CLIPASSO_DOWNLOADS_DIR`, `PYTORCH_ENABLE_MPS_FALLBACK`). Für Entwickler gibt es
  einen Rückfall: `python3` aus dem Repository, wenn `CLIPASSO_DEV_REPO` gesetzt ist.
- **CI:**
  - `.app` bauen, Größe messen (in die Zusammenfassung)
  - in der `.app` einen echten Mini-Auftrag rechnen (`hello`, `start` mit 5 Iterationen, `job_done`)
  - DMG als Artefakt
- **Test:** `EngineLaunchTests.bundledPathsAndEnvironment` (Umgebung ohne Geheimnisse, ohne Benutzer-`PYTHONPATH`)

### Task 5: Skizze zeichnen (Core Graphics), Export SVG und PNG
- **Neu:**
  - `StudioCore/Sketch/SketchRenderer.swift` (`#if canImport(CoreGraphics)`): `Sketch` → `CGPath`, runde Enden und
    Ecken, Deckkraft; `png(width:background:) -> Data`
  - `SketchView` in der App (`Canvas`): weißes Papier in beiden Themes (`paper`/`ink`)
  - Export: SVG wie `export.restyle_svg` (Farbe, Strichbreite, Hintergrund `data-bg`) und PNG
- **Test:** `SketchRendererTests.pngLikeQt`: Fixture-PNG aus Qt (`gui/export.py`, im Generator mit PySide6
  erzeugt); mittlere Abweichung ≤ 2 % pro Kanal, keine Kante, die fehlt. Läuft nur auf macOS, weil Core Graphics
  fehlt; unter Linux wird er nicht übersetzt.

### Task 6: Studio
- **Views:**
  - links die Schritte *1 · Bild* (öffnen, ziehen, einfügen; Vorschau), *2 · Methode* (Karten aus dem Schema: Name,
    `tagline`, `speed`) und *3 · Voreinstellung* (Segmente Schnell, Standard, Qualität, dazu *Anpassen* als
    `DisclosureGroup` pro Gruppe mit Reglern nach `kind`, ausgegraut nach `isEnabled`)
  - in der Mitte die Live-Skizze (`liveSVG` des laufenden Seeds) und darunter die Skizzen des Auftrags
  - unten die Auftragsleiste: *Skizze erstellen* (`.glassProminent`), *Pause*/*Weiter*, *Abbrechen*, Fortschritt
    und Restzeit
- **Modell:** `StudioModel` (`@Observable @MainActor`): Bild, Methode, Voreinstellung, Einstellungen (`JSONObject`)
  und ein Verweis auf den laufenden Auftrag; die häufigen Werte (Fortschritt, SVG) in einem eigenen kleinen
  `LiveJob`-Objekt.
- **Tests:**
  - `StudioModelTests.settingsFollowPresetAndClamp`
  - `startSendsTheSchemaSettings`
  - `umlautPath`
  - `canvasAccessibilityLabel`

### Task 7: Modelle laden, wenn ein Auftrag sie braucht; Seite Modelle
- **Ablauf:** Vor `start` wird `required_models` gefragt. Bei `missing` kommt ein Sheet mit Größen (`ui.models.*`):
  - *Laden* führt `ModelDownloader` mit Fortschritt aus, danach `convert_model`, danach den Start
  - *Abbrechen* lässt den Teil-Download für das nächste Mal liegen
- **Seite Modelle:** Liste aus dem Katalog mit Gruppen wie `model_group` (exportiert); Laden, Löschen, Größe,
  installiert oder nicht.
- **Tests:**
  - `ModelFlowTests.missingModelsAskThenStart` (mit Fake-Engine und Fake-Transport)
  - `cancelKeepsPartial`

### Task 8: Warteschlange und Galerie
- **Warteschlange:** Liste aus `JobQueue.updates`, umsortieren per Ziehen, entfernen, „von selbst starten“ und
  „wenn fertig“ (*nichts* / *Ruhezustand* / *Ausschalten*; die Aktion selbst kommt mit einer Rückfrage über
  NSWorkspace bzw. AppleScript), fortsetzen.
- **Galerie:**
  - `LazyVGrid` mit Vorschauen (`SketchView`), `.searchable`, Filter (Methode, Favoriten, Schlagwort, Album) und
    Sortierung als Menü in der Symbolleiste
  - Kontextmenü: im Studio öffnen, Favorit, Titel, Export SVG und PNG, im Finder zeigen, fortsetzen
- **Tests:**
  - `QueueModelTests.reorderAndWhenDone`
  - `GalleryModelTests.searchFiltersSort` (über `GalleryIndex`, schon in Phase 1b getestet; hier die Bindung an die
    View-Zustände)

### Task 9: Einstellungen, Prüfung, Feinschliff
- **Seite Einstellungen:** Ausgabeordner, Modellordner, Sprache, Erscheinungsbild (System, Hell, Dunkel).
- **Prüfung:**
  - accessibility-review: Kontrast gemessen, Tastaturwege, VoiceOver-Namen
  - design-critique an Screenshots aus der CI (`xcodebuild test` mit `XCUIScreenshot`, dunkel und hell, Deutsch und
    Englisch)
  - Glas-Linter
- **Doku:** Ein README-Abschnitt „Mac“ erklärt Installation, Gatekeeper und die Ordner.
