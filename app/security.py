"""CSRF protection for mutating routes.

Authentication and role authorization now live in `app/auth.py` — a logged-in user
with the right role is what a request needs to reach a mutating route at all. This
module is the second, independent control every one of those routes still needs:
proof that the POST came from this application's own rendered form, not from a
third-party page riding the user's cookie (the textbook CSRF attack). The two
controls are deliberately separate — a valid session proves *who*, a valid CSRF
token proves *this form, this origin*, and neither substitutes for the other.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from fastapi import Form, Header, HTTPException, Request

from .config import settings

_COOKIE = "vitalwatch_csrf"
_TTL = 3600


def _signature(payload: str) -> str:
    return hmac.new(
        settings.app_secret.get_secret_value().encode(), payload.encode(), hashlib.sha256
    ).hexdigest()


def _valid_token(token: str) -> bool:
    if not token or len(token) > 256:
        return False
    try:
        timestamp, nonce, signature = token.split(".")
        age = time.time() - int(timestamp)
        return (0 <= age <= _TTL and len(nonce) == 64
                and hmac.compare_digest(signature, _signature(f"{timestamp}.{nonce}")))
    except (ValueError, TypeError):
        return False


def prepare_csrf(request: Request) -> str:
    """A valid token for this request, reusing the cookie's if it is still good.

    Issued on every page render — any logged-in user might submit a form, so unlike
    the old shared-password prototype there is no separate "writes enabled" gate
    here; `app.auth.require_role` is what decides whether a given user's role may
    reach a given mutating route.
    """
    token = request.cookies.get(_COOKIE, "")
    if not _valid_token(token):
        payload = f"{int(time.time())}.{secrets.token_hex(32)}"
        token = f"{payload}.{_signature(payload)}"
    return token


def set_csrf_cookie(response, token: str) -> None:
    if token:
        response.set_cookie(_COOKIE, token, max_age=_TTL, httponly=True,
                            secure=not settings.demo_allow_http, samesite="strict", path="/")


def _verify_transport(request: Request) -> None:
    """The network-level half of the check, shared by the form and header variants."""
    if request.url.scheme != "https" and not settings.demo_allow_http:
        raise HTTPException(403, "HTTPS is required for writes")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Cross-site writes are not permitted")
    origin = request.headers.get("origin")
    expected_origin = f"{request.url.scheme}://{request.url.netloc}"
    if origin and origin != expected_origin:
        raise HTTPException(403, "Request origin does not match this application")


def _verify_token_pair(request: Request, presented: str) -> None:
    """The presented token must be validly signed and identical to the cookie's."""
    cookie = request.cookies.get(_COOKIE, "")
    if not (_valid_token(presented) and secrets.compare_digest(cookie, presented)):
        raise HTTPException(403, "Invalid or expired form token; reload the form and try again")


def verify_csrf(
    request: Request,
    csrf_token: str = Form("", max_length=256),
) -> None:
    """Dependency for every mutating route: raises 403 on a forged or missing token.

    Composes with `app.auth.require_role` rather than replacing it — a route depends
    on both, e.g. `Depends(auth.require_role(...))` and `Depends(security.verify_csrf)`.
    """
    _verify_transport(request)
    _verify_token_pair(request, csrf_token)


def verify_csrf_header(
    request: Request,
    x_csrf_token: str = Header("", max_length=256, alias="X-CSRF-Token"),
) -> None:
    """CSRF check for request-body API routes (fetch/XHR), token carried in a header.

    `verify_csrf` reads the token from a form field, which a JSON POST does not
    have; a browser `fetch` sends it as `X-CSRF-Token` instead (the value is
    published to the app's own pages in a `<meta name="csrf-token">` tag — the
    cookie itself stays HttpOnly). The checks are identical: same cookie, same
    HMAC, same transport rules. A cross-origin page cannot add this header
    without a CORS preflight this application never grants, which is itself
    part of the defence.
    """
    _verify_transport(request)
    _verify_token_pair(request, x_csrf_token)
