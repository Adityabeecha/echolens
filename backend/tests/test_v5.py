"""v5.0 tests: calibration curve, structured challenge autopsies, weak-spot
prompt guidance, the counter-evidence (refutation) duty in every resolved
investigation, and near-duplicate evidence merging."""
from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from echolens.calibration import calibration, guidance_text, weak_spots
from echolens.db.models import (
    AnomalyEvent, Base, Finding, Investigation, ReviewFeedback, TraceStep)
from echolens.eval.harness import scenario_clear_cause
from echolens.synthetic.generate import generate


def _session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    generate(s)
    s.commit()
    return s


def _seed_reviewed(s, specs):
    """specs: list of (confidence, verdict, reason). Creates findings + feedback."""
    anomaly = s.scalars(select(AnomalyEvent)).first()
    for i, (conf, verdict, reason) in enumerate(specs):
        inv = Investigation(anomaly_id=anomaly.id, status="resolved", opened_by="anomaly",
                            budget_tier="quick", budget_json={})
        s.add(inv); s.flush()
        f = Finding(investigation_id=inv.id, summary=f"finding {i}", confidence=conf,
                    status="approved" if verdict == "approve" else "challenged", json={"confidence": conf})
        s.add(f); s.flush()
        s.add(ReviewFeedback(finding_id=f.id, action=verdict, note="n", reason=reason))
    s.commit()


# ── calibration curve (exit criterion #1) ───────────────────────────────

def test_calibration_curve_and_headline():
    s = _session()
    # 20 reviewed findings: high-confidence ones mostly approved
    specs = [(0.85, "approve", None)] * 8 + [(0.85, "challenge", "wrong_cause")] * 2
    specs += [(0.65, "approve", None)] * 5 + [(0.65, "challenge", "weak_evidence")] * 5
    _seed_reviewed(s, specs)
    cal = calibration(s)
    assert cal["n_reviewed"] == 20 and cal["sufficient"] is True
    # the 80-90 bucket: 8/10 approved
    bucket = next(p for p in cal["points"] if p["range"].startswith("80"))
    assert bucket["count"] == 10 and abs(bucket["approval_rate"] - 0.8) < 1e-6
    assert cal["headline"] and "%" in cal["headline"]


def test_overconfidence_detected():
    s = _session()
    # states 90% but only ~40% approved → overconfident
    specs = [(0.9, "approve", None)] * 4 + [(0.9, "challenge", "wrong_cause")] * 6
    _seed_reviewed(s, specs)
    cal = calibration(s)
    assert cal["overconfidence_gap"] > 0.1 and cal["overconfident"] is True


# ── challenge autopsies → weak spots (exit criterion #3, part 1) ─────────

def test_weak_spots_rollup():
    s = _session()
    specs = [(0.8, "challenge", "wrong_cause")] * 3 + [(0.8, "challenge", "weak_evidence")] * 1
    _seed_reviewed(s, specs)
    ws = weak_spots(s)
    assert ws["total_challenges"] == 4
    assert ws["spots"][0]["reason"] == "wrong_cause" and ws["spots"][0]["count"] == 3
    assert ws["spots"][0]["guidance"]  # corrective guidance present


# ── weak-spot guidance changes future behavior (exit criterion #3, part 2)

def test_guidance_injected_into_prompt():
    s = _session()
    specs = [(0.9, "challenge", "wrong_cause")] * 6 + [(0.9, "approve", None)] * 1
    _seed_reviewed(s, specs)
    g = guidance_text(s)
    assert "KNOWN WEAK SPOT" in g and "wrong root cause" in g
    # and it reaches the investigator's actual system prompt
    from echolens.investigator.prompts import plan_system
    assert "LEARNED GUIDANCE" in plan_system(g)


def test_deliberately_wrong_challenge_changes_next_investigation():
    """A challenge with a structured reason must measurably alter the NEXT
    investigation's prompt (the trust loop closes)."""
    from echolens.investigator.graph import Investigator
    from echolens.eval.harness import ScriptedLLM
    s = _session()
    # before: no learned guidance
    anomaly = s.scalars(select(AnomalyEvent).where(AnomalyEvent.slug == "demo1")).first()
    inv0 = Investigator(s, anomaly, llm=ScriptedLLM([]))
    assert inv0._guidance == ""
    # a batch of 'wrong_cause' challenges accumulates
    _seed_reviewed(s, [(0.9, "challenge", "wrong_cause")] * 6)
    inv1 = Investigator(s, anomaly, llm=ScriptedLLM([]))
    assert "wrong root cause" in inv1._guidance  # next run is now warned


# ── counter-evidence duty (exit criterion #2) ───────────────────────────

def test_refutation_step_in_every_resolved_trace():
    scenario_clear_cause()  # runs a full resolved investigation over Lumo
    # re-run and inspect the trace directly
    from echolens.eval.harness import fresh_session, _run_investigation
    s = fresh_session()
    from echolens.tools.search_reviews import search_reviews
    from echolens.tools.search_github_issues import search_github_issues
    ref_r = search_reviews(s, query="battery drain", date_from="2026-07-11", rating_max=2)["reviews"][0]["ref"]
    ref_g = search_github_issues(s, "background sync battery wakelock")["issues"][0]["ref"]
    responses = [
        {"thought": "form", "action": "revise_hypotheses",
         "hypotheses": [{"id": "H1", "statement": "v3.2 background sync causes battery drain", "confidence": 0.5, "status": "active"},
                        {"id": "H2", "statement": "Android 15 update causes the drain", "confidence": 0.4, "status": "active"}]},
        {"thought": "read", "action": "call_tool",
         "tool": {"name": "search_reviews", "args": {"query": "battery drain", "date_from": "2026-07-11", "rating_max": 2}, "tests_hypothesis": "H1"}},
        {"evidence": [{"ref": ref_r, "snippet": "battery dies since update", "supports": ["H1"], "contradicts": []}],
         "hypothesis_updates": [{"id": "H1", "new_confidence": 0.65, "based_on_refs": [ref_r], "note": "x"}]},
        {"thought": "corroborate", "action": "call_tool",
         "tool": {"name": "search_github_issues", "args": {"query": "background sync battery wakelock"}, "tests_hypothesis": "H1"}},
        {"evidence": [{"ref": ref_g, "snippet": "wakelock never released when queue empty", "supports": ["H1"], "contradicts": ["H2"]}],
         "hypothesis_updates": [{"id": "H1", "new_confidence": 0.85, "based_on_refs": [ref_g], "note": "y"},
                                {"id": "H2", "new_confidence": 0.2, "new_status": "rejected", "based_on_refs": [ref_g], "note": "z"}]},
        {"summary": "sync drives it", "prose": "Battery drain is caused by v3.2 sync [ev_001][ev_002].",
         "confidence": 0.85, "supported_hypothesis": "H1", "checked": ["play_store", "github"], "what_would_settle_it": ""},
    ]
    inv, finding = _run_investigation(s, "demo1", responses)
    assert inv.status == "resolved"
    kinds = [t.kind for t in s.scalars(select(TraceStep).where(TraceStep.investigation_id == inv.id)).all()]
    assert "REFUTE" in kinds  # refutation attempted before confirming


def test_near_duplicate_evidence_merges():
    from echolens.investigator.graph import Investigator
    ev = [{"id": "ev_001", "source": "play_store", "snippet": "battery drains fast since the last update badly"}]
    dup = Investigator._near_duplicate("battery drains fast since the last update badly", "play_store", ev)
    assert dup == "ev_001"
    # different source is never merged
    assert Investigator._near_duplicate("battery drains fast since the last update badly", "github", ev) is None
    # genuinely different snippet is kept
    assert Investigator._near_duplicate("the print shipping cost is way too high now", "play_store", ev) is None
