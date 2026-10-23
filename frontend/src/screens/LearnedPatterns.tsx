import { LearnedView } from "../nav";
import { ScreenHeader } from "../ui";
import { SubTabs } from "../components/SubTabs";
import { Brain } from "./Brain";
import { Patterns } from "./Patterns";

interface Props {
  productName: string | null;
  view: LearnedView;
  onView: (view: LearnedView) => void;
  onOpenInvestigation: (id: number, status?: string) => void;
  onGoCases: () => void;
}

const TABS: { key: LearnedView; label: string }[] = [
  { key: "map", label: "How it breaks" },
  { key: "fixes", label: "Proven fixes" },
];

/**
 * Learned patterns — everything EchoLens has learned about this product, in
 * one place.
 *
 * It used to be two System screens, Patterns and Product memory, each with an
 * empty state pointing at the other. They answer one question at two levels
 * of proof: "how does this product tend to break?" (learned from causes) and
 * "which fixes are proven to work?" (learned from verified fixes). Two tabs,
 * one nav entry. The tab is in the URL, so old #/patterns links land on
 * Proven fixes.
 */
export function LearnedPatterns({ productName, view, onView, onOpenInvestigation, onGoCases }: Props) {
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      <ScreenHeader
        title="Learned patterns"
        product={productName}
        subtitle="How this product breaks, and the fixes proven to work"
      />
      <SubTabs label="Learned patterns" tabs={TABS} active={view} onChange={onView} />
      <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
        {view === "map" ? (
          <Brain embedded onOpenInvestigation={onOpenInvestigation} onGoCases={onGoCases}
                 onGoPatterns={() => onView("fixes")}
                 onBack={() => onView("map")} backLabel="" />
        ) : (
          <Patterns embedded onGoMemory={() => onView("map")} onGoCases={onGoCases} />
        )}
      </div>
    </div>
  );
}
