# CLIPasso Studio – house style

The design system lives in code. There is no Figma file: the source of truth is `clipasso_studio/gui/theme.py`
(desktop) and `clipasso_studio/resources/phone/phone.css` (phone page). This file is the map; the code wins
when they disagree – then fix this file too.

## Two surfaces

| | Studio (desktop) | Phone page (remote) |
|---|---|---|
| Tech | PySide6 Qt Widgets, Fusion style, one QSS from `theme.stylesheet()` | Plain HTML/CSS/JS, no framework |
| Files | `gui/theme.py`, `gui/widgets/common.py`, `gui/pages/*.py`, `gui/*.py` | `resources/phone/index.html`, `phone.css`, `phone.js`, `login.*` |
| Colours | `Palette` DARK / LIGHT in `theme.py` | 4.2: the same palettes – `theme.tokens_css()`, served as `/tokens.css` (names: `PHONE_COLOURS`) |
| Text | `tr("ui.…")` from `resources/i18n/{en,de}.json` | `data-t="name"` / `T.name` = key `ui.phone.page.name` (extra names: `texts.update(...)` in `gui/phone.py`) |
| Served by | – | `gui/remote.py` (HTTP), API in `gui/phone_api.py` |
| Tests | `tests/test_gui.py`, `test_theme_contrast.py`, `test_wrap_row.py` … | `tests/e2e/test_phone_page.py` (Playwright + Chromium), `test_phone*.py` |

4.2: one source. The phone page has no colours or radii of its own: `theme.tokens_css()` writes the palettes
(`PHONE_COLOURS`: `--card` is the studio's surface, `--surface-2/3`, `--line` the border, `--control` a button's edge,
`--field` a text field's edge) and `RADIUS_*` (`--r-control`, `--r-card` …) as CSS variables, served as `/tokens.css`
before `phone.css`; Inter comes from `/fonts/…`, the icons are the studio's Lucide files, inline through
`{{icon:name}}` in the HTML. `--accent` is the fill (white text on it), `--accent-text` the accent as text,
`--on-paper` text on the white sketch paper. `test_design_tokens.py` keeps colour literals and px radii out of
`phone.css`; `test_theme_contrast.py` checks the phone's pairs.

Phone page semantics: a chosen tab / segment / toggle is set with `setOn(el, on)` in `phone.js` (the class `on` plus
`aria-selected` for tabs, `aria-pressed` otherwise); a control without visible text gets its name from
`data-label="<text name>"` (or `aria-labelledby`); glyphs inside buttons sit in `<span aria-hidden="true">`, icons
are `<svg class="icon" aria-hidden="true">`. 4.2: four tabs (Studio · Gallery · Queue · App); the sketch is the top of
the studio (`#studio-sketch`, CSS `order`) while there is one to see; on a wide screen (`body.desk`) the parts move
into a header, three columns and a footer like the PC (`DESK` in `phone.js`: [part, where to]).

## Tokens (desktop)

**Colour** – `theme.current()` returns the active `Palette` (dark default; light; or "system"):

| Token | Role |
|---|---|
| `bg`, `chrome` | the window / the studio's middle → the header and the job footer (4.0; 3.8: `sidebar`) |
| `surface`, `surface2`, `surface3` | side columns, cards → buttons, inputs, toolbars, menus → chosen segment, hover, tracks |
| `border` | 1 px dividers – decorative, never the only edge of an input |
| `control` | 1 px outline of buttons, segment bars and toolbars (soft: a button is told by fill and label) |
| `field` | border of text fields, spin boxes, drop-downs, check boxes – ≥ 3 : 1 on surface / surface2 |
| `text`, `muted`, `faint` | body → secondary → captions, step labels, disabled (`faint` not on surface3 / accent_soft) |
| `accent`, `accent_hover`, `accent_soft` | the one primary button, progress, chosen edges → hover → chosen backgrounds |
| `accent_text`, `accent_text_hover` | the accent as text or icon (links, "changed" titles) → under the mouse, counts |
| `focus` | the keyboard focus ring (= `accent_text`), ≥ 3 : 1 on every surface |
| `on_accent`, `on_accent_soft` | text on `accent` → secondary text on `accent_soft` (the chosen method card) |
| `success`, `warning`, `danger`, `danger_text` + `on_status` | states and costs; `danger` is a destructive button's edge, `danger_text` its label and error text; `on_status` on their fills |
| `on_paper` | hints painted on the white sketch paper (empty canvas) – the same in both themes |
| `paper`, `ink` | the sketch itself: white paper, black strokes – not interface chrome |
| `detail_more`, `detail_less` | the detail brush (orange / blue) |

Tests: `tests/test_theme_contrast.py` (text 4.5 : 1, control parts 3 : 1, both themes) and
`tests/test_design_tokens.py` (no colour, radius or style sheet outside theme.py except the artwork files).

**Spacing** – `SPACE_XS/S/M/L/XL` = 4 / 8 / 12 / 16 / 24 px. Pages use `theme.page_layout(layout)`
(margins 24/20/24/20, spacing 16 – a test enforces it). 4.0: side columns, header and footer `COLUMN_PADDING` 20;
dialogs `DIALOG_MARGIN` 24 / `DIALOG_SPACING` 16 via `theme.dialog_layout(layout)` (every dialog but the
gallery's large view – a test reads the sources); `HEADER_HEIGHT` 52, `FOOTER_HEIGHT` 76, `LEFT_COLUMN` 312,
`RIGHT_COLUMN` 168, `FILTER_COLUMN` 240 (the gallery's filters, the settings' parts), `READING_WIDTH` 820 (the
widest column of cards).

**Type** – font Inter (bundled in `resources/fonts`), 13 px base. Roles via `label(text, role)` /
`set_role(widget, role)`: `brand` 15/700 · `title` 22/700 · `h2` 15/600 · `h3` 13/600 · `muted` · `faint` 12 ·
`label` 11/600 capitals, 0.06 em (step labels; `label()` sets the font) · `status-success|warning|danger` 12 ·
`stat` 20/700 · `mono` · `badge` 11/600 (+ `badge-success`, `badge-warning`, `badge-danger`). No other sizes.
Other looks are properties styled in `theme.stylesheet()`: `variant` (primary, ghost, danger, link), `size`
(sm, lg), `state` (selected, best), `changed`, `align` – set with `set_prop(widget, name, value)`.

**Radius** – `theme.RADIUS_*`: 4 progress, check boxes · 7 segment / tab, menu item · 8 buttons, inputs, tools,
thumbnails, the paper · 9 segment / tab bar, badges · 10 cards, method cards, banners, menus · 11 large buttons,
the switch · 12 floating toolbars. No shadows: layers are told by surface and a 1 px line.

**Icons** – Lucide (ISC), one SVG per icon in `resources/icons/` (71 so far), tinted at run time:
`icons.icon(name, colour)`, `icons.pixmap(name, colour, size)`. A new icon: copy the SVG from lucide.dev into
that folder unchanged (`stroke="currentColor"`, `stroke-width="2"`).

## Components (desktop)

Build with the helpers in `gui/widgets/common.py` – never a bare widget with inline QSS:

| Helper | What | Styling hook |
|---|---|---|
| `label(text, role, wrap)` | any text | `role` property |
| `ElidedLabel(text, role)` | one line that ends in "…" when it does not fit; the whole text becomes the tooltip (status lines, names) | `role` property |
| `button(text, icon, variant, size)` | push button; variants `primary`, `danger`, `ghost`; sizes `sm`, `lg` | `variant`, `size` properties |
| `tool_button(icon, tooltip, size, checkable)` | icon-only button – **always pass a tooltip** (it is the screen-reader name) | QToolButton |
| `Card(flat=…)` | panel | `#Card`, `#CardFlat` |
| `ToggleSwitch` | on/off – named by the label of its row (see `a11y.py`) | painted |
| `SegmentedControl(items, orientation=…)` | exclusive choice, a row or (`Qt.Vertical`) a column; one Tab stop, the arrows choose; `set_icons()` for the compact form, `set_dense()` (8 px beside a label) in a narrow column | `#SegmentBar`, `#Segment[dense]` |
| `link_button(text, icon)` | an action that reads as a link (*Anpassen*, *Details*) | `variant="link"` |
| `RovingFocus(parent, choose)` | one Tab stop for a group of choices (method cards, sketches): arrows, Home, End choose, Space / Enter too | – |
| `CountBadge` | a number next to a name, hidden at 0 | `role="count"` |
| `Chip(icon, text, framed)` | a small piece of state (hardware, a running job); text elides | `#Chip[framed="true"]` |
| `StepHeader(n, title, action)` | *1 · BILD* above a step of the left column; one action on the right (`set_action()`: *Vergleichen …*, *Meine Voreinstellungen*) | `role="label"` |
| `Column(side, width)` | a side column: `surface`, a line towards the middle, `COLUMN_PADDING` | `#Column[side=…]` |
| `WrapRow(first, second, tail)` | a row that breaks into two lines instead of overlapping | – |
| `CollapsibleSection(title, icon)` | parameter groups | `#SectionHeader` |
| `Banner` | inline notice with one action (missing models, hardware) | `#Banner`, `#BannerWarn` |
| `Toast` | transient message, bottom right | `#Card` |
| `EmptyState(icon)` | empty page: icon, title, what to do, a button that does it | – |
| `HintBox` (`widgets/hint_box.py`) | warnings about the photo, each with an action and "don't show again" | `#BannerWarn` |

Other hooks in the stylesheet: `#Root`, `#Page`, `#Header` with `#HeaderTab`, `#RunChip` and `#AppButton`
(`widgets/header.py`), `#MethodCard[selected="true"]`, `#Divider`.

**The studio's footer** (`widgets/studio_footer.py`, 4.0): the job – status, estimate, *Details* (the numbers and
the loss curve as a drawer below the sketch, remembered as `studio_details_open`), the progress, and either
*Skizze erstellen* + *Zur Warteschlange* or, while the shown job runs, *Pause* + *Abbrechen*. The studio is a
page from edge to edge (`theme.columns_layout`, `layout_kind = "columns"`); other pages use `theme.page_layout`.

**The studio's columns** (4.0): on the left the numbered steps (`StepHeader`) – *1 · Bild* (preview, name and
size, the mask row across the column, *Ändern …* as a split button with samples, recent images, webcam and paste),
*2 · Methode* (the method cards one below the other), *3 · Voreinstellung* (the preset segment across the column,
the `#Summary` of what the job draws with *Anpassen*, the time budget, the switch rows). *Anpassen* swaps the
column for the parameter page (`left_stack`; *← Zurück* or Esc). In the middle the view segment, the job's ⋯ menu
and *Exportieren …* (`export_center.py`: the formats in groups, the sketch, the options of the 3.x export dialog
inside), the paper, and below it the floating `#CanvasToolbar` (below the matrix or the contact sheet, too –
whichever the middle shows). On the right the job's sketches (`SeedThumb`, one Tab stop, the arrows choose); for
SceneSketch the right column goes – its matrix in the middle holds the sketches. Tab runs left → middle → right →
footer (`a11y.reading_order`).

**Gallery and settings** (4.0) are pages from edge to edge too: a `Column` of `FILTER_COLUMN` on the left – the
gallery's search, methods (a vertical segment), favourites, albums with their counts (`AlbumChip.count_label`)
and tags; the settings' parts (`section_nav`: a click scrolls the card to the top, the column follows the
scrolling) – and the content beside it. A selection's actions float at the bottom of the results
(`#FloatingBar`, styled like `#CanvasToolbar`); the results keep room for it below their last row.

**A "&" in a button's or a menu item's text** is a shortcut mark to Qt (it underlines the next character):
texts like *Info & Hilfe* go through `.replace("&", "&&")` where they are set (segments and section headers do it
themselves).

**The header** (`widgets/header.py`, 4.0) replaces the sidebar: logo and name, the areas *Studio · Galerie ·
Warteschlange* (`window.nav_buttons`), the running job, the hardware and the menu **App** (`window.app_actions`:
models, settings, compare, phone, updates, about). Ctrl+1 … 7 follow what is seen from left to right
(`header.PAGES`); a menu item shows its key but only the window's shortcut triggers it (`Qt.WidgetShortcut`).
A new look = a new objectName or property in `theme.stylesheet()`, styled for both palettes.

**Keyboard focus** (`gui/focus_ring.py`): a 2 px ring in `focus`, 2 px outside the control, drawn by one overlay
per window while the keyboard is in use (hidden after a click, like `:focus-visible`). Text fields, spin boxes and
drop-downs show focus by their border instead. A focusable custom widget sets `ring_radius` (its corner radius) –
or `focus_ring = False` if it shows its focus itself. Never `setFocusPolicy(Qt.NoFocus)` on something clickable.

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
  `WrapRow`; a test checks the studio's columns at 1200 × 760. The left column scrolls there, so its parts get
  312 − 2 × 20 − 10 (scroll bar) − 1 (line) = 261 px – in German too (`test_studio_columns_fit_a_small_window`).
- **Shortcuts** live in `gui/shortcuts.py` (also listed on the About page).
- **Menus whose entries are kept** (in an attribute or a dict) make them in Python – `act = QAction(self)`,
  `menu.addAction(act)`; `sub = QMenu(self)`, `menu.addMenu(sub)`. An entry made by `menu.addAction("")` belongs
  to Qt, and its Python object can go stale (a later call on it raises `RuntimeError`).

## Text

- Every visible string goes through `tr("key")` with entries in **both** `en.json` and `de.json`, same order.
  Keys: `ui.<area>.<name>`, `param.<name>.label|help|choice.<v>`, `group.<g>`, `nav.<page>`, `method.<m>.*`.
- Widgets that show text implement `retranslate()` (connected to `i18n.language_changed`) – the language
  switches at run time without a restart.
- Voice: see the ux-copy skill. German uses "du".
- Numbers a person reads (scores, losses, sizes) go through `i18n.number(value, decimals)` and `i18n.size(mb)`:
  29,4 / 1,2 GB in German, 29.4 / 1.2 GB in English. Files, logs and the phone's data keep the dot.

## Accessibility rules the tests already enforce

| Rule | Test |
|---|---|
| Every text colour ≥ 4.5:1 on every surface, both themes | `tests/test_theme_contrast.py` |
| Every visible button has a name (text, tooltip, accessible name or a buddy label) | `test_gui.py::test_every_button_has_a_name` |
| Tab order (4.0): header → left column → middle → right column → footer → header | `test_gui.py::test_studio_tab_order` |
| Keyboard focus is visible; groups of choices are one Tab stop with arrows | `tests/test_focus_ring.py` |
| Pages use the spacing tokens | `test_gui.py::test_pages_use_the_spacing_tokens` |
| Empty pages explain the next step | `test_gui.py::test_empty_pages_say_what_to_do` |
| Columns fit the smallest window | `test_gui.py::test_studio_columns_fit_a_small_window` |
| Nothing in the studio's centre is cut at the smallest window (German) | `test_gui.py::test_nothing_in_the_studio_centre_is_cut_in_a_small_window` |
| Phone: chosen states, names of sliders and "?", tick boxes ≥ 24 px | `tests/e2e/test_phone_page.py::test_screen_readers_hear_what_is_chosen` |
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
