---
name: design-handoff
description: Turn a UI idea for CLIPasso Studio – a description, a sketch, a screenshot, a reference from another app – into a build spec that fits this codebase (PySide6 studio and phone page), precise enough that any Claude session can implement it without guessing, then optionally build it or file it as a GitHub issue. Use for "spec this feature", "plan the UI for …", "how should X look and work?", or before a bigger UI change.
argument-hint: "<idea, screenshot or feature> [--issue | --build]"
---

# /design-handoff

In this project the designer, the product owner and the reviewer are the same person, and Claude builds. The
spec is the handoff from "idea" to "code" – written in this codebase's terms: tokens, helpers, translation keys,
tests. Read [../design-system/reference/house-style.md](../design-system/reference/house-style.md) first.

## 1. Understand

- What should the user be able to do, on which page, and why now? Who uses it – desktop, phone, both?
- Look at the current state: `python .claude/skills/design-critique/scripts/shoot.py /tmp/before --demo
  --pages <page> --langs en --themes dark` (and the phone page via `phone_audit.py` if it is involved).
- Find the code: the page in `gui/pages/`, its widgets, the phone counterpart in `resources/phone/` and
  `gui/phone_api.py`. Most studio features also exist on the phone – decide whether this one should.
- Ask only what the code and screenshots cannot answer. Offer 2–3 concrete options when the direction is open.

## 2. Spec

```markdown
## Spec: <feature>
**Goal:** <the user can … so that …>  **Surfaces:** studio · phone · both  **Size:** S / M / L

### Where
| Part | File | Change |
|---|---|---|
| UI | gui/pages/studio.py (`_build_…`) | new row under … |
| Look | gui/theme.py | (only if a new objectName / property is needed) |
| Phone | resources/phone/index.html + phone.js, gui/phone_api.py | … |
| Setting | gui/app_settings.py `DEFAULTS` | `"<key>": <default>` (persists) |

### Layout (tokens, not pixels)
- Container: `Card()` / existing card …; spacing `SPACE_M` inside, `SPACE_L` between groups
- Order and alignment; what wraps at 1200 px (`WrapRow`) and in German

### Components
| Element | Helper | Variant / role | Icon (Lucide) | Name for screen readers |
|---|---|---|---|---|
| Start button | `button()` | `primary` | `play` | its text |

### States
| State | What the user sees | Text key |
|---|---|---|
| empty / default / running / done / error / disabled (+ why) | … | `ui.<area>.<name>` |

### Text (en / de)
| Key | English | German |
|---|---|---|

### Keyboard and accessibility
- Tab order, shortcut (add to `gui/shortcuts.py` if global), Escape behaviour, focus after the action
- Contrast of any new colour pair (`contrast_check.py "#FG" "#BG"`), phone targets ≥ 44 px

### Edge cases
- Long German labels · smallest window 1200 × 760 · interface size 150 % · a job running meanwhile
- No models downloaded · no GPU · phone and studio changing the same thing at once · huge galleries

### Tests (house style: docstring starts with the version)
- `tests/test_gui.py::test_<behaviour>` – what it asserts
- phone: `tests/e2e/test_phone_page.py` (Playwright) / `tests/test_phone*.py`

### Done when
- [ ] Screens checked in dark/light × en/de and at 1200 × 760 (`shoot.py --small`)
- [ ] `token_audit.py`, `contrast_check.py --failing`, `copy_check.py` show nothing new
- [ ] `ruff check .` and the tests above pass
- [ ] A line for what's new (en + de) is drafted
```

Use tokens and helper names, not pixel values; when a value has no token, say so and propose one.

## 3. Hand off

- **`--build`** (or the user says go): implement it in this session, smallest working slice first, and tick
  the "Done when" list with evidence (screenshots before/after, test output).
- **`--issue`**: file it on GitHub `Junostr05/CLIPasso-Studio` (GitHub MCP `issue_write`, or `gh issue create`)
  with the spec as the body and the before screenshot described; title in the commit style
  (`Studio: <what changes>`). Search existing issues first to avoid duplicates.
- Otherwise: show the spec and ask which option / whether to build.
