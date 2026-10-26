import { useEffect, useState } from "react";
import { ProductRow } from "../../api";
import { ThemeMode, applyTheme } from "../../themeMode";
import { Button } from "../../ui";
import { AppHeader } from "../AppHeader";
import { Logo, LogoLockup } from "../Logo";
import { CitationLetter, EmptyState, Exhibit, FocusCard, GoodNewsCard, HighlightQuote, ListRow,
  LiveDot, NumberedSteps, PillTabs, ReasonRow, ReleaseChart, SerifHeadline, Stamp, StatTile } from ".";
import "./design-gallery.css";

const bars = [3,4,3,5,4,3,4,4,5,3,4,3,4,5,4,4,3,4,6,11,15,18,17,19,16,18,20,17,19,18];
const points = bars.map((value, i) => ({ date: `2026-10-${String(i + 1).padStart(2, "0")}`, value }));
const releases = [{ version: "3.2.0", date: "2026-10-19", kind: "release" as const }];
const product: ProductRow = { id:1, name:"Lumo", is_demo:true, package_name:null, github_repo:null, created_at:null };

/** DEV-only fixtures copy the approved canvas, not claims about a live product. */
export default function DesignGallery() {
  const params = new URLSearchParams(window.location.search);
  const frame = params.has("frame");
  const theme: ThemeMode = params.get("theme") === "dark" ? "dark" : "light";
  useEffect(() => applyTheme(theme), [theme]);
  if (frame) return <Parts theme={theme} />;
  return <div className="design-gallery"><SerifHeadline>Approved parts, ready to build with.</SerifHeadline>
    <p>Reference fixtures from design/approved/. Each frame has its own viewport. Scroll inside to inspect every part.</p>
    {(["light", "dark"] as const).map((mode) => <section key={mode}>
      <h2>{mode === "light" ? "Light — default" : "Dark"}</h2>
      <div className="design-gallery__frames">{[1200, 375].map((width) => <div key={width}>
        <h3>{width}px viewport</h3><iframe title={`${mode} parts at ${width}px`} width={width} height={1300}
          src={`/design?frame=1&theme=${mode}`} loading="lazy" />
      </div>)}</div></section>)}
  </div>;
}

function Parts({ theme: initialTheme }: { theme: ThemeMode }) {
  const [theme, setTheme] = useState(initialTheme);
  const [selected, setSelected] = useState("A");
  const [tab, setTab] = useState("proof");
  const [notice, setNotice] = useState("Select a letter, reason or exhibit to highlight its proof.");
  useEffect(() => applyTheme(theme), [theme]);
  const action = () => setNotice("Example action selected. This gallery never changes product data.");
  return <div className="design-parts">
    <AppHeader screen="today" go={action} products={[product]} productId={1} onSwitchProduct={action}
      onLogo={action} onAsk={action} askShortcut="⌘K" theme={theme} onThemeChange={setTheme} onLogout={action}
      onRunInvestigation={action} onImportCsv={action} />
    <main className="design-parts__body">
      <div><p className="design-caption">Approved canvas fixtures · not live product measurements</p>
        <SerifHeadline>One bug is costing you 0.84 stars.</SerifHeadline></div>
      <FocusCard stamp={<Stamp variant="confirmed" />} aside={<>
        <StatTile value="−0.84★" caption="off your rating in 4 weeks" tone="problem" />
        <StatTile value="62%" caption="of your 1★ reviews are about it" />
        <StatTile value="2 days" caption="after the update, it started" />
        <ReleaseChart points={points} releases={releases} ariaLabel="Example one-star reviews per day"
          unit="one-star reviews" caption="1★ reviews per day, last 30 days" />
      </>}>
        <div className="design-caption">Problem #2 · 3 independent sources agree</div>
        <SerifHeadline as="h2" size="card">Battery drain since version 3.2.0</SerifHeadline>
        <p>The new background photo sync keeps phones awake. One reviewer put it simply: <HighlightQuote>“Phone dies by 2pm since the update.”</HighlightQuote></p>
        <div className="design-actions"><Button variant="primary" onClick={action}>See the proof</Button><Button onClick={action}>Send to GitHub</Button></div>
      </FocusCard>
      <div className="design-two-col">
        <section><SerifHeadline as="h2" size="section">Also worth a look</SerifHeadline>
          <ListRow variant="hunch" title="App crashes after clearing cache" detail="Only reviews mention it so far — needs a second source" onClick={action} />
          <ListRow variant="request" title="People want a desktop version" detail="Example request · turn it into a spec" onClick={action} />
          <ListRow variant="live" title="Looking into a login loop" detail="Reading the release notes…" onClick={action} />
        </section>
        <section className="design-stack"><SerifHeadline as="h2" size="section">Good news</SerifHeadline>
          <GoodNewsCard title="Your video-crash fix worked." action={<Button variant="primary" onClick={action}>Write to the reviewers</Button>}>
            Complaints fell from 6 a day to zero after 3.1.4. Example from the approved canvas.
          </GoodNewsCard></section>
      </div>
      <section className="design-stack"><SerifHeadline as="h2" size="case">Battery drain since version 3.2.0</SerifHeadline>
        <PillTabs tabs={[{ id:"proof", label:"Proof" }, { id:"next", label:"What to do next" }]} value={tab}
          onChange={setTab} label="Example problem" panelId="design-tab-panel" />
        <div role="tabpanel" id="design-tab-panel" aria-label={tab === "proof" ? "Proof" : "What to do next"} tabIndex={0} className="design-stack">
          {tab === "proof" ? <div className="design-two-col">
            <div className="design-stack"><p className="design-story"><HighlightQuote active={selected === "C"}>Version 3.2.0 switched on background photo sync.</HighlightQuote>
              <CitationLetter letter="C" selected={selected === "C"} onSelect={setSelected} />
              <HighlightQuote active={selected === "A"}>People wrote that their phone was dead by two in the afternoon.</HighlightQuote>
              <CitationLetter letter="A" selected={selected === "A"} onSelect={setSelected} /></p>
              <ReasonRow letters={["A"]} selected={selected === "A"} onSelect={() => setSelected("A")}>Users describe the same thing, in their own words</ReasonRow>
              <ReasonRow letters={["B"]} selected={selected === "B"} onSelect={() => setSelected("B")}>Your developers already logged it on GitHub</ReasonRow>
              <ReasonRow letters={["C"]} selected={selected === "C"} onSelect={() => setSelected("C")}>The update came before the complaints</ReasonRow>
            </div>
            <aside className="design-exhibits"><SerifHeadline as="h3" size="section">Exhibits</SerifHeadline>
              <Exhibit letter="A" kind="Play Store review ★1" date="Oct 15" quote="“Phone dies by 2pm since the update. Never had this before.”" selected={selected === "A"} onSelect={setSelected} />
              <Exhibit letter="B" kind="GitHub issue #2841" date="Oct 16" quote="Wakelock not released when background sync retry fails." tilt={0.4} selected={selected === "B"} onSelect={setSelected} />
              <Exhibit letter="C" kind="Release note" date="Oct 13" quote="Version 3.2.0 — New: background photo sync, on by default." tilt={-0.3} selected={selected === "C"} onSelect={setSelected} />
            </aside></div> : <NextSteps onAction={action} />}
        </div>
      </section>
      <section className="design-stack"><SerifHeadline as="h2" size="section">What to do next</SerifHeadline><NextSteps onAction={action} /></section>
      <section className="design-stack"><SerifHeadline as="h2" size="section">The verdicts</SerifHeadline>
        <div className="design-stamps">{(["confirmed","hunch","request","fixWorked","reopened"] as const).map((variant) => <Stamp key={variant} variant={variant} />)}<LiveDot /></div>
      </section>
      <section className="design-stack"><SerifHeadline as="h2" size="section">The mark and headline scale</SerifHeadline>
        <div className="design-actions">{[20,28,34].map((size) => <Logo key={size} size={size} />)}<Logo live size={28} /><LogoLockup /></div>
        <SerifHeadline as="h3" size="hero">Find the root cause.</SerifHeadline>
      </section>
      <EmptyState title="No problems waiting for you." action={<Button variant="primary" onClick={action}>Connect a source</Button>}>
        Connect your reviews so EchoLens can notice what changed.
      </EmptyState>
      <p role="status" className="design-caption">{notice}</p>
    </main>
  </div>;
}

function NextSteps({ onAction }: { onAction: () => void }) {
  return <NumberedSteps steps={[
    { id:"send", text:"Send it to your developers — the issue is already written, with every exhibit attached", action:<Button variant="primary" onClick={onAction}>Review & send</Button> },
    { id:"ship", text:"When the fix ships, tell EchoLens the version", action:<Button onClick={onAction}>Fix shipped</Button> },
    { id:"watch", text:<>We watch the reviews for 14 days, then stamp it <strong>FIX WORKED</strong> — or reopen it</>, automatic:true },
  ]} />;
}
