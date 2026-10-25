import { useState } from "react";
import { Exhibit, ReleaseChart, Stamp } from "../../components/casefile";
import { TimelinePoint } from "../../components/charts/TimelineChart";

// The hero's stamped example: the battery case from the live demo (Lumo,
// version 3.2.0, a sync wakelock), drawn small. It is labelled "Example" on
// screen; the numbers are an illustration of its shape, not a measurement.
const ONE_STAR = [3, 4, 3, 5, 4, 3, 4, 4, 5, 3, 4, 3, 4, 5, 4, 4, 3, 4, 6, 11, 15, 18, 17, 19, 16, 18, 20, 17, 19, 18];
const DAY0 = Date.UTC(2026, 8, 1);
const day = (i: number) => new Date(DAY0 + i * 86_400_000).toISOString().slice(0, 10);
const POINTS: TimelinePoint[] = ONE_STAR.map((value, i) => ({ date: day(i), value }));
const RELEASES = [{ version: "3.2.0", date: day(18), kind: "release" as const }];

export function ExampleCase() {
  const [selected, setSelected] = useState("A");
  return (
    <article aria-label="Example problem" className="pub-example">
      <Stamp variant="confirmed" rotation={-7} />
      <div className="pub-example__eyebrow">Example · Lumo, the demo photo app</div>
      <h2 className="pub-example__title">Battery drain since version 3.2.0</h2>
      <div className="pub-example__chart">
        <ReleaseChart points={POINTS} releases={RELEASES} height={124} unit="one-star reviews"
          ariaLabel="Example: one-star reviews per day, rising after version 3.2.0"
          caption="1★ reviews per day" />
      </div>
      <div className="pub-example__exhibits">
        <Exhibit letter="A" kind="Play Store ★1" date="after the update" tilt={-0.6}
          quote="“Phone dies by 2pm since the update.”" selected={selected === "A"} onSelect={setSelected} />
        <Exhibit letter="B" kind="GitHub issue" date="same week" tilt={0.5}
          quote="Wakelock not released when sync retry fails." selected={selected === "B"} onSelect={setSelected} />
      </div>
    </article>
  );
}
