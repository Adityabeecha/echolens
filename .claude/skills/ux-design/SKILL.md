---
name: ux-design
description: Use when designing, building, or improving any UI/UX in the EchoLens frontend (React + Vite + TS in frontend/) — new screens, components, modals, states, flows, copy, or visual polish. Load this BEFORE writing UI code so the work stays consistent with EchoLens's design system and UX principles. Triggers on "UI", "UX", "screen", "component", "layout", "login", "design", "make it nicer", "polish", "empty state", "loading", "error state", "responsive", "accessibility".
---

# EchoLens UX Design

EchoLens is a **dark, operated tool** — a "Feedback Forensics" console, not a document. It is scanned and acted on, so the craft is **information design first, typography second**. Match this skill's rules; the goal is that any new screen looks like it was always part of the app.

## 0. Non-negotiable order of authority
1. The user's explicit words for this task.
2. The existing design system — `frontend/src/theme.ts` (color/type tokens) and `frontend/src/tokens.css` (globals, keyframes). **Never hardcode a hex; always use a `C.*` token.** Never introduce a second font — it's IBM Plex Sans (UI) + IBM Plex Mono (data/labels).
3. Everything below.

## 1. The design system (use it, don't reinvent it)
- **Color:** import `{ C }` from `../theme`. Grounds: `C.bg` / `C.bgRaised`; surfaces: `C.card` / `C.card2`, hover `C.hover`. Borders escalate `C.border` → `C.border4`. Text steps down `C.text` → `C.text2/3` → `C.muted` → `C.dim` → `C.faint` → `C.ghost`. **Accent is amber `C.accent`** (hover `C.accentHi`) — spend it sparingly on the primary action and live state. **Semantic color is separate from the accent:** `C.good` (resolved/positive), `C.bad` (failure/critical), `C.info` (tool/neutral-blue). Use `statusColor()` / `confColor()` from theme for status + confidence.
- **Type:** `sans` for UI, `mono` for data, IDs, timestamps, labels, code, and anything tabular. Uppercase mono labels get `letterSpacing: ".08–.1em"` (see the `Label` component in `ui.tsx`). Headline weight 600–700 with slight negative letter-spacing; body 1.4–1.6 line-height.
- **Spacing & layout:** flex/grid with `gap`, not per-element margins. Cards: `padding` 13–22px, `borderRadius` 8–12px, `1px solid C.border2`. Wide content (tables, trace) scrolls inside its own `overflow-x/y:auto` container — the page body never scrolls sideways.
- **Reuse the primitives** in `frontend/src/ui.tsx` before writing new ones: `Label`, `Bar` (meters/confidence), `Spark`, `Dot`, `Chip`, `PrimaryButton`, `GhostButton`, `Centered`, `ScreenHeader`. New shared primitives go there too.

## 2. UX principles for this tool
- **Summary before detail.** Put the state that needs attention at the top/left; detail below/right. (Case Feed leads with severity + triage chip; Investigation leads with the live status pill.)
- **Encode state in form, not just words.** A status is a colored pill/chip/severity stripe *and* a label, so it reads at a glance. Confidence is a bar *and* a number. Never rely on text alone for state.
- **Every action gives feedback.** A button says exactly what it does ("Start investigation"), enters a busy state ("Starting…"), and results in a visible change or a toast. A control that can fail must **surface the reason inline** — never fail silently (this was a real bug: the New Case modal did nothing on 401).
- **Every async surface has three states.** loading, empty (with a next action — "Run the detector"), and error (what went wrong + how to fix). Use `Centered` for full-screen states. Never render a blank panel.
- **Live is a first-class state.** Investigations stream; show motion (pulse dot, `elGlow`) while running and a clear terminal state when done. Auto-scroll the trace but let the user toggle "follow".
- **Take the user to the thing they made.** After an action that creates something (a case), navigate them to it, don't drop them on a list to hunt for it.
- **Names are what the user recognizes.** Show the case's typed description, not `manual case`; "Possible causes", not "hypotheses" internally-facing; "Needs your call", not `needs_human`. Copy is design material — active voice, say what happens.

## 3. Both-safe, accessible, responsive
- The app is single-theme dark by deliberate choice — keep it; don't add a half-done light mode. If a light mode is ever requested, do it token-level in `tokens.css`, not by inverting.
- Interactive things must **look** interactive (cursor pointer, hover state) and have a visible keyboard focus (the global `:focus-visible` outline in `tokens.css` handles most — don't remove it). Modals/sheets close on `Esc` and on scrim click.
- Respect `prefers-reduced-motion` (already wired in `tokens.css` — don't override it with inline `animation` that can't be disabled; prefer the named keyframes `elPulse`/`elGlow`/`elBar`).
- Reflow, don't break, on narrow widths: use a width check (see `Login.tsx`'s `narrow` state) or flex-wrap. The page body must never scroll horizontally.

## 4. Copy voice
Plain, from the user's side of the screen. Active voice. A control names its effect; the result confirms it. Errors explain what went wrong **and** the fix ("You need reviewer access to start an investigation." not "403"). Specific over clever. No emoji as section markers.

## 5. Before you ship a UI change — checklist
- [ ] Every color is a `C.*` token; no raw hex, no second font.
- [ ] Reused `ui.tsx` primitives where one fit; new shared ones added there.
- [ ] Loading + empty + error states all handled; empty states name the next action.
- [ ] Every button: clear label, busy state, visible result or inline error.
- [ ] State shown as form + label (pill/bar/stripe), not text alone.
- [ ] Interactive elements have hover + keyboard focus; modals close on Esc/scrim.
- [ ] Narrow-width reflow checked; body never scrolls sideways.
- [ ] Copy is plain, active, and user-facing (no internal jargon or status enums).
- [ ] `cd frontend && npm run build` type-checks clean before committing.

## 6. Verify
Always finish with `cd frontend && npm run build` (runs `tsc` — catches type + prop errors). For behavior, run the app (`npm run dev` + backend `echolens serve`) and drive the actual flow you changed; don't assume it renders.
