# EchoLens — approved design (Round 2 target)

Approved by the product owner on 2026-10-25: **"One Thing × Evidence Board"**,
radical simplicity with the personality of a case file. Every screen of the
redesign copies this. When this file and `frontend/DESIGN_SYSTEM.md` disagree,
this file wins — DESIGN_SYSTEM.md is updated to match it in the first prompt
of the round.

Reference screens in this folder (design-canvas sources: read the markup and
its inline styles as the exact spec; they are not meant to run in the app):

| File | Screen |
|---|---|
| `today.html` | Today |
| `case.html` | Case workbench (interactive: letters and reasons highlight exhibits) |
| `landing.html` | Public landing page (interactive "how it works" explorer) |

Copy layout, hierarchy, copy tone, spacing and values from these files.
Screens that were not drawn (All problems, Plan, What we've learned,
Portfolio, Sources, Settings, Onboarding, Login) are built from the same
parts and rules below — they must look like they came from the same hand.

## The idea in one line

Every screen answers *what's wrong, how sure we are, and what to do next* in
plain words — and shows its proof like evidence in a case file.

## Type

- **Geist** (400/500/600/700) — all UI, buttons, labels, body.
- **Geist Mono** (400/500) — stamps, exhibit letters, step numbers, small
  technical labels, versions in monospace contexts.
- **Newsreader** (400/500, italic 400) — page headlines, case titles,
  the story prose, exhibit quotes, section titles like "Exhibits",
  "Good news", and *pencil notes* (italic).
- Headline sizes: page headline 56–60px (landing hero 76px), case title
  50px, card title 38px, section title 26–28px; letter-spacing tight
  (−0.5 to −2.5px). Body 15–18px; story prose 22px / 1.7.

## Colour (light — the default)

| Token | Hex | Use |
|---|---|---|
| ink | `#0B0B0F` | text, primary buttons, the focus card, selected states |
| paper | `#FFFFFF` | page ground |
| soft | `#F6F6F3` | panels (exhibits rail, landing bands), chips |
| line | `#E8E8E3` | dividers, quiet borders |
| line-strong | `#D4D4CC` | secondary button borders, dashed "pending" boxes |
| muted | `#5B5F6B` | secondary text (AA on paper) |
| body | `#3A3C44` | long body text |
| card-2 | `#17171D` | stat tiles inside the dark focus card |
| on-dark-muted | `#A1A3AE` / `#C9CAD3` | text on the focus card |
| stamp-red | `#C2361F` (on dark `#FF8D7E`) | CONFIRMED, the bad number |
| amber | `#9A5B00` | HUNCH (dashed) |
| pencil-blue | `#2348C9` (on dark `#9DB1FF`) | REQUEST, LIVE, pencil notes, release pins, links |
| green | `#127A45` · bg `#EEF8F2` · deep `#0A5C33` | FIX WORKED, checks, good news |
| highlighter | `#FFE96A` (soft `#FFFBDD`) | proof being looked at; selected reason |

Colour carries meaning only — never decoration. Red means a confirmed
problem, never "error styling" for something uncertain.

**Dark mode**: ground `#0B0B0F`, raised `#17171D`, lines `#2A2B33`, text
`#FFFFFF` / `#C9CAD3` / `#A1A3AE`; stamps and pencil use their on-dark
variants; the highlighter stays `#FFE96A` with ink text. The focus card
inverts to paper-on-ink → use `#17171D` with a 1px `#3A3B45` border.

## The parts

- **Top bar** (no left rail): serif wordmark with the Sonar Prism mark (red
  beam), a product switcher right after it ("Lumo ▾"), a pill nav —
  *Today · All problems · Plan · What we've learned* — and on the right the
  Ask field ("Ask about your reviews… ⌘K") plus a quiet menu for Sources,
  Settings, All products, theme and sign-out. Content is centred:
  max-width 1200px app, 1280px landing, 32–40px side padding. On phones the
  pill nav becomes a bottom bar (Today · Problems · Plan · Ask · More).
- **Stamp** — the verdict, Geist Mono 11–15px, letter-spacing 2–3px,
  uppercase, 2–3px border, radius 3–4px, rotated −7°…+4°:
  `CONFIRMED` (red solid) · `HUNCH` (amber dashed — single source / working
  lead / not enough proof) · `REQUEST` (blue solid) · `FIX WORKED` (green
  solid) · `REOPENED` (red dashed — fix didn't hold) · `LIVE` (blue dot with
  halo — being investigated now, not a stamp border). Stamps never replace
  words; the title next to them says what it is.
- **Focus card** — the one thing that matters: ink background, radius 28px,
  40px padding, two columns (story + action left, 3 stat tiles + chart right),
  stamp in the top-right corner, one white primary button + one outline.
- **Stat tile** — big number (30px/600), one plain-language caption
  ("off your rating in 4 weeks"). Every number has a unit and a comparison.
- **Release-pinned chart** — simple bars, the release as a thin vertical
  line with a *pencil note* in Newsreader italic ("version 3.2.0 ships →").
- **Highlighted quote** — `#FFE96A` behind the words that prove it.
- **Exhibit** — white card on the soft rail, letter circle A–E (Geist Mono),
  kind · date in muted 12px, the quote in Newsreader 18px; tilt ±0.6°.
  Selected: 2px ink border, 5px 5px 0 ink offset shadow, highlighted quote,
  yellow letter; unselected exhibits fade to 60%.
- **Citation letter** — 22px circle inline in the prose; tapping it
  highlights its sentence and its exhibit (and the reverse).
- **Reason row** — "Why we're sure": green check circle, plain sentence,
  exhibit letters on the right; selecting it lights up those exhibits.
- **Numbered steps** — "What to do next": the first step is an ink-filled
  row with the main button; later steps are outlined; the automatic step is
  dashed and muted.
- **List row** — stamp column (fixed width) · title + one muted line · ›.
- **Good-news card** — green bg, FIX WORKED stamp, serif headline, one
  green button.

## Words (plain language — use these on screen)

Problem (not finding/case) · spike (not anomaly/signal) · possible cause
(not hypothesis) · proof / exhibit (not evidence row) · "we're 89% sure"
(not confidence 0.89) · hunch (not single-source / needs_human) ·
"Think this is wrong?" (not challenge) · "Fix shipped" · "Send to GitHub" ·
honesty checks (not guards). Technical terms may appear in tooltips only.

## Motion

Calm. Stamps press in once when they first appear (scale 1.12 → 1,
140ms). Selection changes animate border/shadow in 120ms. Nothing loops
except the LIVE dot. All of it off under `prefers-reduced-motion`.

## Rules that keep it simple

1. One primary (ink) button per screen region; everything else outline or text.
2. Headline first: every screen opens with a one-sentence answer in serif.
3. Summary → reason → proof, each one tap deeper; never a wall of text.
4. Generous whitespace; dividers over boxes; at most one dark card per screen.
5. Empty states speak plainly and offer the next step.
6. Everything works at 375px wide and by keyboard.
