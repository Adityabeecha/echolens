"""Remove everything a product owns, in foreign-key order.

Shared by DELETE /products/{id} and the demo reseed, so the two can never
disagree about what "a product's data" is. The Product row itself and the
users pointing at it are the caller's business: a delete removes them, a
reseed keeps them so the demo keeps its id (links, guest scoping).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from echolens.db.models import (
    AnomalyEvent, CaseMerge, CollectorState, Comment, EvidenceRow, FeedbackEntry, Finding,
    FindingDecision, FixWatch, HypothesisRow, Investigation, Issue, KnowledgeEdge,
    LLMCall, Mention, Post, Product, QueuedInvestigation, Recommendation, Release,
    Review, ReviewFeedback, ReviewRequest, SavedView, SentAlert, ShareLink,
    ThemeOverride, TraceStep, TriageDecision, HumanRule, PlanExport,
)


def purge_product_data(session: Session, product: Product) -> None:
    product_id, name = product.id, product.name
    inv_ids = [i.id for i in session.scalars(select(Investigation).where(
        Investigation.product_id == product_id)).all()]
    find_ids = [f.id for f in session.scalars(select(Finding).where(
        Finding.product_id == product_id)).all()]
    anom_ids = [a.id for a in session.scalars(select(AnomalyEvent).where(
        AnomalyEvent.product_id == product_id)).all()]

    def _purge(model, col, ids):
        if ids:
            for row in session.scalars(select(model).where(col.in_(ids))).all():
                session.delete(row)

    # Mentions hang off comments, so they go first — deleting the comment
    # out from under them is the same FK violation one level down.
    comment_ids = [c.id for c in session.scalars(select(Comment).where(
        Comment.product_id == product_id)).all()]
    _purge(Mention, Mention.comment_id, comment_ids)

    _purge(HumanRule, HumanRule.product_id, [product_id])
    _purge(PlanExport, PlanExport.product_id, [product_id])
    session.flush()
    _purge(ReviewFeedback, ReviewFeedback.finding_id, find_ids)
    # v15: decisions and share links hang off findings. Deleting a product
    # must also kill its public links, or a token would outlive its data.
    _purge(FindingDecision, FindingDecision.finding_id, find_ids)
    _purge(ShareLink, ShareLink.finding_id, find_ids)
    _purge(Recommendation, Recommendation.finding_id, find_ids)
    _purge(TraceStep, TraceStep.investigation_id, inv_ids)
    _purge(HypothesisRow, HypothesisRow.investigation_id, inv_ids)
    _purge(EvidenceRow, EvidenceRow.investigation_id, inv_ids)
    _purge(LLMCall, LLMCall.investigation_id, inv_ids)
    # Spend with no case (chat, triage, themes, graph) is tagged by product.
    _purge(LLMCall, LLMCall.product_id, [product_id])
    _purge(TriageDecision, TriageDecision.anomaly_id, anom_ids)
    # Anything that references an investigation must be gone before the
    # investigations themselves, hence two ordered passes rather than one
    # loop over every product-scoped model.
    _purge(Comment, Comment.investigation_id, inv_ids)
    _purge(ReviewRequest, ReviewRequest.investigation_id, inv_ids)
    _purge(QueuedInvestigation, QueuedInvestigation.investigation_id, inv_ids)
    # Merge links point at investigations from both ends.
    _purge(CaseMerge, CaseMerge.source_id, inv_ids)
    _purge(CaseMerge, CaseMerge.target_id, inv_ids)
    session.flush()
    for model in (FixWatch, Finding, Investigation, AnomalyEvent, CollectorState,
                  QueuedInvestigation, KnowledgeEdge, Comment, Mention, ReviewRequest, SavedView,
                  SentAlert, ThemeOverride):
        for row in session.scalars(select(model).where(model.product_id == product_id)).all():
            session.delete(row)
    # Older collector rows were created before product_id was populated.
    # They are still owned by their product name and must not survive a
    # delete only to be inherited by a later product with the same name.
    for row in session.scalars(select(CollectorState).where(
            CollectorState.product == name, CollectorState.product_id.is_(None))).all():
        session.delete(row)
    # Corpus rows are keyed by product NAME, not id. FeedbackEntry was
    # missing: every v2 source (Hacker News, Stack Overflow, GitHub
    # Discussions, PRs/commits) lands there, so deleting a product left its
    # entire non-store corpus behind, and a product recreated with the same
    # name silently inherited it.
    for model in (Review, Issue, Post, Release, FeedbackEntry):
        for row in session.scalars(select(model).where(model.product == name)).all():
            session.delete(row)
    session.flush()
