# Phase 1 · Kopflose Rechnung – Umsetzungsplan

> **Für ausführende Agenten:** Pflicht-Skill: superpowers:executing-plans (in dieser Sitzung, ohne Subagenten).
> Schritte mit `- [ ]` abhaken.

**Ziel:** `python -m clipasso_studio.headless` rechnet Aufträge über JSON-Zeilen auf stdin/stdout. Es exportiert
Schema und Modellliste als JSON und kennt das Gerät `mps`.

**Architektur:** Ein neues Paket `clipasso_studio/headless` (ohne Qt) legt eine dünne Protokoll-Schicht über
`engine/runner.JobRunner`. Die Regeln „aktiv, wenn …“ in `settings_schema.py` werden deklarativ und dadurch
exportierbar. Die Engine bekommt `mps`.

**Technik:** Python 3.11/3.12, PyTorch 2.11, pytest; keine neuen Abhängigkeiten.

**Spec:** `docs/macos/plan.md` (Abschnitte 3, 4, 7, 10)

## Globale Vorgaben

- `build.yml`, `tools/manifest.py`, `packaging/` bleiben unverändert. `ruff check .` (Regeln E, F, W; Zeilen
  ≤ 120) muss grün sein.
- Protokoll Version 1. Ein JSON-Objekt pro Zeile, UTF-8, `\n` am Ende.
  - Anfrage: `{"id", "op", "args"}`
  - Antwort: `{"id", "ok", "result" | "error": {"code", "message", …}}`
  - Ereignis: `{"event", "job", "data"}`
- Ereignisnamen und -felder sind die der Engine. Bytes gehen als Base64 unter `<feld>_b64`, NaN und ±∞ als `null`.
- `iteration` höchstens 10 pro Sekunde und Skizze. Die letzte Meldung einer Skizze kommt immer an.
- stdout gehört allein dem Protokoll. fd 1 des Prozesses (und damit der Worker) wird auf stderr umgelenkt.
- Texte immer Deutsch und Englisch (`de.json`/`en.json`): **Bild**, **Auftrag**, **Voreinstellung**.
- Keine Geheimnisse (`telegram_token`, `remote_token`, `remote_pin`) in Ausgaben. Der Hilfsprozess liest
  `settings.json` nur für `models_dir`.
- Tests werden nie übersprungen oder abgeschwächt.

## Review-Fokus

1. **Pfade mit Umlauten und Leerzeichen** (`Ausgabe ö/Bild Ä.png`): Auftrag und Ordner funktionieren → e2e-Test in
   Task 5.
2. **Sehr lange Zeilen** (Live-SVG und PNG als Base64, mehrere MB) bleiben eine Zeile → Test in Task 3.
3. **Anfragen während einer Ereignisflut** werden sofort beantwortet und gehen nicht verloren → Test in Task 4
   (10 000 Ereignisse, dazwischen `pause`).
4. **Kaputte Zeile oder unbekanntes `op`:** Es kommt eine Fehlerantwort, der Prozess läuft weiter → Test in Task 4.
5. **Hilfsprozess per SIGKILL getötet:** Die Worker enden von selbst innerhalb von 10 s, und der Auftrag lässt
   sich fortsetzen → Prüfung des Elternprozesses in `runner._EventControl.should_stop`, e2e-Test in Task 5.

---

### Task 1: Deklarative Regeln „aktiv, wenn …“

**Dateien:**
- Neu: `clipasso_studio/conditions.py`
- Ändern: `clipasso_studio/settings_schema.py` (alle `enabled_if=`-Lambdas, `_on`, `_off`, `_best_by`,
  `_mask_model`, `_scene_simplify`)
- Test: `tests/test_schema_conditions.py`

**Schnittstellen:**
- Produziert: Die Klassen `On(key)`, `Off(key)`, `Eq(key, value, default=None)`, `Ne(key, value, default=None)`,
  `Gt(key, number)`, `Has(key, flag)`, `All(*c)` und `AnyOf(*c)`. Jede ist aufrufbar als
  `__call__(settings: dict) -> bool` und hat `to_json() -> dict`, zum Beispiel
  `{"op": "eq", "key": "saliency_model", "value": "clip"}` oder `{"op": "all", "of": [...]}`.
- Bedeutung:
  - `On`: `bool(s.get(k))`
  - `Off`: `not s.get(k)`
  - `Eq`/`Ne`: `s.get(k, default) ==/!= v`
  - `Gt`: `float(s.get(k) or 0) > n`
  - `Has`: `flag in str(s.get(k, ""))`

- [ ] **Schritt 1:** Test schreiben. `LEGACY` ist eine wörtliche Kopie der heutigen Lambdas als Dict
  `(method, key) -> callable`, also eine eingefrorene Referenz. Die Domänen der steuernden Schlüssel sind
  explizit; aus ihnen entsteht das kartesische Produkt pro Methode:
  ```python
  def test_conditions_match_the_legacy_lambdas():
      for method in schema.METHODS:
          for s in _all_driver_combinations(method):      # Produkt der Domänen, ergänzt um die Standardwerte
              for p in schema.params_for(method):
                  old = LEGACY.get((method, p.key))
                  assert (p.enabled_if is None) == (old is None), (method, p.key)
                  if old is not None:
                      assert p.enabled_if(s) == old(s), (method, p.key, s)

  def test_every_condition_is_json():
      for method in schema.METHODS:
          for p in schema.params_for(method):
              if p.enabled_if is not None:
                  json.dumps(p.enabled_if.to_json())
  ```
- [ ] **Schritt 2:** `pytest tests/test_schema_conditions.py -q` → FAIL: `to_json` fehlt.
- [ ] **Schritt 3:** `conditions.py` schreiben (eingefrorene Dataclasses). In `settings_schema.py` jedes Lambda
  durch den entsprechenden Ausdruck ersetzen. `clipasso_uses_mask` bleibt als Funktion, ihr `enabled_if` wird
  `AnyOf(On("mask_object"), Eq("mask_object_attention", "on", "auto"))`.
- [ ] **Schritt 4:** Den neuen Test und die bestehenden Tests ausführen:
  `pytest tests/test_schema_conditions.py tests/test_settings.py -q` → PASS. Dazu `ruff check .`.
- [ ] **Schritt 5:** Commit „settings: declarative enabled_if conditions (exportable, same results)“ und Push.

### Task 2: Export von Schema und Modellliste

**Dateien:**
- Neu: `clipasso_studio/headless/__init__.py`, `clipasso_studio/headless/export.py`,
  `clipasso_studio/headless/__main__.py`
- Test: `tests/test_headless_export.py`

**Schnittstellen:**
- Verbraucht: `Param.enabled_if.to_json()` aus Task 1.
- Produziert:
  - `export_schema() -> dict` mit `{"format": 1, "app_version", "methods", "default_method", "devices", "method": {m: {"groups",
    "group_text": {g: "group.<g>"}, "presets": {...}, "preset_order": ["fast", "standard", "quality"],
    "preset_text": {p: "ui.preset.<p>"}, "defaults": {...}, "params": [Param-JSON]}}}`.
  - Param-JSON: `key, kind, default, group, cli, min, max, step, decimals, choices, advanced, hidden,
    enabled_if (dict | null), text: {"label", "help", "choices": {wert: textschlüssel}}`. Die Textschlüssel werden
    aufgelöst wie in `param_text_key` (erst `param.<method>.<key>.<suffix>`, dann `param.<key>.<suffix>`), und zwar
    gegen die Schlüssel in `resources/i18n/en.json`. Schlüssel, die es nicht gibt, fehlen.
  - `export_models() -> dict` mit `{"format": 1, "partial_dir": ".partial", "models": [{"key", "filename", "urls",
    "sha256", "download_size", "stored_size_mb", "kind", "mac_bundled", "extra"}]}`.
    - `mac_bundled` ist nur für `blazeface` wahr.
    - `extra.files` enthält `[{remote, local, size, fp16, prefix}]`.
  - Kommandozeile: `python -m clipasso_studio.headless --export-schema PFAD` und `--export-models PFAD`.

- [ ] **Schritt 1:** Tests schreiben:
  - `test_schema_has_every_param` (Schlüssel, Standardwerte und Grenzen gleich `settings_schema`)
  - `test_text_keys_exist_in_both_languages` (jeder exportierte Schlüssel steht in `de.json` und `en.json`)
  - `test_conditions_round_trip` (ein Python-Auswerter des JSON-Ausdrucks liefert dasselbe wie `enabled_if`,
    geprüft an den Standardwerten und an 200 zufälligen Einstellungen, Seed 0)
  - `test_models_match_store` (Anzahl, SHA-256, Größen gleich `model_store.SPECS`; nur `blazeface` ist
    `mac_bundled`)
  - `test_cli_writes_files` (ein Subprozess schreibt beide Dateien in `tmp_path`)
- [ ] **Schritt 2:** `pytest tests/test_headless_export.py -q` → FAIL: Das Modul fehlt.
- [ ] **Schritt 3:** `export.py` und `__main__.py` schreiben. Der Export importiert weder torch noch Qt; der Test
  prüft `sys.modules` im Subprozess.
- [ ] **Schritt 4:** pytest → PASS; `ruff check .`.
- [ ] **Schritt 5:** Commit „headless: export the parameter schema and the model list as JSON“ und Push.

### Task 3: Protokoll

**Dateien:**
- Neu: `clipasso_studio/headless/protocol.py`
- Test: `tests/test_headless_protocol.py`

**Schnittstellen:**
- `PROTOCOL_VERSION = 1`
- `encode(obj: dict) -> bytes`: kompaktes JSON, `ensure_ascii=False`, `\n`. Bytes → `<feld>_b64`, NaN/∞ → `None`,
  Tupel → Listen, numpy-Skalare → Python.
- `decode(line: bytes) -> dict`: wirft `ProtocolError(code, message)` bei ungültigem JSON, fehlender `id`,
  fehlendem `op` oder falschen Typen.
- `class Writer(stream)` mit `send(obj)`, threadsicher.
- `class IterationThrottle(rate=10.0, clock=time.monotonic)` mit `offer(job, data) -> list[dict]` und
  `flush(job, seed=None) -> list[dict]`. Die zurückgegebenen Ereignisse sind sofort zu senden. `it + 1 == total`
  geht immer durch, und `flush` liefert die zurückgehaltene letzte Meldung.

- [ ] **Schritt 1:** Tests schreiben:
  - `test_bytes_become_base64_fields` (`{"png": b"\x89PNG"}` → `{"png_b64": "iVBORw=="}`)
  - `test_non_finite_numbers_are_null`
  - `test_umlauts_stay_readable` (`"Bild Ä"` steht im Klartext)
  - `test_large_payload_is_one_line` (5 MB → genau ein `\n` am Ende)
  - `test_decode_rejects` (Parametrisierung: kein JSON, Liste statt Objekt, ohne `op`, `id` als Text) → `ProtocolError`
  - `test_throttle` (Uhr als Fake: 100 Meldungen in 1 s → ≤ 11 gesendet, die letzte immer dabei; `flush` nach
    `seed_done` gibt die zurückgehaltene)
- [ ] **Schritt 2:** pytest → FAIL.
- [ ] **Schritt 3:** `protocol.py` schreiben.
- [ ] **Schritt 4:** pytest → PASS; ruff.
- [ ] **Schritt 5:** Commit „headless: JSON-lines protocol with base64 bytes and iteration throttle“ und Push.

### Task 4: Server (mit Fake-Runner getestet)

**Dateien:**
- Neu: `clipasso_studio/headless/server.py`
- Ändern: `clipasso_studio/headless/__main__.py` (ohne Export-Option startet der Server)
- Test: `tests/test_headless_server.py`

**Schnittstellen:**
- Verbraucht: `protocol.*` (Task 3), `export.*` (Task 2) und `JobRunner` (`start`, `poll`, `pause`, `resume`,
  `cancel`, `kill`, `is_running`, `is_paused`, `shutdown_warm`).
- Produziert:
  - `class EngineServer(writer: Writer, runner=None, clock=time.monotonic)`
  - `handle(req: dict) -> dict`: die Antwort
  - `pump() -> None`: Ereignisse holen und senden
  - `serve(inp: BinaryIO) -> int`: Leseschleife in einem Thread, Hauptschleife mit `pump` alle 50 ms. Bei EOF:
    `runner.kill()`, Rückgabe 0.
- **ops** und ihr Ergebnis:

  | op | Ergebnis |
  |---|---|
  | `hello` | `{protocol, app_version, python}` |
  | `devices` | `{torch, cuda, mps}` aus einer Probe im Kindprozess (spawn), zwischengespeichert |
  | `schema` | `export_schema()` |
  | `models` | `export_models()` |
  | `required_models` | `args.settings` → `{required, missing}` |
  | `start` | `args: target, settings, output_root, resume_dir?, auto_parallel=True` → `{job: "j<n>", job_dir}` |
  | `pause`/`resume`/`cancel` | `{paused}` |
  | `shutdown` | `kill` und Ende |

- **Fehlercodes:** `bad_request`, `unknown_op`, `busy` (ein Auftrag läuft schon), `no_job`, `not_found` (das Bild
  fehlt), `internal`.
- Ereignisse `job_done`, `job_failed` und `job_ended` beenden den aktuellen Auftrag. Vorher kommt `flush`.

- [ ] **Schritt 1:** Tests schreiben, mit einem `FakeRunner`, der Ereignislisten abspielt:
  - `test_hello`
  - `test_start_streams_events_with_job_id`
  - `test_busy_while_running`
  - `test_pause_without_job_is_no_job`
  - `test_bad_line_and_unknown_op_keep_serving`
  - `test_requests_answered_during_event_flood` (10 000 Ereignisse, `pause` wird beantwortet, die Reihenfolge der
    Ereignisse bleibt)
  - `test_eof_kills_the_runner`
  - `test_shutdown_answers_then_ends`
  - `test_job_done_flushes_last_iteration`
- [ ] **Schritt 2:** pytest → FAIL.
- [ ] **Schritt 3:** `server.py` schreiben. In `__main__.py` setzt `main()` vor allem anderen
  `PYTORCH_ENABLE_MPS_FALLBACK=1` (`setdefault`) und ruft `claim_stdout() -> BinaryIO` auf. Die Funktion macht
  `fd = os.dup(1)`, `os.dup2(2, 1)` und `sys.stdout = sys.stderr` und gibt `os.fdopen(fd, "wb", buffering=0)`
  zurück.
- [ ] **Schritt 4:** pytest → PASS; ruff.
- [ ] **Schritt 5:** Commit „headless: engine server – start, pause, resume, cancel, shutdown over JSON lines“ und
  Push.

### Task 5: Echte Aufträge im Subprozess (e2e)

**Dateien:**
- Ändern: `clipasso_studio/engine/runner.py` (`_EventControl.should_stop`: auch wahr, wenn
  `mp.parent_process()` nicht mehr lebt; die Prüfung höchstens einmal pro Sekunde)
- Test: `tests/test_headless_e2e.py`, `tests/test_runner_orphans.py`

**Schnittstellen:** Verbraucht wird der Server aus Task 4 als Subprozess:
`[sys.executable, "-m", "clipasso_studio.headless"]`. Die Modelle kommen wie in den bestehenden Tests aus
`models/` (`tools/fetch_models.py`).

- [ ] **Schritt 1:** Tests schreiben. Kleiner CLIPasso-Auftrag: `num_iter=30`, `num_sketches=1`, `device=cpu`,
  `mask_object=False`, Bild aus `resources/samples`.
  - `test_job_runs_with_preview_and_done`: Es kommt mindestens ein `preview` mit `<svg`, dazu `seed_done` und
    `job_done`; `job.json` existiert. Ziel ist eine Kopie unter `Ausgabe ö/Bild Ä.png`.
  - `test_stdout_stays_clean`: Ein Subprozess ruft `claim_stdout()` auf (aus `headless/__main__.py`, gibt den
    Protokoll-Strom zurück). Danach schreiben `print`, `os.write(1, …)` und ein Kindprozess
    (`subprocess.run([sys.executable, "-c", "print('kind')"])`) auf stdout. Auf stdout steht trotzdem nur die eine
    Protokollzeile, alles andere landet auf stderr. Einen Test-Haken im Produktcode gibt es nicht.
  - `test_pause_resume_cancel`: `num_iter=5000`. Nach dem ersten `iteration` kommt `pause`; danach 2 s lang kein
    `iteration`. Es folgen `resume` und `cancel`. Ein Endereignis kommt, `job_state.json` hat den Status
    `cancelled`, und `jobs.can_continue` ist wahr.
  - `test_eof_marks_interrupted`: Ist stdin während eines Auftrags zu, endet der Prozess innerhalb von 15 s.
    Der Status ist `interrupted`.
  - `test_resume_dir_continues`: `start` mit `resume_dir` auf den abgebrochenen Ordner → `job_done`, derselbe
    `job_dir`.
  - `test_orphan_workers_stop` (in `test_runner_orphans.py`): Der Server läuft mit einem Auftrag und wird per
    SIGKILL getötet. Nach höchstens 10 s lebt keiner seiner Worker mehr (geprüft mit `psutil` über die
    Kinder-PIDs, die vorher abgefragt wurden).
- [ ] **Schritt 2:** pytest → FAIL bei den Waisen, alle anderen PASS. Das Fehlschlagen beweist den Test.
- [ ] **Schritt 3:** `should_stop` im Runner ergänzen.
- [ ] **Schritt 4:** `pytest tests/test_headless_e2e.py tests/test_runner_orphans.py tests/test_reliability.py -q`
  → PASS.
- [ ] **Schritt 5:** Commit „headless: end-to-end jobs; workers stop when their parent is gone“ und Push.

### Task 6: Gerät `mps`

**Dateien:**
- Ändern:
  - `clipasso_studio/settings_schema.py`: `device`-Wahl um `"mps"` ergänzen, in `PARAMS` und in `_hardware`
  - `clipasso_studio/engine/pipeline.py:resolve_device`
  - `clipasso_studio/engine/runner.py`: `plan_workers` und `spreads_over_gpus` behandeln `mps` wie eine
    Grafikkarte, also mit einem Worker
  - jede weitere Stelle, die `cuda` direkt prüft (Liste per `grep -rn "cuda" clipasso_studio/engine`)
  - `clipasso_studio/gui/widgets/param_panel.py`: `mps` nur unter macOS anbieten
  - `de.json`/`en.json`: `param.device.choice.mps` = „Apple-Grafik (MPS)“ / „Apple GPU (MPS)“
- Test: `tests/test_device_mps.py`

**Schnittstellen:**
- `MPS_AUTO: tuple[str, ...] = ()` in `pipeline.py`: die Methoden, für die `auto` MPS wählt. Die Liste bleibt
  leer, bis Task 7 gemessen hat.
- `resolve_device(settings) -> (device, warning)`:
  - `mps` gewünscht, aber nicht verfügbar → `cpu` und `"mps_unavailable:…"`
  - `auto` → `cuda`, dann `mps` (nur Methoden in `MPS_AUTO`), sonst `cpu`

- [ ] **Schritt 1:** Tests schreiben, mit `monkeypatch` auf `torch.backends.mps.is_available` und
  `torch.cuda.is_available`:
  - `test_mps_chosen_when_available`
  - `test_mps_falls_back_with_warning`
  - `test_auto_uses_mps_only_for_measured_methods`
  - `test_mps_is_one_worker`
  - `test_coerce_accepts_mps_everywhere` (Aufträge vom Mac lassen sich unter Windows normalisieren)
  - `test_device_choice_hidden_off_macos` (mit `qapp`, `sys.platform` auf `win32` gesetzt)
- [ ] **Schritt 2:** pytest → FAIL.
- [ ] **Schritt 3:** Ändern wie oben.
- [ ] **Schritt 4:** `pytest tests/test_device_mps.py tests/test_settings.py tests/test_language.py tests/test_gui.py -q`
  → PASS; ruff.
- [ ] **Schritt 5:** Commit „engine: the mps device (Apple GPU), chosen by auto only where measured faster“ und
  Push.

### Task 7: Geschwindigkeit messen und macOS-CI für die Engine

**Dateien:**
- Neu: `tools/bench_device.py`, `.github/workflows/macos.yml` (Job `engine`), `requirements/macos.txt`
- Test: `tests/test_bench_device.py`

**Schnittstellen:**
- Aufruf: `python tools/bench_device.py --methods clipasso,swiftsketch,controlsketch,scenesketch --devices cpu,mps
  --repeats 3 --images benchmarks/images --out bench.json`
- `bench.json`: `[{method, device, image, repeat, seconds, sec_per_iter, iterations, clip_score, error}]`
- Ausgabe zusätzlich als Markdown-Tabelle auf stdout. Ein Gerät, das fehlt, wird als `error: "unavailable"`
  eingetragen und nie verschwiegen.
- `requirements/macos.txt`:
  - torch==2.11.0, torchvision==0.26.0
  - die Engine-Abhängigkeiten aus `app.txt` ohne PySide6, segno und imageio*
  - dazu pytest und pytest-timeout aus `dev.txt`
- `macos.yml`, Job `engine` auf `macos-26` (arm64), Python 3.12:
  1. installieren
  2. Modelle laden (Cache)
  3. `pytest tests/test_headless_* tests/test_schema_conditions.py tests/test_device_mps.py tests/test_runner_orphans.py`
  4. `python -c "import torch; print(torch.backends.mps.is_available())"`
  5. `bench_device.py` mit `--repeats 1` für CLIPasso und SwiftSketch
  6. Artefakt `bench.json`
- **Auslöser:** Push auf `claude/**` mit Pfaden `clipasso_studio/**`, `macos/**`, `tools/bench_device.py`,
  `.github/workflows/macos.yml`; dazu `workflow_dispatch`.

- [ ] **Schritt 1:** Test `test_bench_runs_tiny_cpu` schreiben: `--methods clipasso --devices cpu,mps --iters 3`;
  JSON mit einem CPU-Eintrag samt `seconds > 0` und einem MPS-Eintrag (`unavailable` unter Linux).
- [ ] **Schritt 2:** pytest → FAIL.
- [ ] **Schritt 3:** Werkzeug und Workflow schreiben.
- [ ] **Schritt 4:** pytest → PASS. Push, dann den Lauf auf GitHub prüfen (`mcp__github__actions_list`) und das
  Ergebnis lesen. Ob MPS auf dem Runner verfügbar ist, kommt in `docs/macos/plan.md` §7.
- [ ] **Schritt 5:** Commit „tools: measure cpu against mps per method; macOS CI for the engine“ und Push.
  `MPS_AUTO` wird erst gefüllt, wenn MPS-Messungen vorliegen, vom Runner oder von deinem Mac.
