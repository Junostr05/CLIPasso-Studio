# CLIPasso Studio – house style

The design system lives in code. There is no Figma file: the source of truth is `clipasso_studio/gui/theme.py`
(desktop) and `clipasso_studio/resources/phone/phone.css` (phone page). This file is the map; the code wins
when they disagree – then fix this file too.

## Two surfaces

| | Studio (desktop) | Phone page (remote) |
|---|---|---|
| Tech | PySide6 Qt Widgets, Fusion style, one QSS from `theme.stylesheet()` | Plain HTML/CSS/JS, no framework |
| Files | `gui/theme.py`, `gui/widgets/common.py`, `gui/pages/*.py`, `gui/*.py` | `resources/phone/index.html`, `phone.css`, `phone.js`, `login.*` |
| Colours | `Palette` DARK / LIGHT in `theme.py` | CSS variables in `phone.css` `:root` (+ `prefers-color-scheme: dark`) |
| Text | `tr("ui.…")` from `resources/i18n/{en,de}.json` | `data-t="name"` / `T.name` = key `ui.phone.page.name` (extra names: `texts.update(...)` in `gui/phone.py`) |
| Served by | – | `gui/remote.py` (HTTP), API in `gui/phone_api.py` |
| Tests | `tests/test_gui.py`, `test_theme_contrast.py`, `test_wrap_row.py` … | `tests/e2e/test_phone_page.py` (Playwright + Chromium), `test_phone*.py` |

The two palettes are separate on purpose (web vs desktop) but must read as one app – same accent family, same
text colours. `token_audit.py` lists where they drift.

## Tokens (desktop)

**Colour** – `theme.current()` returns the active `Palette` (dark default; light; or "system"):

| Token | Role |
|---|---|
| `bg`, `sidebar` | window and navigation background |
| `surface`, `surface2`, `surface3` | cards → inputs/buttons → hover, tooltips, tracks |
| `border` | 1 px lines of cards, inputs, buttons |
| `text`, `muted`, `faint` | body → secondary → captions, placeholders, disabled |
| `accent`, `accent_hover`, `accent_soft` | primary buttons, focus, checked → pressed → selected backgrounds, badges |
| `accent_text` | the accent used as text or icon on surfaces (links, "changed" parameter titles) |
| `on_accent` | text on `accent` |
| `success`, `warning`, `danger` + `on_status` | states, badges (text on success/warning) |
| `paper`, `ink` | the sketch itself: white paper, black strokes – not interface chrome |

**Spacing** – `SPACE_XS/S/M/L/XL` = 4 / 8 / 12 / 16 / 24 px. Pages use `theme.page_layout(layout)`
(margins 24/20/24/20, spacing 16 – a test enforces it). Dialogs use 22/20 margins and 14 spacing by habit – not
a token yet.

**Type** – font Inter (bundled in `resources/fonts`), 13 px base. Roles via `label(text, role)` /
`set_role(widget, role)`: `brand` 15/700 · `title` 22/700 · `h2` 15/600 · `h3` 13/600 · `muted` · `faint` 12 ·
`stat` 20/700 · `mono` · `badge` 11/600 (+ `badge-success`, `badge-warning`). No other sizes.

**Radius** – cards 14, method cards 12, flat cards / banners / menus 10, buttons 9 (lg 11, sm 8),
inputs / tooltips 8, segments 7, badges 9 (pill).

**Icons** – Lucide (ISC), one SVG per icon in `resources/icons/` (71 so far), tinted at run time:
`icons.icon(name, colour)`, `icons.pixmap(name, colour, size)`. A new icon: copy the SVG from lucide.dev into
that folder unchanged (`stroke="currentColor"`, `stroke-width="2"`).

## Components (desktop)

Build with the helpers in `gui/widgets/common.py` – never a bare widget with inline QSS:

| Helper | What | Styling hook |
|---|---|---|
| `label(text, role, wrap)` | any text | `role` property |
| `button(text, icon, variant, size)` | push button; variants `primary`, `danger`, `ghost`; sizes `sm`, `lg` | `variant`, `size` properties |
| `tool_button(icon, tooltip, size, checkable)` | icon-only button – **always pass a tooltip** (it is the screen-reader name) | QToolButton |
| `Card(flat=…)` | panel | `#Card`, `#CardFlat` |
| `ToggleSwitch` | on/off – named by the label of its row (see `a11y.py`) | painted |
| `SegmentedControl(items)` | exclusive choice; `set_icons()` for the compact form | `#SegmentBar`, `#Segment` |
| `WrapRow(first, second, tail)` | a row that breaks into two lines instead of overlapping | – |
| `CollapsibleSection(title, icon)` | parameter groups | header styled inline in `common.py` |
| `Banner` | inline notice with one action (missing models, hardware) | `#Banner`, `#BannerWarn` |
| `Toast` | transient message, bottom right | `#Card` |
| `EmptyState(icon)` | empty page: icon, title, what to do, a button that does it | – |
| `HintBox` (`widgets/hint_box.py`) | warnings about the photo, each with an action and "don't show again" | `#BannerWarn` |

Other hooks in the stylesheet: `#Root`, `#Page`, `#Sidebar`, `#NavButton`, `#MethodCard[selected="true"]`, `#Divider`.
A new look = a new objectName or property in `theme.stylesheet()`, styled for both palettes.

Custom-painted widgets (`canvas.py`, `ToggleSwitch`, `mask_edit.py`, `detail_edit.py`, `gallery_viewer.py`) read
`theme.current()` when they paint. Switching the theme rebuilds the main window (`MainWindow.apply_theme`), so
colours read at construction are fine – except while a job runs (then only the nav icons refresh).

## Patterns

- **Empty pages** say what is missing and offer the next step as a button (`EmptyState`; tested).
- **Notices**: persistent and actionable → `Banner`; transient → `Toast`; about the input → `HintBox`.
- **Parameters**: every field has a label, a `?` help (tooltip from `param.<name>.help`), a reset, and is found by
  the search. A changed parameter shows its title in `accent_text`.
- **Destructive actions**: `danger` variant; deleting results goes to the recycle bin; confirmations name the
  thing and the consequence.
- **Long work** never blocks: progress in a strip at the top, on the taskbar button, and on the phone.
- **Narrow windows**: smallest window `MIN_WIDTH` = 1200 px (`main_window.py`); rows that may not fit use
  `WrapRow`; a test checks the studio's columns at 1200 × 760.
- **Shortcuts** live in `gui/shortcuts.py` (also listed on the About page).

## Text

- Every visible string goes through `tr("key")` with entries in **both** `en.json` and `de.json`, same order.
  Keys: `ui.<area>.<name>`, `param.<name>.label|help|choice.<v>`, `group.<g>`, `nav.<page>`, `method.<m>.*`.
- Widgets that show text implement `retranslate()` (connected to `i18n.language_changed`) – the language
  switches at run time without a restart.
- Voice: see the ux-copy skill. German uses "du".

## Accessibility rules the tests already enforce

| Rule | Test |
|---|---|
| Every text colour ≥ 4.5:1 on every surface, both themes | `tests/test_theme_contrast.py` |
| Every visible button has a name (text, tooltip, accessible name or a buddy label) | `test_gui.py::test_every_button_has_a_name` |
| Tab order: input → canvas → parameters | `test_gui.py::test_studio_tab_order` |
| Pages use the spacing tokens | `test_gui.py::test_pages_use_the_spacing_tokens` |
| Empty pages explain the next step | `test_gui.py::test_empty_pages_say_what_to_do` |
| Columns fit the smallest window | `test_gui.py::test_studio_columns_fit_a_small_window` |
| View tabs and tools never overlap | `tests/test_wrap_row.py` |

New colours, buttons, pages or rows must keep these green – extend the test when you add a new kind of thing
(e.g. a new colour pair → add it to `pairs()` in `test_theme_contrast.py`).

## How to verify a change

```bash
ruff check .                                                     # lint (version pinned in requirements/dev.txt)
QT_QPA_PLATFORM=offscreen python -m pytest -q tests/test_theme_contrast.py tests/test_gui.py -k "name or tab_order or spacing or empty or small_window"
python .claude/skills/design-system/scripts/token_audit.py       # tokens vs hard-coded values
python .claude/skills/accessibility-review/scripts/contrast_check.py --failing
python .claude/skills/ux-copy/scripts/copy_check.py              # en/de texts
python .claude/skills/design-critique/scripts/shoot.py /tmp/shots --pages studio --small   # look at sheet_studio.png
python .claude/skills/accessibility-review/scripts/phone_audit.py /tmp/phone                # phone page in Chromium
```

Qt on Linux needs `libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3`; the phone audit needs
`python -m playwright install chromium` once.

## Project habits

- Tests have a docstring that starts with the version and says the behaviour in plain words
  (`"""3.6: every visible button … has a name for screen readers"""`).
- User-facing changes get a line in `resources/whats_new_en.md` + `whats_new_de.md` and in
  `packaging/release_notes.md` – but version bumps and release notes are their own commit
  (`3.6.0: version, release notes, what's new, README`); don't bump the version unless asked.
- Commit messages: `Area: what changed` in plain words (`Phone remote: back to the running job, …`).
- British spelling in English texts and code comments (colour, optimise, behaviour).
