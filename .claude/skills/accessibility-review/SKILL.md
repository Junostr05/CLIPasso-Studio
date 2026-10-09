---
name: accessibility-review
description: Audit and fix accessibility in CLIPasso Studio – the PySide6 desktop studio and the phone remote page – against WCAG 2.2 AA. Use for "check a11y", "is this accessible?", contrast, keyboard and focus, screen-reader names, touch target size, or before releasing a UI change. Measures real colours and the real phone page in Chromium instead of guessing.
argument-hint: "[studio | phone | <page, widget or file>]"
---

# /accessibility-review

Audit with evidence, fix what is objective, keep the project's a11y tests green. Read
[../design-system/reference/house-style.md](../design-system/reference/house-style.md) for the tokens and
components first.

## 1. Measure

Run what applies to the scope (all of it for a full audit):

```bash
python .claude/skills/accessibility-review/scripts/contrast_check.py --failing   # both palettes + phone.css
python .claude/skills/accessibility-review/scripts/contrast_check.py "#FG" "#BG"  # any pair you are unsure of
python .claude/skills/accessibility-review/scripts/phone_audit.py /tmp/phone       # phone page, light + dark
QT_QPA_PLATFORM=offscreen python -m pytest -q tests/test_theme_contrast.py \
  tests/test_gui.py -k "every_button_has_a_name or tab_order or small_window"
python .claude/skills/design-critique/scripts/shoot.py /tmp/shots --pages <page> --small   # to look
```

- `contrast_check.py` covers text (4.5:1) **and** the non-text pairs the test does not: borders, input fills,
  focus/checked accent, slider and progress tracks (1.4.11, 3:1). A failing `ui:` row is only a problem when
  nothing else identifies the control (a label, text, an icon) – judge in context.
- `phone_audit.py` starts the app offscreen (`tests/e2e/app_harness.py`), opens the phone page in Chromium at
  390 × 844 and checks every tab: names, symbol-only names (✎ ☆ ?), touch targets (24 px AA, 44 px
  comfortable), computed text contrast (disabled controls exempt), unlabeled fields, alt text, and states shown
  only by the `on` class. It saves screenshots – look at them.
- Qt widgets have no automated contrast-on-screen check: read the screenshots for text drawn on non-token
  backgrounds (e.g. text painted on the white sketch paper, on the canvas or on photos).

Needs the dev requirements; Qt on Linux needs `libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3`;
the phone audit needs `python -m playwright install chromium` once.

## 2. Inspect what tools cannot measure

**Studio (Qt)**
- **Focus visible (2.4.7)** – the stylesheet sets `outline: 0` on `*`; inputs get an accent border on focus,
  but check buttons, tool buttons, toggles, segments, nav buttons and list items: tab through a page
  (`QWidget.focusNextChild`, or reason from `theme.stylesheet()` – is there a `:focus` rule?).
- **Keyboard (2.1.1)** – everything reachable with Tab; canvas tools, mask/detail brushes, gallery large view
  have keyboard paths? Shortcuts in `gui/shortcuts.py` must not need a mouse to discover (About page lists
  them). Escape closes dialogs and full screen.
- **Names (4.1.2)** – icon-only buttons need a tooltip or `setAccessibleName`; switches get the label of their
  row via `a11y.link_labels()` (buddy). Custom-painted widgets (canvas, sliders in dialogs) need
  `setAccessibleName` / `setAccessibleDescription`.
- **Text size** – nothing below the 11 px badge role; respect the interface size setting (90–150 %,
  `QT_SCALE_FACTOR`): no fixed pixel heights that clip text at 150 %.
- **Status messages (4.1.3)** – toasts and progress: do they also exist as text somewhere persistent?

**Phone page (HTML)**
- Tabs (`#tabs`) and segmented buttons use the class `on` – add `aria-selected` / `aria-pressed` /
  `aria-current` alongside; glyph icons (✎ ◐ ▦ ☰ ★ ☆) inside buttons go in `<span aria-hidden="true">`.
- Live regions for the job status (`#status`) and toasts (`role="status"` / `aria-live="polite"`).
- `<html lang>` is set from the app language – keep it.

## 3. Report

```markdown
## Accessibility audit – <scope>, <date>
**Standard:** WCAG 2.2 AA | **Studio:** dark + light | **Phone:** light + dark, 390 × 844

| # | Where | Issue | WCAG | Severity | Fix |
|---|---|---|---|---|---|
| 1 | phone.css dark `--accent` | white on #8B7FFF = 3.2:1 on every primary button | 1.4.3 | 🔴 | darker accent for fills, keep the light one for text |

### Contrast (measured)  – failing pairs from the scripts, with ratios
### Keyboard & focus     – path, traps, invisible focus
### Screen reader        – unnamed / badly named controls
### Touch (phone)        – below 24 px (AA) · below 44 px (comfortable)
### Fixed in this pass   – with file:line
### Needs a decision     – colour changes that alter the look
```

Severity: 🔴 blocks someone (fails AA on a main path) · 🟡 fails AA on a side path or is confusing ·
🟢 below best practice.

## 4. Fix and prove

- Colour fixes go into the **tokens** (`theme.py` Palette, `phone.css :root`), never per widget. Re-run
  `contrast_check.py` and the contrast test; a token change ripples – shoot both themes and look.
- New colour pair → add it to `pairs()` in `tests/test_theme_contrast.py` so it stays fixed.
- Names: prefer visible text; else tooltip (Qt) / `aria-label` (phone) from **both** language files.
- Add a test in the house style for each new rule (`"""3.7: the phone tabs say which one is selected"""`); the
  phone page has Playwright tests in `tests/e2e/test_phone_page.py`.
- Contrast and name fixes are objective – make them. Changing the brand accent or the look of a whole surface
  → show before/after screenshots and let the user choose.
- Then run `ruff check .` and the tests above; mention user-facing fixes for the next what's new.
