"""Cheap, offline validation of the two onboarding inputs (v3.0).

Format checks only — we don't hit the network here (the backfill does, and its
failure surfaces as a stale/errored source). The goal is to reject an obvious
typo before kicking off a backfill, with a message a PM can act on.
"""
from __future__ import annotations

import re

# Android application id: dot-separated segments, each starting with a letter.
_PKG_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*(\.[a-zA-Z][a-zA-Z0-9_]*)+$")
# owner/repo (GitHub slug rules, simplified)
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def validate_play_store_package(pkg: str | None) -> str | None:
    """Return an error message, or None if the package name looks valid."""
    pkg = (pkg or "").strip()
    if not pkg:
        return "Enter your app's Play Store package name (e.g. com.company.app)."
    if " " in pkg:
        return "A package name has no spaces — copy it from the Play Store URL (id=…)."
    if not _PKG_RE.match(pkg):
        return "That doesn't look like an Android package name. Expected something like com.company.app."
    return None


def normalize_github_repo(value: str | None) -> tuple[str | None, str | None]:
    """Accept a full GitHub URL or a bare 'owner/repo' and return
    (normalized_repo, error). Empty input is allowed (GitHub is optional)."""
    value = (value or "").strip()
    if not value:
        return None, None
    # strip a full URL down to owner/repo
    m = re.search(r"github\.com[/:]([^/]+/[^/#?]+)", value)
    repo = (m.group(1) if m else value).removesuffix(".git").strip("/")
    if not _REPO_RE.match(repo):
        return None, "Enter the repo as owner/repo (e.g. signalapp/Signal-Android) or its GitHub URL."
    return repo, None
