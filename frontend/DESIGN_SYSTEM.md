# EchoLens design system — Sonar Prism

EchoLens listens to noisy customer echoes and focuses them into one verified
root cause: *acoustic forensics meets optical precision*. The people using it
are busy indie developers, not analysts. Every screen is built from this
document; read the UX principles first, then reuse the tokens and components
below instead of inventing new ones.

Source of truth: `src/tokens.css` (values), `src/theme.ts` (the same values as
`var()` references for inline styles), `src/ui.tsx` (primitives) and
`src/components/` (shared components).

---

## 1. UX principles — every screen follows these

1. **The 5-second test.** A first-time user can say, within five seconds of
   landing on any screen, *what is wrong*, *how bad it is* and *what to do
   next*. Lead with that sentence; everything else is below it.
2. **One primary action per screen.** Exactly one `Button variant="primary"`
   in view. Secondary actions are `quiet`/`ghost`. Destructive actions live
   out of the way (Settings, an overflow menu), never next to the primary one.
3. **Plain language.** Use the UI word, never the internal one. The technical
   term may appear only in a tooltip (`title`) or in docs:

   | Internal concept | Say in the UI |
   |---|---|
   | signal / anomaly | spike |
   | hypothesis | possible cause |
   | z-score | signal strength |
   | triage | decide what to investigate |
   | finding | what we found |
   | evidence | proof |
   | guard | honesty check |
   | supported (multi-source) | Smoking gun |
   | supported_single_channel | Working lead — awaiting 2nd source |
   | needs_human | Needs your call |
   | fix watch / FixWatch | Fix watch |
   | confirmed fix | Verified fix |

4. **Progressive disclosure.** Summary → reason → proof, each one click
   deeper. Never a wall of text: a paragraph longer than three lines gets a
   "Show why" disclosure.
5. **Every number carries a unit, a direction and a comparison.**
   "14.2% negative ↑ 3 pts vs last 4 weeks", not "14.2". Better/worse is
   colour *and* an arrow; the comparison is spelled out.
6. **Designed states.** Loading, empty and error states explain what is
   happening and offer the next step (`EmptyState` with an action,
   `ErrorState` with Retry). Never a blank panel.
7. **Forgiving.** Prefer an undo toast (`toast.action("Archived.", "Undo", …)`)
   to a confirmation dialog where the action is safe to reverse. Nothing
   important is irreversible by one click.
8. **Fast and calm.** Navigation is instant (cached reads, see §8), updates
   are optimistic, nothing shifts when data arrives (reserve the space), and
   motion only explains a change.
9. **Consistent.** The same component behaves the same everywhere. Keyboard
   reaches everything; ⌘K / Ctrl K opens Ask from any screen.
10. **Mobile is for reading and deciding.** At 375px a user can read a case
    and approve or challenge it — not just look at it.

Be creative within these rules: craft and delight, never added complexity.

---

## 2. Brand — the Sonar Prism mark

`components/Logo.tsx`. Concentric soundwave rings (the echoes) pass through a
prism and leave as one beam ending at a glowing node (the verified cause).

```tsx
import { Logo, LogoLockup } from "../components/Logo";

<Logo size={26} />                       // static mark, role="img", label "EchoLens"
<Logo size={26} live />                  // rings emanate + node glows: an investigation is running
<Logo size={20} decorative />            // beside a visible wordmark
<LogoLockup size={28} subtitle="Feedback forensics" />   // public pages
```

- Drawn on a 32-unit grid; crisp from 20px up. Do not recolour it: it reads
  its colours from tokens and follows the theme.
- `live` is used by the rail while any investigation runs. Under
  `prefers-reduced-motion` it is static.
- Favicon: `public/favicon.svg` (static mark on an obsidian tile).
- The logo links to Today for signed-in users and to the landing page for a
  demo guest.

---

## 3. Colour

Two themes, same vocabulary. **Dark** (default) is obsidian/carbon with
layered surfaces; **light** is a crisp, high-contrast slate. Themes switch by
`html[data-theme]`; never branch on the theme in components — use tokens.

### Surfaces and lines

| Token | `C.` | Use |
|---|---|---|
| `--el-bg` | `bg` | the canvas |
| `--el-bg-raised` | `bgRaised` | rail, header, banners |
| `--el-bg-card` | `card` | cards, raised panels, inputs |
| `--el-bg-overlay` | `overlay` | menus, popovers, tooltips |
| `--el-bg-inset` | `inset` | sunk secondary detail |
| `--el-bg-hover` / `--el-bg-active` | `hover` / `active` | interaction states |
| `--el-border` → `--el-border-4` | `border`…`border4` | 1px hairlines, escalating; `border4` is the 3:1 control edge |
| `--el-text` → `--el-text-ghost` | `text`…`ghost` | text, stepping down; all pass AA |

### Fixed semantics — these never change meaning

| Meaning | Token (`C.`) | Hue | Use for | Never for |
|---|---|---|---|---|
| Live AI work, citations | `live`, `cite` | cyan | running investigations, [ev_…] chips, the theme overlay on charts | decoration |
| Your move / primary | `accent` | indigo | the one primary button, focus rings, "Smoking gun" | status |
| Verified fix | `verified` | emerald | a fix measured to have worked, high health | "resolved" in general |
| Working lead | `lead` | amber-gold | single-source / capped conclusions, "needs a look" | errors |
| Regression | `regress` | coral/rose | **only** a confirmed multi-source regression | errors, destructive buttons, "bad" numbers |
| Everything else | text/border tokens | neutral | — | — |

Each semantic colour has `…Bg` and `…Line` companions for tinted pills.
`C.good`, `C.bad` and `C.info` are legacy aliases of `verified`, `regress`
and `live`; new code uses the semantic names.

**Errors and destructive actions are neutral.** An error state is a neutral
card with a warning icon and a plain sentence; a destructive button is a
`ghost` button inside a confirmation (or an undo toast). Red is not "bad";
it means "it came back".

---

## 4. Typography

- **UI and headings:** Plus Jakarta Sans (`sans`, `--el-font`), a geometric sans.
- **Data:** JetBrains Mono (`mono`, `--el-mono`) for versions (`v3.2.0`),
  SHAs, confidence (`0.89`), `[ev_001]` chips, costs (`$0.0031`), ids
  (`Case #34`), timestamps and tabular numbers. Add `className="el-num"` for
  tabular figures in sans text.
- Both from Google Fonts, loaded without blocking first paint (`index.html`).

| Token | `T.` | px | Use |
|---|---|---|---|
| `--el-fs-micro` | `micro` | 11 | mono labels, tags |
| `--el-fs-xs` | `xs` | 12 | dense metadata |
| `--el-fs-sm` | `sm` | 13 | secondary text, tables |
| `--el-fs-base` | `base` | 14 | body (default) |
| `--el-fs-md` | `md` | 16 | card / panel titles |
| `--el-fs-lg` | `lg` | 20 | screen titles |
| `--el-fs-xl` | `xl` | 26 | big section numbers |
| `--el-fs-display` | `display` | 40 | the one headline number |

Headings 600–700 with slight negative tracking (`--el-ls-tight`). Uppercase
mono labels use `--el-ls-wide` (see `Label`).

---

## 5. Space, shape, elevation, motion

- **Space** (`S.`): 4px base — 4, 8, 12, 16, 20, 24, 32, 40, 48. Lay out with
  flex/grid `gap`, not per-element margins.
- **Radius** (`R.`): `sm` 4 · `control` 7 · `card` 10 · `overlay` 14 · `pill`.
- **Elevation** (`E.`): `1` resting card · `2` hover / tooltip · `3` menu ·
  `4` modal. In dark mode each carries a 1px top highlight so a lifted plane
  reads as lifted, not dirty.
- **Motion:** `--el-dur-fast` 120ms, `--el-dur` 180ms, `--el-dur-slow` 320ms,
  `--el-ease`. Motion only explains a change (something arrived, moved,
  started running). Everything respects `prefers-reduced-motion`.

---

## 6. Layout

App screens are **full width**: there is no centred measure any more
(`--el-measure` is `none`, so `maxWidth: MEASURE` no longer caps). Keep line
length readable inside a block (`max-width: 62ch` on paragraphs), not by
narrowing the whole screen. Hierarchy comes from elevation, dividers and
whitespace — **not every block is an equal bordered box**.

```tsx
import { Workbench, Panel, Section, PublicContainer, ScreenHeader, ScreenBody } from "../ui";
```

### Workbench — the full-viewport grid

```tsx
<Workbench columns={3}>{/* three equal columns → 2 under 1100px → 1 under 900px */}</Workbench>

<Workbench split storageKey="case">   {/* 60/40, resizable, sticky right pane */}
  <CaseNarrative />                   {/* main: scrolls with the page */}
  <ProofRail />                       {/* side: sticky, scrolls on its own */}
</Workbench>
```

- `split` takes exactly two children. Drag the divider, or focus it and use
  ←/→ (Home resets). The ratio (35–75%) is remembered per `storageKey`.
- Under 900px everything stacks to one column and the side pane un-sticks.

### Panel and Section

```tsx
<Panel title="What we found" eyebrow="Step 2" actions={<Button>Copy</Button>}>…</Panel>  // flat (default)
<Panel tone="raised" title="Needs your call">…</Panel>   // the ONE thing that must stand out
<Panel tone="inset">…</Panel>                           // sunk secondary detail
<Section title="Proof" description="3 sources" divider>…</Section>
```

Use `flat` by default. At most one `raised` panel per view column.

### Public pages

`<PublicContainer>` caps at `--el-public-max` (1520px) with the gutter, for
the landing page and shared briefs.

### Screen frame

Each screen renders `ScreenHeader` (title · product · one-line subtitle ·
right-side actions) then `ScreenBody`. The shell already shows breadcrumbs, so
`ScreenHeader` is a flat title row, not a band.

---

## 7. App shell (owned by `App.tsx`)

- **Rail** (`components/Sidebar.tsx`): the logo, the product switcher (each
  product with a health dot from the portfolio rows: emerald healthy,
  neutral watch, amber needs attention), then **Today · Cases & Signals ·
  Quarter Plan · Intelligence** and **Portfolio · Sources · Settings**. The
  case workbench is reached from Cases. Nothing is locked: a screen with
  nothing in it shows an empty state. Collapsible (remembered); icon-only
  under 1200px; under 720px it becomes the bottom bar (Today, Cases, Plan,
  Ask, More).
- **Header** (`components/AppHeader.tsx`) on every app screen: breadcrumbs
  (Product / Screen / Case #N), the AI cost pill (this month vs cap, $/case,
  model — click opens Settings → Costs), Ask (⌘K / Ctrl K) and, for reviewers
  and admins only, **Run investigation** and **Import CSV**. Under 720px the
  compact mobile bar replaces it (logo, product, Ask, theme).
- **Demo banner:** a guest sees "You're exploring the demo · Sign in · Exit
  demo". Exit ends the guest visit and returns to the landing page; visiting
  `/` as a guest shows the landing page.
- **Routes:** `/p/:id/intelligence` is new (Learned patterns + a link to
  Settings → Calibration). `/memory`, `/patterns` and `/brain` redirect to
  it; `/calibration` and `/costs` redirect to their Settings sections.

Screens get callbacks from the shell (`onOpenCase`, `go(...)`); they never
render their own nav or header bar.

---

## 8. Data loading — instant navigation

`useAsync(fn, deps, { key? })` (`src/hooks.ts`) keeps the last successful
result per **call site + deps** in memory. A revisit renders it immediately
and revalidates in the background.

```tsx
const { data, error, loading, refreshing, reload } = useAsync(() => api.sources(), []);
if (loading) return <Skeleton rows={3} />;      // true ONLY on a first load
if (error && !data) return <ErrorState onRetry={reload} />;
// `refreshing` → optionally a quiet inline indicator; never a skeleton
```

- `loading` is false whenever cached data exists, so a skeleton never
  flashes on revisit. `Skeleton` also waits 150ms before appearing.
- The cache is cleared on product switch and sign-out (the shell does this).
- Writes go straight through (`api.*` calls), then `reload()`.
- Pass `{ key }` only to share one cache entry between two call sites on purpose.

---

## 9. Components — stories

The data in these stories (`api.timeline`, `api.citations`, `inv.guards`,
`finding.causal_chain`) comes from the forensics read endpoints
(`GET /timeline`, `/investigations/{id}/citations`, `/guards/*`); the
components themselves take plain props and work with any source.

### CitationChip / CitedText — `components/CitationChip.tsx`

```tsx
// One chip. Hover or keyboard focus shows the quote; Enter/click selects.
<CitationChip id="ev_001" quote="Phone dies by 2pm since the update." source="Play Store · 1★"
  active={hovered === "ev_001"}
  onHover={setHovered}            // id on enter/focus, null on leave/blur → highlight the proof row
  onSelect={openEvidence} />

// Prose with inline [ev_…] tags → chips, quotes looked up lazily.
<CitedText text={finding.prose} activeId={hovered}
  getQuote={(id) => evidence.find((e) => e.id === id)?.snippet}
  onHover={setHovered} onSelect={openEvidence} />
```

Two-way highlighting: the proof list sets `hovered` on its rows too, and
passes `active` back to the chips. `GET /investigations/{id}/citations` gives
`claim_spans` (sentence indexes) and `highlight` (the exact quoted substring)
for the reverse direction.

### StatusBadge — `components/StatusBadge.tsx`

```tsx
<StatusBadge kind="smoking_gun" />      // Smoking gun — confirmed by 2+ independent sources (indigo)
<StatusBadge kind="working_lead" />     // Working lead — awaiting 2nd source (calm amber)
<StatusBadge kind="fix_watch" />        // Fix watch (cyan: the machine is watching)
<StatusBadge kind="verified_fix" />     // Verified fix (emerald)
<StatusBadge kind="regressed" />        // Regressed (coral — confirmed regressions only)
<StatusBadge kind="resolved" />         // Resolved (neutral)
<StatusBadge kind="working_lead" compact />   // short label; full label in the tooltip

const kind = statusKindFor(row.case_status, finding?.support_level, finding?.fix?.status);
{kind && <StatusBadge kind={kind} />}
```

Every badge is colour + glyph + words. Lists of running/queued cases keep
using `statusMeta()` from `src/status.ts`.

### GuardBadge — `components/GuardBadge.tsx`

```tsx
{inv.guards?.map((g) => (
  <GuardBadge key={g.key} status={g.status} label={g.label} detail={g.detail} />
))}
```

Status words: Passed · Capped · Trimmed · Blocked · Not needed. Only `capped`
takes colour (amber); the others are neutral, told apart by glyph. In copy,
guards are **honesty checks**.

### TimelineChart — `components/charts/TimelineChart.tsx`

```tsx
const t = await api.timeline(30, caseId);
<TimelineChart
  ariaLabel="Negative reviews per day, last 30 days"
  points={t.series.map((d) => ({ date: d.date, value: d.negative }))}
  overlay={t.theme?.series.map((d) => ({ date: d.date, value: d.total }))}
  overlayLabel="mention this problem"
  releases={t.releases}              // pins: "v3.2.0 shipped" / "hotfix v3.2.1"
  unit="negative reviews"
  height={200} />
```

Hand-rolled SVG (no chart library), responsive to its container, tooltips on
hover, keyboard-explorable (Tab, ←/→, Home/End) with the tooltip mirrored to a
live region. `mode="line"` draws the main series as a line.

### Sparkline — `components/charts/Sparkline.tsx`

```tsx
<Sparkline values={weekly} />                                   // decorative, beside a number
<Sparkline values={rates} tone="verified" label="Complaint rate since the fix: falling" />
```

`tone` follows the fixed semantics; default neutral.

### Gauge — `components/charts/Gauge.tsx`

```tsx
<Gauge value={row.health} label="Health" caption="vs 74 last week" size={120} />
```

0–100, higher is healthier: emerald ≥75, neutral 45–74, amber <45, "—" with
no data. `role="meter"` with a spoken value.

### Skeleton — `ui.tsx`

`<Skeleton rows={3} height={74} />` — only when `loading` (true first load).

---

## 10. Accessibility checklist

- Visible focus everywhere (global `:focus-visible` ring in `--el-accent`).
  Never remove it without replacing it.
- AA contrast: use the text tokens; they are measured on their surfaces.
- State is never colour alone: pill + glyph + words; numbers carry arrows.
- Every interactive thing is a real `<button>`/`<a>`; menus and dialogs close
  on Escape and return focus (`useDialog`).
- `prefers-reduced-motion`: the logo, live dots and transitions stand still.
- Phone width (375px): no horizontal page scroll; wide content scrolls inside
  its own container.

## 11. Don't

- Don't hardcode a hex or rgba — add a token.
- Don't use coral for anything but a confirmed regression.
- Don't add a second primary button, a second font, or a chart library.
- Don't cap a screen's width; cap a paragraph's.
- Don't box every block — one raised panel per column, the rest flat.
- Don't show a skeleton over data the user has already seen.
