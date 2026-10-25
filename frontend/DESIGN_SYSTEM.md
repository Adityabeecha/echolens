# EchoLens: One Thing × Evidence Board

The product owner approved this look on 2026-10-25. **[design/approved/README.md](../design/approved/README.md) wins** if any detail here disagrees. Read the markup and inline styles of [Today](../design/approved/today.html), [the problem workbench](../design/approved/case.html), and [Landing](../design/approved/landing.html) as the exact visual contract. They are design-canvas sources, not app screens.

Every screen answers **what is wrong, how sure we are, and what to do next**, with proof one tap away. Do not improvise another visual language.

## Six simplicity rules

1. One primary ink button per screen region; everything else outline or text.
2. Open with a one-sentence answer in serif.
3. Summary → reason → proof, each one tap deeper. Never a wall of text.
4. Generous whitespace, dividers over boxes, at most one dark focus card per screen.
5. Empty states explain what happened and offer the next step.
6. Everything works at 375px and by keyboard.

Every number also needs a unit, a direction and a comparison. Keep loading space reserved. Prefer Undo for reversible actions. Errors explain recovery in plain words. Do not invent measurements for an empty product.

## Tokens and typography

Values live in `src/tokens.css`; `src/theme.ts` exports matching `var()` references. Use tokens, never a second palette. Light is the default; a saved theme still wins. `boot.js` and `themeMode.ts` agree before first paint. Components never inspect the theme to choose colours.

| Token / JS | Light | Dark | Purpose |
|---|---|---|---|
| `--el-ink` / `C.ink` | `#0B0B0F` | `#FFFFFF` | text, primary, selected border |
| `--el-paper` / `C.paper` | `#FFFFFF` | `#0B0B0F` | page |
| `--el-soft` / `C.soft` | `#F6F6F3` | `#17171D` | exhibits rail, chips |
| `--el-line` / `C.line` | `#E8E8E3` | `#2A2B33` | quiet dividers |
| `--el-line-strong` / `C.lineStrong` | `#D4D4CC` | `#3A3B45` | outlined controls, pending steps |
| `--el-muted` / `C.muted` | `#5B5F6B` | `#A1A3AE` | secondary text |
| `--el-body` / `C.body` | `#3A3C44` | `#C9CAD3` | prose |
| `--el-stamp-red` / `C.stampRed` | `#C2361F` | `#FF8D7E` | CONFIRMED, bad number, REOPENED |
| `--el-amber` / `C.amber` | `#9A5B00` | `#E9B65A` | HUNCH |
| `--el-pencil-blue` / `C.pencil` | `#2348C9` | `#9DB1FF` | REQUEST, LIVE, release notes, links |
| `--el-green` / `C.green` | `#127A45` | `#80D6A4` | FIX WORKED, checks |
| `--el-green-bg` / `C.greenBg` | `#EEF8F2` | `#13291D` | good news |
| `--el-green-deep` / `C.greenDeep` | `#0A5C33` | `#B0E4C6` | good-news prose |
| `--el-highlighter` / `C.highlighter` | `#FFE96A` | same | selected proof; always ink text |
| `--el-highlighter-soft` | `#FFFBDD` | same | selected reason; always ink text |

The focus card deliberately stays dark in both themes: `C.focus` is ink in light and `#17171D` with a `#3A3B45` border in dark. Its text is white, body `#C9CAD3`, captions `#A1A3AE`, stat tiles `#17171D`, red `#FF8D7E`, pencil `#9DB1FF`. Use the FocusCard part rather than manually inverting tokens.

**Geist** 400/500/600/700 (`sans`): UI, body and buttons. **Geist Mono** 400/500 (`mono`): stamps, letters, step numbers, versions. **Newsreader** 400/500 and italic 400 (`serif`): headlines, story, quotes and pencil notes. Google Fonts uses preconnect and `display=swap` with immediate fallbacks.

| `T` | Size | Use |
|---|---|---|
| `micro`, `xs`, `sm` | 11, 12, 13px | metadata |
| `base`, `md`, `lg`, `xl` | 15, 17, 22, 28px | UI/body scale |
| `page` / `display` | 60px, responsive | one page answer |
| `hero` | 76px, responsive | landing headline |
| `case` | 50px, responsive | problem title |
| `card` | 38px | focus-card title |
| `section` | 28px | Exhibits, Good news |
| `story`, `stat` | 22px / 1.7, 30px / 600 | narrative, numbers |

`S`: 4, 8, 12, 16, 20, 24, 32, 40, 48px. Approved radii: control 12px, stat/card 18px, exhibit 14px, good-news 22px, rail/overlay 24px, focus 28px, pill 999px. Exceptions copied from the canvases are encoded in the parts. Use 120ms selection feedback; stamps press once over 140ms. Only LIVE loops. Reduced motion stops all animation and transitions.

Legacy `C.bg`, `card`, `border*`, `text*`, `accent*`, `good*`, `bad*`, `info*`, `live*`, `cite*`, `verified*`, `lead*`, `regress*`, `overlay`, `inset`, `track`, plus `S`, `R`, `E`, `T` remain available. They alias the new palette so screens can migrate separately. New primary uses ink; red means a confirmed problem, never an uncertain error. `MEASURE` is 1200px; `PUBLIC_MAX` is 1280px.

## Shell and navigation

`AppHeader` owns the top bar: Sonar Prism, Newsreader wordmark, product switcher with measured health dot and demo tag, pill navigation, Ask field, quiet Workspace menu. There is **no left rail**. `Sidebar.tsx` is retained as a compatibility filename for the top/phone navigation component. Phones below 768px use Today · Problems · Plan · Ask · More at the bottom. More reaches every secondary destination. Reviewer actions Run investigation and Import CSV live in the menu; guests never see them.

Content is centred at max-width 1200px, including 32px side padding (20px on phones). Public pages use 1280px. Use `ScreenHeader` + `ScreenBody`, or `Workbench`, `Panel`, `Section`, `PublicContainer` from `ui.tsx`. `Panel` defaults flat; dividers before boxes. `Workbench split` keeps the existing keyboard-resizable split. Constrain long paragraphs to a readable measure inside the screen.

Labels/routes: Today `/today`; All problems `/cases`; Plan `/plan`; What we've learned `/intelligence`. Product scope is `/p/:id/...`. Existing `/memory`, `/patterns`, `/brain`, `/backlog`, legacy hashes, case tabs and Settings section redirects stay valid. Never invent a second router. The demo banner retains Sign in and Exit demo. Ask still uses the existing drawer and Cmd/Ctrl K.

## Plain words

| Internal term | On screen |
|---|---|
| finding / case | problem |
| anomaly / signal | spike |
| hypothesis | possible cause |
| evidence row | proof / exhibit |
| confidence 0.89 | we're 89% sure |
| single-source / needs_human | hunch |
| challenge | Think this is wrong? |
| fix watch | Fix shipped |
| create issue | Send to GitHub |
| guards | honesty checks |

Technical vocabulary belongs in tooltips, not navigation or main labels.

## Case-file parts

Import all parts and their exported types from `components/casefile`. They take plain typed props: no API calls and no invented data. Keep selection state in the screen so narrative, reasons and exhibits agree.

```tsx
import { Stamp, stampFor, LiveDot, SerifHeadline, FocusCard, StatTile, ReleaseChart,
  HighlightQuote, Exhibit, CitationLetter, ReasonRow, NumberedSteps, ListRow,
  GoodNewsCard, PillTabs, EmptyState } from '../components/casefile';
```

### Verdicts, brand and hierarchy

- **Stamp**: `<Stamp variant="confirmed" rotation={-6} />`. Variants `confirmed`, `hunch`, `request`, `fixWorked`, `reopened`; `live` renders LiveDot. `compact` uses 11px, otherwise 14px. Rotations normally −7°…+4°. A verdict always sits beside a title that explains the problem.
- **stampFor**: `<Stamp variant={stampFor(row)} />`. Accepts a `StampInput` compatible with a case row, investigation or finding. Precedence: running/queued → LIVE; regressed → REOPENED; confirmed fix → FIX WORKED; feature request → REQUEST; single-channel/capped/needs-human → HUNCH; explicit supported or `trust.two_source_ok` → CONFIRMED. A bare resolved status is **not proof** and earns HUNCH. `StatusBadge` delegates through this helper; legacy `StatusKind` and `statusKindFor` exports remain compatible.
- **LiveDot**: `<LiveDot label="Investigating now" />`. Only for work actually in progress, never a confirmed conclusion or a shipped fix still being watched.
- **Logo**: `import { Logo, LogoLockup } from '../components/Logo'`. `<Logo size={28} live decorative />` or `<LogoLockup size={28} />`. Approved 34-unit ink ring/prism and red beam; use 20–34px. `decorative` beside a visible wordmark. `live` is calm and reduced-motion safe. Favicon matches.
- **SerifHeadline**: `<SerifHeadline as="h1" size="page">One bug is costing you 0.84 stars.</SerifHeadline>`. Sizes `hero`, `page`, `case`, `card`, `section`. Use real heading order; a number here must come from actual data.

### The one thing that matters

```tsx
<FocusCard stamp={<Stamp variant={stampFor(row)} />} aside={<>
  <StatTile value="−0.84★" caption="off your rating in 4 weeks" tone="problem" />
  <ReleaseChart points={daily} releases={releases} ariaLabel="One-star reviews per day"
    unit="one-star reviews" caption="Last 30 days, compared with the previous month" />
</>}>
  <SerifHeadline as="h2" size="card">Battery drain since version 3.2.0</SerifHeadline>
  <p>The update keeps phones awake. <HighlightQuote>Phone dies by 2pm.</HighlightQuote></p>
  <Button variant="primary" onClick={openProof}>See the proof</Button>
</FocusCard>
```

**FocusCard**: 28px corners, 40px padding, equal story and stats columns; stacks on phones. Supply `children`, `aside`, optional `stamp`, and ordinary article attributes. One per screen. **StatTile** accepts `value`, `caption`, and `tone="neutral" | "problem" | "good"`; put all units/comparisons in the value or caption. **ReleaseChart** reuses TimelineChart's typed `points`, `releases`, optional `overlay`, `mode`, `unit`, `height`, `formatDate`; adds `caption`. Daily points are `{date, value}`, pins `{date, version, kind: 'release' | 'hotfix'}`. It preserves dates, counts and keyboard exploration (arrows, Home/End, Escape). Empty input states no data. Blue thin release pins use Newsreader italic pencil notes. Hover/focus details are announced by a live region.

### Proof and two-way selection

```tsx
<HighlightQuote active={selected === 'A'}>Phone dies by 2pm.</HighlightQuote>
<CitationLetter letter="A" selected={selected === 'A'} onSelect={setSelected} />
<Exhibit letter="A" kind="Play Store ★1" date="Oct 15" quote="Phone dies by 2pm."
  selected={selected === 'A'} tilt={-0.5} onSelect={setSelected} />
<ReasonRow letters={['A', 'D']} selected={reason === 'users'}
  onSelect={() => { setReason('users'); setLit(['A', 'D']); }}>
  Users describe the same thing, in their own words
</ReasonRow>
```

**HighlightQuote** marks only the exact proof substring. **CitationLetter** is a 22px real button with an accessible exhibit name and pressed state; `onSelect` receives its letter. **Exhibit** has a 30px letter, kind/date and 18px serif quote. `onSelect(letter)` selects it; `selected` adds a 2px ink border, 5px ink offset shadow and yellow proof. Unselected fades to 60%; `tilt` is degrees (normally ±0.6). **ReasonRow** is a green-check button with the plain reason and related `letters`. The screen owns related selection; never nest interactive controls inside these buttons.

### Next steps, lists and good news

```tsx
<NumberedSteps steps={[
  { id:'send', text:'Send it to your developers', action:<Button variant="primary">Review & send</Button> },
  { id:'ship', text:'Tell EchoLens when the fix ships', action:<Button>Fix shipped</Button> },
  { id:'watch', text:'We watch the reviews for 14 days', automatic:true },
]} />
<ListRow variant="hunch" title="App crashes after clearing cache"
  detail="Needs a second source" onClick={openProblem} />
<GoodNewsCard title="Your video-crash fix worked." action={<Button variant="primary">Write to the reviewers</Button>}>
  Complaints fell from 6 a day to zero after the fix.
</GoodNewsCard>
```

**NumberedSteps**: stable `id`, `text`, optional `action`, `automatic`. First human step is ink-filled; automatic is dashed/muted. The screen supplies working actions. **ListRow**: verdict column, title + one muted line, arrow; whole row is a button. **GoodNewsCard**: 22px green panel, FIX WORKED stamp and Newsreader title. Use only for measured improvement after a fix.

```tsx
<PillTabs tabs={[{id:'proof',label:'Proof'},{id:'next',label:'What to do next'}]}
  value={tab} onChange={setTab} label="Problem sections" panelId="problem-panel" />
<div role="tabpanel" id="problem-panel" aria-label="Proof">…</div>
<EmptyState title="No problems waiting." action={<Button onClick={connect}>Connect a source</Button>}>
  Connect reviews so EchoLens can notice what changed.
</EmptyState>
```

**PillTabs**: controlled generic string IDs; optional disabled items; arrows, Home/End select and move focus. Give the associated panel an accessible name. **EmptyState**: one clear sentence, explanatory children and a real next-step action. No decorative dashboard numbers.

## Existing shared parts and data

`CitationChip` / `CitedText`, `GuardBadge`, `TimelineChart`, `Sparkline`, `Gauge`, `Skeleton`, `ErrorState`, `Button`, and dialog hooks remain available. Citation chips retain hover/focus quotes; new narrative screens prefer CitationLetter for exhibit selection. Use `useAsync`'s existing cache/revalidation and `api.ts` for cookie + CSRF writes. Do not put backend terms into labels. Do not copy the sample numbers from the canvases into real screens.

## Dev gallery and verification

`/design` exists **only in Vite DEV**; it is never in navigation and its module/fixtures are excluded from production. It renders every part in four isolated frames: light/dark × 1200/375px. Open `/design?frame=1&theme=light` directly to inspect at a real viewport. All gallery measurements are clearly labelled reference fixtures. The shell in each frame uses the actual AppHeader; example action buttons only announce a local message.

Before a screen handoff: compare the canvases at 1440 and 375px in light and dark, exercise keyboard navigation, reduced motion, source/empty/error states and the one obvious next action. Run TypeScript, production build and every `frontend/scripts/*.mjs`. Do not commit screenshots or notes.
