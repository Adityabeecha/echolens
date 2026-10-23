"""Instant preview of an onboarding input, before anything is set up.

Typing `com.whatsapp` and seeing "WhatsApp Messenger · 190M ratings" is the
fastest way to know you typed the right thing. That needs one network call, so
unlike validate.py this module does go out — but with a short timeout, and it
never fails the wizard: a store that is slow or down returns `ok: False` with a
reason, and the user can still continue.

The fetches reuse the collectors' own clients and are injectable so tests stay
offline.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as _Timeout

from echolens.onboarding.validate import normalize_github_repo, validate_play_store_package

DEFAULT_TIMEOUT_S = 4.0


def _bounded(fn, timeout: float):
    """Run `fn()` with a wall-clock cap. The scraper has no timeout knob of its
    own, so a hung store would otherwise hang the request with it. The worker
    thread is abandoned (not joined) on timeout; it finishes in the background."""
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(fn).result(timeout=timeout)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def preview_play_store(package: str, fetch_fn=None, timeout: float = DEFAULT_TIMEOUT_S) -> dict:
    err = validate_play_store_package(package)
    if err:
        return {"ok": False, "kind": "invalid", "reason": err}
    package = package.strip()
    if fetch_fn is None:
        from echolens.collectors.play_store import fetch_app_details
        fetch_fn = fetch_app_details
    try:
        info = _bounded(lambda: fetch_fn(package), timeout) or {}
    except _Timeout:
        return {"ok": False, "kind": "timeout",
                "reason": "Google Play is slow to answer — you can still continue."}
    except Exception as err:  # noqa: BLE001 — any store failure degrades to "unverified"
        if type(err).__name__ == "NotFoundError":
            return {"ok": False, "kind": "not_found",
                    "reason": f"No Play Store app with the id {package}. Check the id= part of its URL."}
        return {"ok": False, "kind": "unavailable",
                "reason": "Couldn't reach Google Play to check — you can still continue."}
    return {
        "ok": True,
        "source": "play_store",
        "identifier": package,
        "title": info.get("title") or package,
        "developer": info.get("developer"),
        "ratings": info.get("ratings"),
        "reviews": info.get("reviews"),
        "score": round(float(info["score"]), 2) if info.get("score") is not None else None,
        "installs": info.get("installs"),
    }


def preview_github(value: str, fetch_fn=None, timeout: float = DEFAULT_TIMEOUT_S) -> dict:
    repo, err = normalize_github_repo(value)
    if err or not repo:
        return {"ok": False, "kind": "invalid",
                "reason": err or "Enter the repo as owner/repo."}
    if fetch_fn is None:
        from echolens.collectors.github import fetch_repo_meta
        fetch_fn = lambda r: fetch_repo_meta(r, timeout=timeout)  # noqa: E731
    try:
        info = _bounded(lambda: fetch_fn(repo), timeout + 0.5)
    except _Timeout:
        return {"ok": False, "kind": "timeout", "repo": repo,
                "reason": "GitHub is slow to answer — you can still continue."}
    except Exception:  # noqa: BLE001
        return {"ok": False, "kind": "unavailable", "repo": repo,
                "reason": "Couldn't reach GitHub to check — you can still continue."}
    if info is None:
        return {"ok": False, "kind": "not_found", "repo": repo,
                "reason": f"GitHub has no public repo {repo}. Check the owner and name."}
    return {
        "ok": True,
        "source": "github",
        "identifier": repo,
        "title": info.get("full_name") or repo,
        "description": info.get("description"),
        "open_issues": info.get("open_issues_count"),
        "stars": info.get("stargazers_count"),
    }
