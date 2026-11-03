# Phase 1b · StudioCore (Swift-Package) – Umsetzungsplan

> **Für ausführende Agenten:** Pflicht-Skill: superpowers:executing-plans (in dieser Sitzung, ohne Subagenten),
> superpowers:test-driven-development, swiftui-macos (Referenz `concurrency.md`). Schritte mit `- [ ]` abhaken.

**Ziel:** `macos/` ist ein Swift-Package `StudioCore` ohne AppKit und SwiftUI. Es enthält:
- die Steuerung des Hilfsprozesses
- die Warteschlange
- das Ordnerformat und den Galerie-Index
- das Parameter-Schema mit den Regeln
- die Modell-Downloads
- das Lesen der Skizzen-SVGs

`swift test` läuft unter Linux (hier) und auf macOS (CI).

**Architektur:** Zustand mit Nebenläufigkeit liegt in `actor`s (`EngineClient`, `JobQueue`, `GalleryIndex`,
`ModelDownloader`), Werte sind `Sendable`-Structs. Ereignisse fließen als `AsyncStream`. JSON wird mit einem kleinen
eigenen Parser gelesen und geschrieben (`PyJSON`): Er behält die Reihenfolge der Schlüssel und unterscheidet Int von
Double. Seine Ausgabe ist byte-gleich mit Pythons `json.dumps(…, indent=2, ensure_ascii=False)`.

**Technik:** Swift 6 (Sprachmodus 6, strikte Concurrency), `swift-tools-version: 6.2`, Plattform macOS 26, Swift
Testing.
- SHA-256 kommt auf macOS aus CryptoKit und unter Linux aus `swift-crypto` (Apples Paket, nur für Linux eingebunden).
- Sonst gibt es keine Abhängigkeiten.

**Spec:** `docs/macos/plan.md` (Abschnitte 2, 3, 5, 6, 9) · Vorgänger: `docs/macos/phase1-engine-plan.md`

## Globale Vorgaben

- Das Ordnerformat ist genau das von `engine/jobs.py`:
  - **Lesen:** `job.json`, `job_state.json`, `meta.json`, `<lauf>/result.json`, `edited.svg`, `<lauf>_best.svg`,
    `input/`.
  - **Schreiben:** nur `meta.json` (`META_KEYS` = favourite, title, notes, tags, albums, ratings) und den Status in
    `job_state.json`, atomar über `.tmp` und Umbenennen.
- `rebase()` wie in Python, auch für Windows-Pfade mit `\` und Laufwerksbuchstaben.
- Die Parameter werden nicht abgeschrieben. Alles kommt aus `schema.json` und `models.json` (Export aus Phase 1).
- Protokoll Version 1 wie in `clipasso_studio/headless/protocol.py`.
- Nie Geheimnisse (`telegram_token`, `remote_token`, `remote_pin`) in Logs oder im stderr-Puffer.
- Die Fixtures erzeugt Python, keine Datei wird von Hand geschrieben. Ein pytest prüft, dass sie aktuell sind.
- Tests werden nie übersprungen oder abgeschwächt.

## Review-Fokus

1. **Ein Ordner aus Windows** mit `C:\…`-Pfaden, Umlauten und einem fehlenden `best_svg` erscheint, und die Skizze
   wird gefunden → Fixture `jobs/windows_paths` (Task 4).
2. **Ein Hilfsprozess, der mitten in einer langen Zeile stirbt** oder Unsinn schreibt: Die Steuerung bleibt
   stabil, der Neustart folgt der Regel, offene Anfragen enden mit Fehler → Task 6.
3. **Ein abgebrochener Download** setzt an der richtigen Stelle fort. Liefert der Server die Range nicht, beginnt
   er neu. Bei einer falschen Prüfsumme wird die Datei gelöscht → Task 9 (Fake-Transport und lokaler Range-Server).
4. **Galerie mit 2000 Aufträgen:** Ein zweites Einlesen liest nur geänderte Ordner (wie `ScanCache` der
   Qt-Galerie) → Task 5.
5. **`meta.json` mit Umlauten und Emoji**, von Swift geschrieben, ist byte-gleich mit Pythons Ausgabe → Task 2/4.

---

### Task 1: Fixtures aus Python

**Dateien:**
- Neu: `tools/make_mac_fixtures.py`, `tests/test_mac_fixtures.py`
- Erzeugt: `macos/Tests/StudioCoreTests/Fixtures/…`
- Ändern: `clipasso_studio/headless/export.py`, dazu kommt pro Methode `strokes`, siehe unten

**Schnittstellen:** `python tools/make_mac_fixtures.py [--out DIR]` schreibt mit fester Zeit und festen Seeds,
damit alles reproduzierbar ist:
- `schema.json`, `models.json`: die Exporte aus Phase 1
- `conditions.json`: `[{method, settings, enabled: {key: bool}}]`, 300 Fälle pro Methode (Seed 0)
- `pyjson.json`: `[{value, text}]`. `text` ist `json.dumps(value, indent=2, ensure_ascii=False)`, mit Umlauten,
  Emoji, Floats (0.1, 1e-05, 1e+16, 100.0), leeren Containern und Verschachtelung.
- `jobs/`:
  - `done_clipasso`: 3 Läufe, `meta.json` mit Titel, Schlagwörtern, Alben und Bewertungen
  - `interrupted_swiftsketch`: nur `job_state.json` und ein `result.json`
  - `scenesketch_matrix`: Zellen `L8_level0` und `L8_level4`
  - `windows_paths`: absolute `C:\Users\Jürgen\…`-Pfade, das `best_svg` fehlt am alten Ort
  - `old_2x`: `source.png`, favourite in `job.json`
  - Alle Ordner werden mit den Funktionen aus `engine/jobs.py` gebaut: `make_job_dir`, `write_state`,
    `save_result`, `write_meta`. `job.json` wie `finish_job` (ohne aesthetic).
- `jobs_expected.json`: `{ordner: jobs.job_summary(ordner)}` mit Pfaden relativ zu `jobs/`
- `svg/`: drei Skizzen aus `svg_io.scene_to_svg` (gerade Linie, Quad, Kubik, geschlossen, mit Deckkraft) und
  `svg_expected.json` mit Punkten, Farben und Breiten

**Erweiterung des Exports:** `strokes` = `{"key": "num_paths" | "num_strokes" | null, "fixed": 32 | null,
"one_line": "one_line" | null}`, abgeleitet so, dass `schema.num_strokes` für jede Methode dasselbe ergibt. Ein Test
vergleicht das an 200 Einstellungen.

- [ ] **Schritt 1:** Tests schreiben:
  - `tests/test_mac_fixtures.py::test_fixtures_are_current` (erzeugt in `tmp_path`, vergleicht Datei für Datei mit
    `macos/Tests/StudioCoreTests/Fixtures`)
  - `test_headless_export.py::test_strokes_rule_matches_num_strokes`
- [ ] **Schritt 2:** pytest → FAIL.
- [ ] **Schritt 3:** Generator schreiben, Export ergänzen, Fixtures erzeugen.
- [ ] **Schritt 4:** pytest → PASS; ruff.
- [ ] **Schritt 5:** Commit „macOS: fixtures for StudioCore, made by the Python side“ und Push.

### Task 2: Package-Gerüst, `JSONValue`, `PyJSON`, CI-Job `core`

**Dateien:**
- Neu: `macos/Package.swift`, `macos/Sources/StudioCore/JSON/JSONValue.swift`,
  `macos/Sources/StudioCore/JSON/PyJSON.swift`, `macos/Tests/StudioCoreTests/PyJSONTests.swift`,
  `macos/Tests/StudioCoreTests/Support/Fixtures.swift`
- Ändern: `.github/workflows/macos.yml`
- `.gitignore`: `macos/.build/`

**Schnittstellen:**
- `public enum JSONValue: Sendable, Hashable { case null, bool(Bool), int(Int), double(Double), string(String),
  array([JSONValue]), object(JSONObject) }`
- `public struct JSONObject: Sendable, Hashable, Sequence`: geordnete Schlüssel; `subscript(key) -> JSONValue?`
  (get/set), `keys`, `init(_ pairs: [(String, JSONValue)])`; per Literal erzeugbar
- Bequemlichkeit: `.stringValue`, `.intValue`, `.doubleValue` (Int → Double), `.boolValue`, `.arrayValue`,
  `.objectValue`; dazu `truthy` mit Pythons `bool()`-Semantik
- `public enum PyJSON`:
  - `static func parse(_ data: Data) throws -> JSONValue`
  - `static func dump(_ value: JSONValue, indent: Int? = nil) -> String`
  - Mit `indent: nil` entsteht eine Zeile mit `", "` und `": "` wie `json.dumps(…)`, mit `indent: 2` wie
    `json.dumps(…, indent=2)`. Floats im kürzesten Round-Trip-Format wie Pythons `repr`.
  - Ganze Zahlen ohne Punkt bleiben `int`.
- `Fixtures.url(_ relative: String) -> URL` über `Bundle.module`
- CI-Job `core` auf `macos-26`:
  1. die neueste Xcode-Version wählen (`ls /Applications | grep Xcode`) und `xcodebuild -version` ausgeben
  2. `swift build` und `swift test` in `macos/`

- [ ] **Schritt 1:** Test `pyjsonMatchesPython` schreiben: Für jeden Fall aus `pyjson.json` ist
  `dump(parse(text), indent: 2) == text` und `parse(dump(v)) == v`. Dazu kommt `rejectsBrokenJSON` (Parametrisierung:
  abgeschnitten, Komma am Ende, ungültiges UTF-8).
- [ ] **Schritt 2:** `swift test` → FAIL (Kompilierfehler: Typen fehlen).
- [ ] **Schritt 3:** Umsetzen.
- [ ] **Schritt 4:** `swift build && swift test` hier → PASS. Push, dann den CI-Job `core` auf GitHub prüfen.
- [ ] **Schritt 5:** Commit „macOS: StudioCore package with a Python-compatible JSON reader and writer“ und Push.

### Task 3: Parameter-Schema und Regeln

**Dateien:**
- Neu: `macos/Sources/StudioCore/Schema/ParamSchema.swift`, `Condition.swift`
- Test: `ParamSchemaTests.swift`

**Schnittstellen:**
- `public struct ParamSchema: Sendable` mit `static func load(_ url: URL) throws -> ParamSchema` sowie `methods`,
  `defaultMethod`, `devices` und `method(_ id: String) -> MethodSchema?`
- `MethodSchema`: `name`, `icon`, `text`, `groups`, `groupText`, `presets: [String: JSONObject]`,
  `presetOrder`, `presetText`, `defaults: JSONObject`, `params: [Param]`, `strokes: StrokesRule`
- `Param`: `key`, `kind` (enum mit den Fällen int, float, bool, choice, text, path, layers, flags), `default`, `group`,
  `minimum`, `maximum`, `step`, `decimals`, `choices: [JSONValue]`, `advanced`, `hidden`, `enabledIf: Condition?`,
  `text: ParamText`
- `indirect enum Condition: Sendable` mit `on`, `off`, `eq(key, value, default)`, `ne`, `gt(key, Double)`,
  `has(key, String)`, `all([Condition])` und `any([Condition])`
  - `func evaluate(_ settings: JSONObject) -> Bool`, mit der Semantik aus `clipasso_studio/conditions.py`
- `MethodSchema.isEnabled(_ param: Param, in settings: JSONObject) -> Bool`
- `MethodSchema.applyPreset(_ name: String, to settings: JSONObject) -> JSONObject`
- `MethodSchema.clamp(_ param: Param, _ value: JSONValue) -> JSONValue` (Grenzen und Typ, wie `coerce` bei int
  und float)
- `MethodSchema.numStrokes(_ settings: JSONObject) -> Int`

- [ ] **Schritt 1:** Tests schreiben:
  - `everyConditionMatchesPython` (`conditions.json`)
  - `presetsAndDefaults` (Schnell, Standard, Qualität pro Methode gleich dem Export)
  - `clampFollowsCoerce` (Werte außerhalb der Grenzen, „3.7“ für int)
  - `numStrokesMatchesPython` (Fälle aus der Fixture)
- [ ] **Schritt 2:** `swift test` → FAIL.
- [ ] **Schritt 3:** Umsetzen.
- [ ] **Schritt 4:** `swift test` → PASS.
- [ ] **Schritt 5:** Commit „StudioCore: the parameter schema and its rules from schema.json“ und Push.

### Task 4: Auftragsordner und Meta

**Dateien:**
- Neu: `macos/Sources/StudioCore/Jobs/JobFolder.swift`, `JobSummary.swift`, `JobMeta.swift`, `Rebase.swift`
- Test: `JobFolderTests.swift`

**Schnittstellen:**
- `public enum JobFolder`:
  - `summary(at: URL) -> JobSummary?`, als Nachbau von `jobs.job_summary` samt `state` und `progress`
  - `readMeta(at:) -> JobMeta`
  - `writeMeta(at:, _ change: (inout JobMeta) -> Void) throws -> JobMeta`, atomar
  - `setStatus(at:, _ status: String) throws`
  - `canContinue(_ summary: JobSummary) -> Bool`
  - `bestSketch(_ summary: JobSummary, jobDir: URL) -> URL?`: `edited.svg` des besten Laufs vor `best_svg`
  - `savedInput(jobDir:, target:) -> URL?`: `input/<name>`, sonst `source.*`
- `public func rebase(_ path: String, jobDir: URL) -> String` wie `jobs.rebase`, mit Trennern `/` und `\`
- `JobSummary`: `target`, `created`, `settings: JSONObject`, `method`, `clipScore`, `bestSVG`, `bestRun`,
  `runs: [RunSummary]`, `state`, `progress: (done: Int, total: Int)?`, `seconds`, dazu `raw: JSONObject`
- `JobMeta`: `favourite`, `title`, `notes`, `tags`, `albums`, `ratings: [String: Int]`; unbekannte Schlüssel fallen
  weg wie in `read_meta`

- [ ] **Schritt 1:** Tests schreiben:
  - `summariesMatchPython` (`jobs_expected.json`, alle Fixture-Ordner, kopiert in ein temporäres Verzeichnis)
  - `windowsPathsAreRebased`
  - `metaRoundTripIsByteEqualToPython` (geschriebene `meta.json` == `PyJSON.dump(…, indent: 2)` der von Python
    erwarteten Daten)
  - `writeMetaKeepsOtherKeysAndRemovesNil`
  - `setStatusIsAtomic` (kein `.tmp` bleibt liegen)
- [ ] **Schritt 2:** FAIL.
- [ ] **Schritt 3:** Umsetzen.
- [ ] **Schritt 4:** PASS. Zusätzlich liest `tests/test_mac_fixtures.py::test_swift_written_meta_reads_in_python`
  eine `meta.json`, die `swift test` mit `STUDIOCORE_EXPORT_DIR` ablegt, mit `jobs.read_meta` zurück (im CI-Job
  `core` nach `swift test`, hier lokal genauso).
- [ ] **Schritt 5:** Commit „StudioCore: job folders – the same format as engine/jobs.py, Windows paths too“ und
  Push.

### Task 5: Galerie-Index

**Dateien:**
- Neu: `macos/Sources/StudioCore/Gallery/GalleryIndex.swift`, `GalleryItem.swift`, `GalleryQuery.swift`
- Test: `GalleryIndexTests.swift`

**Schnittstellen:**
- `public actor GalleryIndex`
  - `init(root: URL)`
  - `refresh() -> [GalleryItem]`: Ordner mit `job.json` oder `job_state.json`. Ein fertiger Auftrag wird nur neu
    gelesen, wenn sich `mtime` oder Größe einer seiner drei Dateien geändert hat; unfertige immer (wie `ScanCache`).
  - `items(_ query: GalleryQuery) -> [GalleryItem]`
  - `setFavourite`, `setTitle`, `setNotes`, `setTags`, `setAlbums`: über `JobFolder.writeMeta`
- `GalleryItem` (`Identifiable` über den Pfad): `name` (Titel, sonst der Dateiname des Bildes ohne Endung),
  `method`, `favourite`, `tags`, `notes`, `albums`, `created`, `score`, `seconds`, `strokes`, `bestSketch`
- `GalleryQuery`: `text`, `method` (`nil` = alle), `favouritesOnly`, `tag`, `album`, `sort`
  - `sort` ∈ `newest`, `oldest`, `score`, `duration`, `strokes`, `name`, wie `gallery.SORTS` und `sort_items`
  - Die Suche ist wie `GalleryItem.matches`: Wörter in Kleinschreibung, alle müssen vorkommen im Heuhaufen aus
    Name, Ordnername, Dateiname des Bildes, Methode, Methodenname, Schlagwörtern und Notizen.

- [ ] **Schritt 1:** Tests schreiben:
  - `scanFindsFixtureJobs`
  - `searchLikeTheQtGallery` (Fälle: Umlaut-Titel, Schlagwort, Methodenname „SwiftSketch“, zwei Wörter)
  - `sortOrders` (alle sechs)
  - `filters`
  - `secondRefreshReadsOnlyChanged` (2000 erzeugte Ordner, gezählte Lesevorgänge über einen injizierten Leser)
- [ ] **Schritt 2:** FAIL.
- [ ] **Schritt 3:** Umsetzen.
- [ ] **Schritt 4:** PASS.
- [ ] **Schritt 5:** Commit „StudioCore: the gallery index – search, filters and sorting like the studio“ und Push.

### Task 6: EngineClient (Hilfsprozess)

**Dateien:**
- Neu: `macos/Sources/StudioCore/Engine/EngineClient.swift`, `EngineMessage.swift`, `LineReader.swift`,
  `RestartPolicy.swift`
- Test: `EngineClientTests.swift`, `macos/Tests/StudioCoreTests/Support/fake_engine.py`

**Schnittstellen:**
- `public struct EngineLaunch: Sendable`: `executable: URL`, `arguments: [String]`, `environment: [String: String]`,
  `workingDirectory: URL?`
- `public struct EngineEvent: Sendable`: `kind`, `job: String?`, `data: JSONObject`
  - Dazu kommt das synthetische Ereignis `engine_exit` mit `{code, crashed}`.
- `public struct EngineFailure: Error`: `code`, `message`, mit Engine-Codes und eigenen (`engine_gone`, `timeout`,
  `protocol`)
- `public enum EngineState: Sendable`: `stopped`, `starting`, `running`, `restarting(attempt: Int)`,
  `failed(String)`
- `public actor EngineClient`
  - `init(launch: EngineLaunch, policy: RestartPolicy = .standard)`
  - `nonisolated let events: AsyncStream<EngineEvent>`
  - `state`
  - `start() async throws`: startet und wartet auf `hello`, prüft `protocol == 1`
  - `request(_ op: String, _ args: JSONObject = [:], timeout: Duration = .seconds(120)) async throws -> JSONValue`
  - `stop() async`: `shutdown`, nach 5 s `terminate`
  - `stderrTail() -> [String]`: die letzten 2000 Zeilen
- `RestartPolicy.standard`: Verzögerungen 1, 2, 4, 8, 16, 30 s; höchstens 3 Abstürze in 120 s, dann `failed`
- **Zeilenlesen:** `FileHandle.readabilityHandler` → `LineReader` (Puffer, `\n`, Zeilen beliebiger Länge) →
  `AsyncStream`. Offene Anfragen sind `CheckedContinuation`s nach `id`; stirbt der Prozess, enden sie mit
  `engine_gone`.

- [ ] **Schritt 1:** Tests schreiben. `fake_engine.py` hat die Modi `echo`, `crash_after`, `garbage`, `slow`,
  `huge_line` und `stderr_secret`.
  - `helloAndRequest`
  - `eventsArriveInOrder`
  - `garbageLineIsReportedNotFatal`
  - `hugeLineArrivesWhole` (8 MB)
  - `crashEndsPendingRequestsAndRestarts` (Uhr injiziert)
  - `threeCrashesIn120sFail`
  - `stopEndsTheProcess`
  - `realHeadlessHello`: startet `python3 -m clipasso_studio.headless` aus dem Repository, `hello` und
    `schema`, ohne PyTorch
- [ ] **Schritt 2:** FAIL.
- [ ] **Schritt 3:** Umsetzen.
- [ ] **Schritt 4:** PASS (Linux und macOS).
- [ ] **Schritt 5:** Commit „StudioCore: the engine process – start, requests, events, restart after a crash“ und
  Push.

### Task 7: Warteschlange

**Dateien:**
- Neu: `macos/Sources/StudioCore/Queue/JobQueue.swift`, `QueuedJob.swift`
- Test: `JobQueueTests.swift`

**Schnittstellen:**
- `public protocol EngineControlling: Actor` mit `events: AsyncStream<EngineEvent>` und `request(_:_:timeout:)`.
  `EngineClient` erfüllt es, im Test ein Fake.
- `public actor JobQueue`
  - `init(engine: any EngineControlling, outputRoot: URL)`
  - `nonisolated let updates: AsyncStream<QueueSnapshot>`
  - `add(target: URL, settings: JSONObject) -> QueuedJob.ID`
  - `addContinuation(jobDir: URL, target: URL, settings: JSONObject) -> QueuedJob.ID`, startet mit `resume_dir`
  - `remove(_:)`, `move(_:to:)`
  - `autoStart: Bool`, `whenDone: WhenDone` (`nothing`, `sleep`, `shutdown`)
  - `startNext() async throws`, `pause()`, `resume()`, `cancel()`
- `QueuedJob`: `id`, `target`, `settings`, `status` (`queued`, `running`, `paused`, `done`, `failed`, `cancelled`,
  `interrupted`), `jobDir`, `progress`, `eta`, `message`, `seedProgress`, `liveSVG: [Int: String]`,
  `bestSVG`
  - `progress` ist der Mittelwert über die Seeds aus `job_start.seeds`, jeweils `(it + 1) / total`; `seed_done` zählt
    als 1.
  - `eta` ist das letzte `iteration.eta`.
- Ereignis `engine_exit` während eines Auftrags → Status `interrupted`; der Auftrag lässt sich mit
  `addContinuation` fortsetzen.
- `QueueSnapshot` enthält `jobs` und `finished: WhenDone?`. Das wird gesetzt, wenn die Schlange von selbst leer
  wird, nicht nach einem Abbruch durch den Nutzer (wie `queue_idle`).

- [ ] **Schritt 1:** Tests schreiben:
  - `runsInOrderAndStartsNextByItself`
  - `autoStartOffWaits`
  - `progressAndEta`
  - `pauseResumeCancel`
  - `crashMarksInterruptedAndCanContinue`
  - `finishedOnlyWhenEmptiedByItself`
  - `liveSVGPerSeed`
- [ ] **Schritt 2:** FAIL.
- [ ] **Schritt 3:** Umsetzen.
- [ ] **Schritt 4:** PASS.
- [ ] **Schritt 5:** Commit „StudioCore: the job queue on the engine process“ und Push.

### Task 8: Modelle umwandeln (Python-Seite)

**Dateien:**
- Ändern: `clipasso_studio/engine/model_store.py` (`_install_hf` teilen in `download_hf_raw` und
  `convert_hf_raw`; neu `convert_downloaded(spec_key, dest_root) -> Path`), `clipasso_studio/headless/server.py`
  (op `convert_model`)
- Test: `tests/test_model_convert.py`, `tests/test_headless_server.py`

**Schnittstellen:**
- `convert_downloaded(spec_key, dest_root)`: nimmt die Rohdatei aus `.partial/` (`<safe_key>.part` bzw. den
  Ordner `<safe_key>/` mit `revision.txt`), so wie Python sie selbst ablegt, wandelt sie um und räumt `.partial`
  auf. Fehlt etwas, kommt `UserError("not_downloaded")`.
- op `convert_model {key, dest_root}` → `{path}`. `install()` und `_install_hf()` verhalten sich nach außen
  unverändert, das prüfen die bestehenden Tests.

- [ ] **Schritt 1:** Tests schreiben:
  - `test_convert_downloaded_blazeface` (kleine echte Datei aus `models/`, als `.part` abgelegt)
  - `test_convert_downloaded_hf_fp16_prefix` (ein erzeugter safetensors-Ordner)
  - `test_convert_missing_is_not_downloaded`
  - `test_convert_model_op`
- [ ] **Schritt 2:** FAIL.
- [ ] **Schritt 3:** Umsetzen.
- [ ] **Schritt 4:** `pytest tests/test_model_convert.py tests/test_model_store*.py tests/test_headless_server.py`
  → PASS.
- [ ] **Schritt 5:** Commit „model store: convert a download made elsewhere (the Mac app downloads, Python
  converts)“ und Push.

### Task 9: Modell-Katalog und Downloads (Swift)

**Dateien:**
- Neu: `macos/Sources/StudioCore/Models/ModelCatalog.swift`, `ModelDownloader.swift`, `HTTPTransport.swift`,
  `SHA256.swift`, `GoogleDrive.swift`
- Test: `ModelDownloaderTests.swift`, `Support/range_server.py`

**Schnittstellen:**
- `ModelCatalog`: `load(models.json)`, `spec(_ key)`, `installedURL(key, dirs: [URL]) -> URL?` (wie `find`),
  `spaceNeeded(key, root) -> Int64` (wie `space_needed`), `uninstall(key, root) throws`
- `protocol HTTPTransport: Sendable`: `func stream(_ url: URL, offset: Int64) async throws -> (status: Int,
  length: Int64?, bytes: AsyncThrowingStream<Data, Error>)`. Umgesetzt mit `URLSessionTransport`.
- `actor ModelDownloader`
  - `init(transport:, catalog:, root: URL)`
  - `download(_ key:, progress: @Sendable (Int64, Int64) -> Void) async throws -> URL` (die Rohdatei bzw. der
    Rohordner in `.partial`)
  - Ablage wie Python: `<safe_key>.part` und `.json` mit `{size, sha256, url}`, HF-Dateien unter `<safe_key>/` mit
    `revision.txt`. Python setzt also einen Download fort, den Swift begonnen hat, und umgekehrt.
- Verhalten:
  - Fortsetzen mit `Range`; ohne `206` geht es neu von vorn.
  - 3 Versuche pro Mirror, dann der nächste.
  - Falsche Prüfsumme oder Größe: die Datei löschen, nächster Mirror.
  - Google Drive: die Bestätigungsseite wie `_open_gdrive`.
  - Vor dem Start die Platzprüfung (`volumeAvailableCapacityForImportantUsage`, unter Linux `statfs`) →
    `EngineFailure("no_space")`.
- Nach dem Download: `engine.request("convert_model", …)`. Das verdrahtet die App in Phase 2.

- [ ] **Schritt 1:** Tests schreiben:
  - `resumesFromPartialFile` (Fake-Transport)
  - `restartsWhenRangeIgnored`
  - `wrongChecksumDeletesAndTriesNextMirror`
  - `hfFilesWithSizes`
  - `gdriveConfirmPage`
  - `spaceCheck`
  - `partialLayoutReadableByPython` (die Fixture `.json` ist identisch)
  - `realURLSessionWithRangeServer` (`range_server.py` auf einem freien Port)
- [ ] **Schritt 2:** FAIL.
- [ ] **Schritt 3:** Umsetzen.
- [ ] **Schritt 4:** PASS.
- [ ] **Schritt 5:** Commit „StudioCore: model downloads – resume, checksum, space, mirrors, Google Drive“ und
  Push.

### Task 10: Skizzen-SVG lesen

**Dateien:**
- Neu: `macos/Sources/StudioCore/Sketch/SketchSVG.swift`
- Test: `SketchSVGTests.swift`

**Schnittstellen:**
- `public struct Sketch: Sendable`: `width`, `height`, `background: RGB?`, `strokes: [Stroke]`
- `Stroke`: `segments: [Segment]`, `closed`, `color: RGB`, `opacity`, `width`, `fixed`
- `Segment` ∈ `move`, `line`, `quad`, `cubic`
- `SketchSVG.parse(_ text: String) throws -> Sketch` liest, was `svg_io.scene_to_svg`, `edited.svg` und
  `export.restyle_svg` schreiben: `M`, `L`, `Q`, `C` und `Z`, absolut, mit `rgb()`- oder `#`-Farben,
  `stroke-opacity`, `stroke-width`, `data-fixed` und `data-bg`.
- `SketchSVG.write(_ sketch: Sketch) -> String` ist für Phase 2 (Bearbeiten); hier wird nur gelesen.
- Unter Linux kommt `XMLParser` aus FoundationXML.

- [ ] **Schritt 1:** Test `parsesWhatPythonWrites` schreiben (`svg_expected.json`, Toleranz 1e-4), dazu
  `rejectsNonSVG`.
- [ ] **Schritt 2:** FAIL.
- [ ] **Schritt 3:** Umsetzen.
- [ ] **Schritt 4:** PASS.
- [ ] **Schritt 5:** Commit „StudioCore: read the sketch SVGs of the engine“ und Push.
