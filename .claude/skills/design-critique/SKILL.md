---
name: design-critique
description: Critique and improve a screen of CLIPasso Studio – the desktop studio, compare, queue, gallery, models, settings and about pages, or the phone remote page – from real offscreen screenshots in dark and light, English and German, at normal and smallest window size. Use for "review this screen", "what do you think of the gallery?", "make the studio look better", "polish the UI", or when a screenshot or idea for a screen is shared.
argument-hint: "<page, flow, screenshot or idea> [focus: hierarchy | layout | consistency | German | small window | phone]"
---

# /design-critique

Look at the real thing, judge it against this app's own system, then improve it. Read
[../design-system/reference/house-style.md](../design-system/reference/house-style.md) first.

## 1. See it

Never critique from code alone. Take screenshots:

```bash
python .claude/skills/design-critique/scripts/shoot.py /tmp/shots --demo --pages studio,gallery --small
#   pages: studio, studio:<method>[:<view>] (e.g. studio:scenesketch:matrix, studio:swiftsketch),
#          compare, queue, gallery, models, settings, about
#   --themes dark,light  --langs en,de  (default: all four)   --small: also MIN_WIDTH × 760
#   --demo: finished results of three methods + two queued jobs (placeholder strokes, from tests/helpers.py)
#   --job <job dir> / --queue IMAGE[:METHOD] for your own content
python .claude/skills/accessibility-review/scripts/phone_audit.py /tmp/phone     # phone page screenshots + checks
```

Open `sheet_<page>.png` (the four variants side by side) with Read, then the single files to zoom in – crop
with Pillow when details matter. If the user shared a screenshot, critique that and still shoot the current
state to compare. Shoot with `--demo` as well as without: the empty states and the full screens are both
part of the design. The demo strokes are placeholders – judge the chrome around them, not the sketches.

## 2. Judge – in this order

1. **Purpose in two seconds** – does the eye land on the sketch and the one primary action (Create sketch,
   Export, Download)? Is there exactly one `primary` button per area?
2. **Breakage** – overlap, clipping, cut-off text, elements leaving their card, scrollbars where none are
   needed. Check the **German** and **smallest window** variants first: that is where it breaks.
3. **Hierarchy** – type roles used as meant (title → h2 → h3 → body → muted → faint); spacing groups related
   things (8–12 inside a group, 16–24 between); weight and colour only where they carry meaning.
4. **Consistency** – tokens, radius, icon size and stroke, button variants, same words for the same thing; the
   phone page and the studio look like one product.
5. **States** – empty (says what to do), loading/running (progress, time left), done, error (what happened,
   what helps), disabled (why?). Ask for screenshots of states you cannot see.
6. **Accessibility basics** – contrast of anything painted outside the tokens, focus visibility, names of
   icon-only buttons, target sizes on the phone. For a full pass use `/accessibility-review`.
7. **Delight** – what makes this screen feel crafted (live drawing, time lapse, paper styles). Keep it, build
   on it.

Be specific ("the model banner's text is cut at the top and bottom in German at 1200 × 760") and say why
(which user, which task). Name what works – it should survive the next change.

## 3. Report

```markdown
## Critique: <screen> – <date>
Variants seen: dark/light × en/de, 1480 × 920 and 1200 × 760

### First impression
<2 sentences: what lands first, the biggest opportunity>

### Broken (fix now)
| What | Where (variant) | Cause (file:line) | Fix |
|---|---|---|---|

### Improve
| Finding | Why it matters | Proposal | Effort |
|---|---|---|---|

### Works well
- …

### Plan
1. <highest impact> – objective / needs your call
```

## 4. Improve

- **Fix broken things directly** (clipping, overlap, token bugs, missing states), smallest change first: a
  `WrapRow`, a word-wrapped label, a minimum size, a shorter German text (ask before changing meaning).
- **Taste changes** (layout moves, new emphasis, colour) – make them, then show before/after sheets and let
  the user decide; keep the change easy to revert (one commit per idea).
- Use the existing helpers and tokens (`/design-system`); new text in en **and** de (`/ux-copy`).
- **Prove it**: re-shoot the same pages and variants, compare with the before sheet, run
  `ruff check .` and the GUI tests that touch the area (`QT_QPA_PLATFORM=offscreen python -m pytest -q
  tests/test_gui.py -k <area>`). Add a test when a layout rule was broken (like
  `test_studio_columns_fit_a_small_window`).

## Known pressure points

- The studio at 1200 × 760 in German: the centre column (model banner, canvas, status row, start bar).
- The phone page's own palette (`phone.css`) drifts from the studio's – compare side by side.
- Six SceneSketch views compete for the tab row (`WrapRow` + compact `SegmentedControl`).
Re-check these after any change nearby; remove an item here once it is fixed for good.
