import { KeyboardEvent, useId, useState } from "react";

// The loop in five steps. Each sentence describes what the product does today
// (collection every 6 hours, the refutation pass, the 14-day fix watch); the
// "In the demo" line points at something a visitor can actually open there.
const STEPS = [
  { title: "Notice",
    body: "Every 6 hours EchoLens reads your new reviews and issues, and flags anything that changed: a spike in 1★ reviews, a rating drop, a new complaint.",
    demo: "1★ reviews about battery jumped right after version 3.2.0 shipped." },
  { title: "Investigate",
    body: "An agent tests competing explanations, step by step, the way an analyst would — and you can watch every step it takes.",
    demo: "It compared versions, read the release notes and searched GitHub." },
  { title: "Prove",
    body: "Each claim points to an exhibit you can open: a review, an issue, a release note. No exhibit, no claim.",
    demo: "Open any problem and tap a letter to see the review or issue behind that sentence." },
  { title: "Decide",
    body: "You approve, push back, or park it. Approving writes the GitHub, Linear or Jira issue for you, with the exhibits attached.",
    demo: "One click turns a problem into a ready-to-file GitHub issue." },
  { title: "Confirm the fix",
    body: "After your fix ships, EchoLens watches the reviews for 14 days and stamps it FIX WORKED — or reopens the problem.",
    demo: "The 4K-video crash fix is stamped FIX WORKED, with the before-and-after chart." },
];

/** Tabs at the canvas's size: arrow keys, Home and End move and select. */
export function HowItWorks() {
  const [step, setStep] = useState(2);
  const uid = useId();
  const current = STEPS[step];

  const onKey = (event: KeyboardEvent<HTMLButtonElement>) => {
    const last = STEPS.length - 1;
    const next = event.key === "ArrowRight" || event.key === "ArrowDown" ? (step + 1) % STEPS.length
      : event.key === "ArrowLeft" || event.key === "ArrowUp" ? (step - 1 + STEPS.length) % STEPS.length
      : event.key === "Home" ? 0 : event.key === "End" ? last : -1;
    if (next < 0) return;
    event.preventDefault();
    setStep(next);
    document.getElementById(`${uid}-tab-${next}`)?.focus();
  };

  return (
    <>
      <div role="tablist" aria-label="How it works" className="pub-steps">
        {STEPS.map((s, i) => (
          <button key={s.title} type="button" role="tab" id={`${uid}-tab-${i}`} className="pub-step"
            aria-selected={step === i} aria-controls={`${uid}-panel`} tabIndex={step === i ? 0 : -1}
            onClick={() => setStep(i)} onKeyDown={onKey}>
            <span className="pub-step__n" aria-hidden>{String(i + 1).padStart(2, "0")}</span>
            <span className="pub-step__title">{s.title}</span>
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`${uid}-panel`} aria-labelledby={`${uid}-tab-${step}`} className="pub-panel">
        <p>{current.body}</p>
        <div className="pub-panel__demo"><b>In the demo:</b> {current.demo}</div>
      </div>
    </>
  );
}
