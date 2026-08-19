"""Google Sign-In: verify an ID token, map it to an EchoLens user.

The browser runs Google Identity Services, which hands back a signed JWT (an
"ID token"). This module verifies that token properly — signature against
Google's published keys, issuer, audience, and expiry — and returns the claims.

The verification is the whole point. An ID token is attacker-supplied input: a
client could post any JSON it likes to /auth/google. Decoding it without
checking the signature would let anyone log in as anyone by editing the
payload, so every check below is load-bearing.

No new dependency: python-jose (already used for our own tokens) does JWKS
verification, and httpx (already used by the collectors) fetches the keys.
"""
from __future__ import annotations

import threading
import time

import httpx
from jose import jwt
from jose.exceptions import JWTError

from echolens.config import settings
from echolens.logging import get_logger

log = get_logger("auth.google")

# Google's key set. Rotated periodically, so it is cached with a TTL rather
# than fetched once at import (a process that outlives a rotation would then
# reject every valid token) or fetched per request (a Google outage or slow
# response would stall every sign-in, and it is a needless round trip).
_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
_CACHE_TTL_S = 3600
_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}

_lock = threading.Lock()
_jwks: dict | None = None
_fetched_at: float = 0.0


class GoogleAuthError(Exception):
    """The ID token could not be verified. Never leak the reason to the client."""


def _keys(force: bool = False) -> dict:
    """Google's JWKS, cached for an hour."""
    global _jwks, _fetched_at
    with _lock:
        fresh = _jwks is not None and (time.time() - _fetched_at) < _CACHE_TTL_S
        if fresh and not force:
            return _jwks  # type: ignore[return-value]
        try:
            r = httpx.get(_CERTS_URL, timeout=10)
            r.raise_for_status()
            _jwks = r.json()
            _fetched_at = time.time()
            return _jwks
        except Exception as err:
            # Serve a stale key set rather than locking everyone out over a
            # transient network blip; only fail hard if we never had one.
            if _jwks is not None:
                log.warning("google_jwks_refresh_failed", error=str(err))
                return _jwks
            raise GoogleAuthError(f"cannot reach Google's key set: {err}") from err


def verify_id_token(token: str) -> dict:
    """Verify a Google ID token and return its claims.

    Raises GoogleAuthError on anything suspicious.
    """
    if not settings.google_client_id:
        raise GoogleAuthError("Google sign-in is not configured on this server")
    if not token or not isinstance(token, str):
        raise GoogleAuthError("no credential supplied")

    def _decode(jwks: dict) -> dict:
        # jose checks signature, `aud`, `iss` and `exp`. Passing the audience
        # is what stops a token minted for a DIFFERENT Google app — which is
        # still perfectly signed by Google — from authenticating here.
        return jwt.decode(
            token,
            jwks,
            algorithms=["RS256"],
            audience=settings.google_client_id,
            issuer="https://accounts.google.com",
            options={"verify_at_hash": False},
        )

    # Read the header BEFORE any network work. This is unverified data, used
    # only to decide whether a refetch could possibly help — never trusted.
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as err:
        raise GoogleAuthError(f"invalid Google token: {err}") from err
    kid = header.get("kid")
    # Google signs with RS256. Refusing anything else here also closes the
    # `alg: none` and HMAC-confusion classes of attack outright.
    if header.get("alg") != "RS256" or not kid:
        raise GoogleAuthError("invalid Google token: unexpected signing algorithm")

    jwks = _keys()
    known = {k.get("kid") for k in jwks.get("keys", [])}
    if kid not in known:
        # An unrecognised key id is the ONE case a refetch can fix: Google
        # rotates keys, so a rotation must not look like an outage. Every other
        # failure (garbage string, bad signature, wrong audience) refetches
        # nothing, so a flood of junk credentials cannot be turned into a flood
        # of outbound requests to Google.
        jwks = _keys(force=True)

    try:
        claims = _decode(jwks)
    except JWTError as err:
        raise GoogleAuthError(f"invalid Google token: {err}") from err
    except Exception as err:
        # jose raises JWKError (a KeyError subclass, NOT a JWTError) for a
        # malformed key set, so it escaped this handler entirely and surfaced
        # as an unhandled 500 with a stack trace instead of a clean 401.
        # Verification failing for ANY reason is a rejection, never a crash.
        raise GoogleAuthError(f"invalid Google token: {type(err).__name__}") from err

    # `iss` is checked above only for the canonical form; Google also uses the
    # bare hostname, so accept either and reject anything else.
    if claims.get("iss") not in _ISSUERS:
        raise GoogleAuthError("unexpected token issuer")

    email = (claims.get("email") or "").strip().lower()
    if not email:
        raise GoogleAuthError("Google token carries no email")
    # An unverified email is a claim, not a fact: Google will mint a token for
    # an address the user has not proven they own, and trusting it would let
    # someone sign in as the owner by claiming the owner's address.
    if not claims.get("email_verified"):
        raise GoogleAuthError("that Google account's email is not verified")

    return {"email": email, "name": claims.get("name") or "", "sub": claims.get("sub")}


def role_for(email: str) -> str:
    """Admin if allowlisted, otherwise the configured default role."""
    return "admin" if email.lower() in settings.google_admin_list else settings.google_default_role
