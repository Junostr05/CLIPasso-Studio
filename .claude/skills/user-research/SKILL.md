---
name: user-research
description: Plan and run lightweight user research for CLIPasso Studio as a solo maker – quick usability tests of the studio or the phone remote, first-run observation, interview and survey questions for people who sketch, plot or cut, and test scripts with realistic tasks. Use for "usability test", "interview guide", "survey", "how do I find out if people get X?", or before redesigning a flow.
argument-hint: "<question to answer, flow, or audience>"
---

# User research – small, fast, real

This app is made by one person; research has to fit into an evening. Five people doing real tasks beat any
survey. Results go into `/research-synthesis`; fixes into `/design-critique`, `/ux-copy`, `/design-handoff`.

## Who uses it (assumptions to check, not facts)

| Group | Wants | Typical setup |
|---|---|---|
| Hobby artists, illustrators | a nice line drawing of their photo, styles, prints | Windows laptop, no NVIDIA GPU |
| Plotter / Cricut / laser makers | clean single-layer SVG, few strokes | CPU, exports "SVG · 1 layer" |
| AI / research tinkerers | every parameter of the papers, method comparison | NVIDIA GPU, CLI |
| Phone users | start a sketch from the sofa, see it draw | the phone remote on Wi-Fi or Tailscale |

## Methods that fit

| Method | When | Effort |
|---|---|---|
| **5-person task test** (remote screen share or side by side) | a flow feels unclear | 1 evening |
| **First-run watch** – a newcomer installs the portable exe and makes a first sketch | onboarding, the tour, model downloads | 30 min each |
| **Phone test** on 2–3 real phones (iPhone + Android, light + dark) | phone page changes | 30 min |
| **5-question survey** linked from the release notes | which methods/exports people use | 1 hour + waiting |
| **Issue follow-up** – ask the reporter one question | a bug report hides a design problem | minutes |

## Task test script (adapt)

Setup: the current release on a clean Windows user account, a photo they brought, no explanations.
Say: "Think aloud. We are testing the app, not you."

1. Turn your photo into a line drawing. *(method choice, model download, waiting, time estimate)*
2. Make it simpler / with fewer lines. *(presets, strokes, Simplify, abstraction)*
3. Save it so you can cut it with a plotter / put it on a website. *(export formats, SVG · 1 layer, Lottie)*
4. Find the drawing you made earlier and try another method on it. *(gallery, compare)*
5. Start a sketch from your phone. *(QR code, PIN, phone page)*

Note per task: success (yes / with help / no), time, where they hesitated, exact quotes. Don't help until they
are truly stuck; then note what unblocked them.

## Interview guide (20 min)

1. What do you make? With which tools? Where does the drawing go afterwards?
2. Tell me about the last time you turned a photo into a drawing. What was annoying?
3. *(show the app)* What do you expect this screen to do? What would you click first?
4. What would make you come back to it? What would make you stop?
5. Anything I should have asked?

## Survey (≤ 5 questions)

Which method do you use most? · Which export? · CPU or NVIDIA GPU? · What took longest to figure out? ·
One thing you would change? – Multiple choice where possible, one open question at most.

## Ethics, light

Ask before recording; keep notes without names; delete raw recordings after the synthesis; never put
participants' photos in the repository or screenshots without permission.

## Deliverable

```markdown
## Research plan: <question>
**Decision it informs:** … | **Method:** … | **People:** 5 × <group> | **When:** …
**Tasks / questions:** …
**What would change our mind:** …
```
After the sessions: paste the notes into `/research-synthesis`.
