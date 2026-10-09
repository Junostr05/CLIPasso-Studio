---
name: design-system
description: Audit, document, or extend CLIPasso Studio's design system – the tokens in gui/theme.py, the widgets in gui/widgets/common.py and the phone page's phone.css. Use when checking for hard-coded colours, font sizes or spacing, when the studio and the phone page drift apart, when documenting a component, or when adding a new component or pattern that must fit the existing look in dark and light.
argument-hint: "[audit | document | extend] <component, page or pattern>"
---

# /design-system

The design system of this project lives in code, not in a design tool. Read
[reference/house-style.md](reference/house-style.md) first – it maps the tokens, components, patterns, text
rules and the tests that guard them. The code wins when the two disagree (then fix the reference too).

```
/design-system audit                    # where the UI leaves the tokens – desktop and phone
/design-system document <component>     # document a helper from gui/widgets/common.py (or a phone pattern)
/design-system extend <pattern>         # design and build a new component that fits
```

## Audit

1. Run the token audit and read the whole output:
   ```bash
   python .claude/skills/design-system/scripts/token_audit.py          # --all for every line, --json for data
   ```
   It parses `theme.py` and `phone.css` itself (no Qt needed) and lists: token values typed as hex (wrong in
   the other theme), off-palette colours, QColor literals, inline `setStyleSheet`, font sizes outside the
   type roles, layout numbers off the spacing scale (as a histogram), phone-vs-studio palette drift, colour
   literals on the phone page. Artwork colours (the sketch's ink, paper, export) are counted apart – they are
   content, not chrome.
2. Judge each group – the script finds candidates, you decide:
   - A hex that equals a token (e.g. `#9AA3B4` = `DARK.muted` painted on the white canvas) is a bug in light
     mode or on paper → use `theme.current().<token>`, or the token that matches the surface it sits on.
   - Scrims (black/white with alpha over a photo) and the white sketch paper are deliberate.
   - Inline QSS built from `theme.current()` at construction is acceptable (the theme switch rebuilds the
     window) but a property/objectName in `theme.stylesheet()` is cleaner; a fixed size like `font-size: 9px`
     is not acceptable – it bypasses the type scale (smallest role: 11 px badges).
   - Spacing values used many times (22/20 dialog margins, 6, 10, 14) are unofficial tokens: propose adding
     them to `theme.py` or snapping them to 4/8/12/16/24 – a user decision, since it moves pixels everywhere.
   - Phone drift: accent and text colours should read as one app; exact equality is not required.
3. Check what the tests already guard (house-style.md, "Accessibility rules the tests already enforce") and run
   `python .claude/skills/accessibility-review/scripts/contrast_check.py --failing` for colour decisions.
4. Report with the template below, then fix the objective items (token bugs, off-scale font sizes, missing
   theme handling) unless the user only asked for a report. Bigger moves (new tokens, re-spacing, palette
   changes) → propose with before/after screenshots and let the user pick.

```markdown
## Design system audit – <date>
**Token bugs:** X | **Off-palette:** X | **Inline styles:** X | **Off-scale type:** X | **Phone drift:** X

### Fix now (objective)
| Where | Problem | Fix |
|---|---|---|
| `gui/widgets/canvas.py:334` | `#9AA3B4` (= DARK.muted) on white paper, 2.5:1 | paint with a token that passes on `paper` |

### Decide (taste / wide impact)
| Proposal | Why | Impact |
|---|---|---|

### Healthy
- <what is consistent and should stay that way>
```

## Document

Read the helper in `gui/widgets/common.py` (or `widgets/*.py`, or the phone markup + CSS), its QSS in
`theme.stylesheet()`, and every call site (`grep -rn "Banner(" clipasso_studio/gui`). Document what is true
in the code:

```markdown
## <Component>
**Use for:** … **Not for:** … (name the alternative helper)
**Build:** `button(tr("ui.x"), "download", "primary", size="sm")`
| Option / property | Values | Default | Notes |
| State | Look (tokens) | Behaviour |   ← default, hover, pressed, checked, disabled, focus; dark + light
**Text:** keys it needs (en + de), retranslate() handling
**Accessibility:** name (text / tooltip / buddy label), keyboard, focus visibility
**Seen in:** file:line of 2–3 real uses
```

Put durable documentation in the reference file (a row in the components table or a short section), not in a
new document nobody opens.

## Extend

1. **Need** – what the user is trying to do; which existing helper comes closest and why it is not enough.
   Reuse beats a new component: a new `variant` / `role` / objectName is usually enough.
2. **Design in tokens** – colours from the Palette (both themes), sizes from SPACE_* and the type roles,
   radius from the existing set, Lucide icons. On the phone page: CSS variables only, touch targets ≥ 44 px.
3. **Build** – helper in `gui/widgets/common.py` (or its own module in `gui/widgets/` when large), QSS in
   `theme.stylesheet()`, texts via `tr()` in en.json **and** de.json, `retranslate()`, accessible name.
4. **Test** – a test in the house style (docstring starts with the version: `"""3.7: …"""`); extend
   `test_theme_contrast.pairs()` for new colour pairs; keep `test_every_button_has_a_name` green.
5. **Look** – `python .claude/skills/design-critique/scripts/shoot.py /tmp/shots --pages <page> --small` and
   read the contact sheet: dark/light × en/de, plus the smallest window.
6. **Record** – add it to `reference/house-style.md`.

## Principles for this app

1. **The sketch is the hero** – chrome stays quiet (surfaces, muted text); colour is for state and the one
   primary action per area.
2. **Both themes, both languages, smallest window** – nothing is done until it holds in all of them.
3. **Tokens or nothing** – a value that is not a token is either a new token or a mistake.
4. **Tested, not hoped** – this project encodes design rules as tests; a new rule gets a test.
