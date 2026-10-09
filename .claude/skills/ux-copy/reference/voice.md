# Voice and glossary – CLIPasso Studio

Derived from the 1 400 texts in `resources/i18n/en.json` / `de.json`. When in doubt, copy the shape of the
nearest existing text (`copy_check.py --key <prefix>`).

## Voice

- **Calm and explanatory.** Say what happens and what helps – never alarm, never cheer. No exclamation marks,
  no "Oops", no "successfully", no "Please" unless asking for something the app cannot do itself.
- **Honest about cost.** Times, sizes and hardware in plain numbers: "≈ 20 min on a CPU, 1–2 min on a GPU",
  "Needs a one-time download (822 MB)". Say when something is experimental.
- **The user is in control.** Offer the way out or the next step: "Every hint can be switched off",
  "The original stays", "You see and can change everything first".
- **Explain the science in one clause**, then the practical meaning: "the one with the highest CLIP score is
  picked". Keep paper names (CLIPasso, SceneSketch, ControlNet, SDXL, LaMa) as they are.
- **German uses "du"** (informal, as the app does everywhere): „Wähle ein Bild …“, „deine Daumen hoch/runter“.

## Typography

| | English | German |
|---|---|---|
| Quotes | “Create sketch” | „Skizze erstellen“ |
| Aside / pause | space – en dash – space | same |
| Ranges | 1–2 min, 90–150 % | same |
| Needs more input | Save as … (space before …) | Speichern unter … |
| Running status | Loading models (sketch 1/3) … | Lade Modelle (Skizze 1/3) … |
| Menu path | Settings → Phone & messages | Einstellungen → Handy & Nachrichten |
| Multiplication / size | 248×248 px, 2× | same |
| Approximately | ≈ 20 min | ≈ 20 Min |
| Abbreviations | e.g. | z. B. (with a space) |
| Spelling | British: colour, optimise, behaviour, favourite | – |
| Case | Sentence case for buttons, titles, labels | German noun capitalisation |
| Joiners in titles | Result & export, Phone & messages | Ergebnis & Export |

## Glossary

| English | German | Means |
|---|---|---|
| sketch | Skizze | one drawing the methods produce (a set of strokes) |
| stroke | Strich | one Bézier curve of a sketch |
| result | Ergebnis | a finished job as the gallery shows it (its best sketch, score, settings) |
| job | Auftrag | one image + settings, in the queue; may draw several sketches |
| run | Durchlauf | the computation of one sketch (one seed) inside a job |
| queue | Warteschlange | waiting jobs |
| gallery | Galerie | all results in the output folder |
| method | Methode | CLIPasso, SwiftSketch, ControlSketch, SceneSketch |
| preset · My presets | Preset (also Voreinstellung) · Meine Presets | Fast / Standard / Quality · saved by the user |
| model | Modell | downloaded network weights |
| mask | Maske | the object cut out of the photo |
| seed | Seed | random start of a sketch |
| CLIP score | CLIP-Score | similarity of sketch and photo, in % |
| output folder | Ausgabeordner | where results are saved |
| brush style · paper | Pinselstil · Papier | how a sketch is shown and exported |
| detail brush | Detail-Pinsel | paint more / less detail |
| time budget | Zeitbudget | settings chosen to fit a duration |
| the phone (remote) | das Handy | the phone page; settings area: Phone & messages / Handy & Nachrichten |
| graphics card (GPU) | Grafikkarte | say "graphics card" in sentences, GPU in compact labels and badges |
| processor (CPU) | Prozessor | same rule as GPU |

**Known overlaps to settle** (each needs the user's call before a sweep):
- *photo / image / picture* – all three are used for the input. Today: "image" in labels and formats
  (Input image, Recent images), "photo" when talking about its content and quality (hints), "picture" on the
  phone page and in backup texts.
- *job / run* – `ui.cancel_run_question` says "job" in English but „Durchlauf“ in German.
- *Preset / Voreinstellung* – German uses both (the phone page says „Voreinstellung“, own presets say
  „Preset“).
- *delete / remove* – delete = gone (to the recycle bin); remove = taken out of a list, the file stays.
  Keep it that way and check new texts against it.

When the user decides one of these, update this table and fix the texts with `copy_check.py --grep`.
