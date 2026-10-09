---
name: ux-copy
description: Write, review or fix the interface text of CLIPasso Studio in English and German – buttons, hints, tooltips, parameter help, errors, empty states, toasts, the phone page, what's new and release notes. Use for "what should this button say?", "write the error for …", "review the copy", "translate this", or whenever new UI needs text. Keeps en.json and de.json in step and in the app's calm, explanatory voice.
argument-hint: "<screen, key prefix, or text to write or review>"
---

# /ux-copy

All interface text lives in `clipasso_studio/resources/i18n/en.json` and `de.json` – the same keys in the same
order. Code reads it with `tr("ui.area.name", n=3)`; the phone page with `data-t="name"` / `T.name`
(= key `ui.phone.page.name`). Release texts: `resources/whats_new_en.md` / `_de.md`,
`packaging/release_notes.md`. Voice and glossary: [reference/voice.md](reference/voice.md).

## Check first

```bash
python .claude/skills/ux-copy/scripts/copy_check.py              # missing keys, en/de parity, placeholders,
                                                                 # house style, long German labels, terminology
python .claude/skills/ux-copy/scripts/copy_check.py --grep "queue"     # how a word is used, both languages
python .claude/skills/ux-copy/scripts/copy_check.py --key ui.gallery.  # every text of an area
python .claude/skills/ux-copy/scripts/copy_check.py --unused           # keys nothing seems to use (verify!)
```

"Keys the code uses that have no text" is always a bug – the user sees the raw key.

## Write

1. **Context** – read the code that shows the text (widget, size, when it appears) and its neighbours
   (`--key` on the area). Match the words they already use.
2. **Draft in English and German together** (German "du", „…“) – not English first and a translation later.
3. **Fit** – German runs 30–100 % longer. Buttons, tabs, segments and nav labels have fixed room: keep them to
   1–3 words, and look at the German screenshot
   (`python .claude/skills/design-critique/scripts/shoot.py /tmp/shots --langs de --pages <page> --small`).
4. **Keys** – `ui.<area>.<name>` in snake_case; parameters `param.<name>.label` / `.help`; place the new keys
   next to their siblings in both files; the same `{placeholders}` in both languages.
5. **Wire it** – `tr("key")`, and if the widget lives through a language switch, set the text again in its
   `retranslate()`. Phone texts: a `ui.phone.page.*` key is sent automatically.
6. **Run the checker again** and the language tests
   (`QT_QPA_PLATFORM=offscreen python -m pytest -q tests/test_language.py tests/test_gui.py -k language`).

## Patterns (with this app's real texts)

| Kind | Shape | Example |
|---|---|---|
| Button | verb + object, sentence case, ≤ 3 words | Create sketch · Download · Reset all |
| Needs more input | text + space + … | Save as … · Report a problem … |
| Empty state | what will be here – how to start | No results yet – create your first sketch in the studio. |
| Hint about input | what is wrong (with numbers) – what helps | The photo is very small (120×90 px). … – a bigger photo helps. |
| Error | what happened. What to do (+ details below) | {name} could not be downloaded. Check the internet connection and try again. |
| Confirmation | the action as a question + the consequence | Cancel the running job? The best sketch so far will be saved. |
| Toast | the outcome, short | “{name}” is finished. |
| Tooltip / help | what it does, when to change it, the default | … Recommended: 3. |
| Status (running) | -ing form + count + … | Loading models (sketch 1/3) … |
| Menu path | arrows | Settings → Phone & messages |
| Long wait | honest numbers | ≈ 20 min on a CPU, 1–2 min on a GPU |

## Review output

```markdown
## Copy review: <area>
| Key | Now (en / de) | Problem | Proposal (en / de) |
|---|---|---|---|
### Terminology – words used for the same thing, with counts, and a recommendation
### Checker – what copy_check.py reported and what was fixed
```

Fix typos, house-style slips, missing German and broken placeholders directly. Rewording that changes meaning
or terminology across the app → propose first (a glossary change touches dozens of strings).

## What's new and release notes

User-facing changes get a bullet in `whats_new_en.md` **and** `whats_new_de.md` (shown in the app after an
update) and in `packaging/release_notes.md`: bold name + colon + what the user can now do, where to find it
(`**Time lapse:** ▶ next to the step slider plays …`). Versioned sections are written in the release commit –
don't bump versions unless asked.
