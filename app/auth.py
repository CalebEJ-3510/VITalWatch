"""Authentication and role-based access control.

Replaces the old shared-password write guard (`app/security.py::require_demo_writer`)
with real per-user identity: a `users` table, salted PBKDF2 password hashes, and
server-side sessions identified by an opaque token whose SHA-256 — never the token
itself — is what the database stores.

Two layers, and both matter:

1. **Authentication** — `get_current_user` resolves a session cookie to a `User`,
   or to `None`. It never raises: a page that cannot identify its caller shows the
   login screen, it does not 500.
2. **Authorization** — `require_role` is a dependency factory. Each mutating route
   states exactly which roles may call it; every route in `app/main.py` composes
   from here rather than from a single shared password, so the audit trail's
   `actor` field is finally a real identity and not a fixed demo string.

`UserRole` (see `app/models.py`) is the five primary roles the specification names —
volunteer, company, investigator, safety_officer, leadership.

Two more layers sit on top of "which role":

3. **Permissions** — `Permission` and `PERMISSIONS_BY_ROLE` are the
   ROLE → ACTION vocabulary spec section 29 asks for: a named capability
   (`file_adverse_event`, `raise_safety_concern`, `leadership_decision`, ...) that a
   role either holds or does not, checked by `has_permission` and, at the route
   layer, by `require_permission`. The per-route role tuples that previously lived
   inline in `main.py` are what this replaces, one capability name at a time.
4. **Session references for the audit trail** — `session_reference` derives the
   opaque, non-reversible identifier spec section 30 wants on every audit row.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from enum import Enum

from fastapi import Depends, HTTPException, Request

from .config import settings
from .db import Connection
from .models import User, UserRole, parse_role, utcnow

UTC = timezone.utc

#: Public so `main.py` can set/clear the cookie and its own middleware can read it.
SESSION_COOKIE = "vitalwatch_session"

#: PBKDF2 iteration count. 200,000 is comfortably inside OWASP's current guidance for
#: PBKDF2-SHA256 and costs a human login nothing noticeable; it costs an offline
#: attacker on a stolen `users` table a great deal, which is the point of hashing at all.
_PBKDF2_ITERATIONS = 200_000
_HASH_NAME = "sha256"


# --------------------------------------------------------------------- password hashing


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Return `(hash_hex, salt_hex)`. Generates a fresh random salt if none is given.

    The salt is stored beside the hash — that is what a salt is for — and is never
    reused across users, so two accounts sharing a password never share a hash.
    """
    salt_bytes = bytes.fromhex(salt) if salt else secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac(_HASH_NAME, password.encode("utf-8"), salt_bytes, _PBKDF2_ITERATIONS)
    return derived.hex(), salt_bytes.hex()


def verify_password(password: str, stored_hash: str, salt: str) -> bool:
    """Constant-time comparison. Never short-circuits on the first differing byte."""
    candidate, _ = hash_password(password, salt)
    return hmac.compare_digest(candidate, stored_hash)


# ------------------------------------------------------------------------------ sessions


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(conn: Connection, user_id: str) -> str:
    """Start a session for `user_id`. Returns the raw token — put it in the cookie.

    Only `sha256(token)` is written to `sessions`, so a copy of the database (a
    backup, a leaked file) never hands out a usable login on its own.
    """
    token = secrets.token_urlsafe(32)
    now = utcnow()
    conn.execute(
        """INSERT INTO sessions (token_hash, user_id, created_at, expires_at, revoked)
           VALUES (?, ?, ?, ?, 0)""",
        (
            _token_hash(token),
            user_id,
            now.isoformat(),
            (now + timedelta(hours=settings.session_ttl_hours)).isoformat(),
        ),
    )
    conn.commit()
    return token


def revoke_session(conn: Connection, token: str) -> None:
    """Log out: mark the session revoked rather than deleting it.

    A revoked-but-present row is a record that a logout happened; deleting it would
    throw that fact away for no benefit — an expired or revoked row grants nothing.
    """
    conn.execute(
        "UPDATE sessions SET revoked = 1 WHERE token_hash = ?", (_token_hash(token),)
    )
    conn.commit()


def _user_from_row(row) -> User:
    # `parse_role`, not `UserRole(row["role"])`: a `users` row seeded before the
    # five-role alignment still carries a legacy value ("pharmacovigilance", ...),
    # and normalising it here means login keeps working for every existing account
    # until the seed data itself is regenerated with primary values.
    return User(
        id=row["id"], username=row["username"], role=parse_role(row["role"]),
        display_name=row["display_name"], pi_name=row["pi_name"],
        active=bool(row["active"]), created_at=row["created_at"],
    )


def session_reference(token: str | None) -> str | None:
    """The opaque, audit-safe reference to a session — never the token itself.

    Spec section 30 asks every audit row to carry a "session/request reference":
    enough to tie the row back to the session that made the change, not enough to
    replay the session. The first 16 hex digits of the same SHA-256 the `sessions`
    table stores are exactly that — derived from the token, stable across a
    session's life, irreversible in practice, and correlatable with the session
    row's `token_hash` without ever putting the raw token into the trail. `None`
    in, `None` out: an event made with no session says so rather than claiming one.
    """
    if not token:
        return None
    return _token_hash(token)[:16]


def authenticate(conn: Connection, username: str, password: str) -> User | None:
    """Verify credentials. Returns the `User` on success, `None` on any failure.

    Deliberately uniform: an unknown username and a wrong password both return
    `None` rather than distinguishing which — telling an attacker "no such user"
    for one case and "wrong password" for the other is a username-enumeration leak.
    """
    row = conn.execute(
        "SELECT * FROM users WHERE username = ? AND active = 1", (username,)
    ).fetchone()
    if row is None:
        return None
    if not verify_password(password, row["password_hash"], row["salt"]):
        return None
    return _user_from_row(row)


def get_session_user(conn: Connection, token: str | None) -> User | None:
    """Resolve a raw session token to its `User`, or `None` if it names nothing live.

    "Nothing live" covers three distinct states on purpose — missing, revoked, and
    expired — and all three collapse to the same `None` here, because none of them
    should authorise anything and a caller has no need to tell them apart.
    """
    if not token:
        return None
    row = conn.execute(
        """SELECT s.expires_at, s.revoked, u.* FROM sessions s
             JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ?""",
        (_token_hash(token),),
    ).fetchone()
    if row is None or row["revoked"] or not row["active"]:
        return None
    expires = datetime.fromisoformat(row["expires_at"])
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if utcnow() > expires:
        return None
    return _user_from_row(row)


# --------------------------------------------------------------- FastAPI dependencies


class LoginRequired(Exception):
    """Raised by page routes' dependencies; `main.py` converts this to a 303 redirect."""

    def __init__(self, next_path: str):
        self.next_path = next_path


def require_role(*roles: UserRole):
    """Dependency factory: 403s unless the current user's role is one of `roles`.

    Every mutating route names its allowed roles explicitly at the call site —
    `Depends(require_role(UserRole.INVESTIGATOR, UserRole.SAFETY_OFFICER))` — so the
    permitted set is visible in the route signature, not buried in a shared password
    check. New routes should prefer `require_permission` (the capability, not the
    role, is the thing being granted); this factory remains for routes whose gate is
    genuinely "one of these identities" rather than "holds this capability".
    """

    def dependency(user: User = Depends(_current_user_or_401)) -> User:
        if user.role not in roles:
            raise HTTPException(
                403,
                f"Role {user.role.value!r} is not permitted to perform this action "
                f"(requires one of: {', '.join(r.value for r in roles)}).",
            )
        return user

    return dependency


def _current_user_or_401(request: Request) -> User:
    """Read the user FastAPI's own auth middleware already attached to the request.

    `main.py`'s global auth check runs first and stores the resolved `User` on
    `request.state.user`; every dependency in this module reads it from there
    instead of re-querying the database, so one request resolves its session once.
    """
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(401, "Authentication required.")
    return user


# -------------------------------------------------------------------------- permissions
#
# The ROLE -> ACTION vocabulary spec section 29 calls for. Before this, "what may a
# user do" was answered by inline role tuples scattered through `main.py`
# (`AE_WRITE_ROLES`, `ESCALATION_RAISE_ROLES`, ...), and the five-role alignment
# makes that scatter actively dangerous: two former roles sharing a primary role
# must now be told apart by *capability*, not by identity. A capability is a named,
# individually checkable thing; a role is who you are. The matrix below is the
# single place the two are joined.


class Permission(str, Enum):
    """A named capability, checked by `has_permission` / `require_permission`.

    One member per distinct thing a route grants. Keeping the vocabulary short and
    route-shaped (not module-shaped) is deliberate: a permission nobody holds or
    nobody checks is a matrix cell pretending to be a policy.
    """

    #: File an adverse event through the intake route (former `AE_WRITE_ROLES`).
    FILE_ADVERSE_EVENT = "file_adverse_event"
    #: Raise a protocol-deviation escalation (spec section 23: the Investigator's path).
    RAISE_PROTOCOL_DEVIATION = "raise_protocol_deviation"
    #: Raise a safety-concern escalation (spec section 23: the Safety Officer's path).
    RAISE_SAFETY_CONCERN = "raise_safety_concern"
    #: Review the Company's response — resolve or escalate to Leadership.
    REVIEW_ESCALATION_RESPONSE = "review_escalation_response"
    #: Submit the Company's structured response to an escalation (spec section 15).
    SUBMIT_COMPANY_RESPONSE = "submit_company_response"
    #: Record the final governance decision (spec sections 17, 21, 22).
    LEADERSHIP_DECISION = "leadership_decision"
    #: Open the escalation inbox and detail screens.
    VIEW_ESCALATIONS = "view_escalations"
    #: Read the audit trail page and its verification.
    VIEW_AUDIT_TRAIL = "view_audit_trail"


#: The whole of the role-based policy, in one readable table. Every capability a role
#: holds is listed here — nowhere else — so the question "can a Company account do X"
#: has exactly one answer, and that answer is visible rather than inferred from which
#: route happened to mention the role.
#:
#: Deliberate absences, and why:
#   * `VOLUNTEER` owns registration, consent, and adverse-event self-reporting only.
#   * `LEADERSHIP` cannot file AEs, raise escalations or review responses: the final
#     decision-maker decides, and the decision carries the mandatory reason — but the
#     clinical judgement itself belongs to the Investigator and the Safety Officer.
#   * `COMPANY` responds and sees the escalations its responses are judged on; it does
#     not file AEs or decide governance, and there is no permission here that lets it.
PERMISSIONS_BY_ROLE: dict[UserRole, frozenset[Permission]] = {
    UserRole.VOLUNTEER: frozenset(),
    UserRole.COMPANY: frozenset({
        Permission.SUBMIT_COMPANY_RESPONSE,
        Permission.VIEW_ESCALATIONS,
    }),
    UserRole.INVESTIGATOR: frozenset({
        Permission.FILE_ADVERSE_EVENT,
        Permission.RAISE_PROTOCOL_DEVIATION,
        Permission.REVIEW_ESCALATION_RESPONSE,
        Permission.VIEW_ESCALATIONS,
        Permission.VIEW_AUDIT_TRAIL,
    }),
    UserRole.SAFETY_OFFICER: frozenset({
        Permission.FILE_ADVERSE_EVENT,
        Permission.RAISE_SAFETY_CONCERN,
        Permission.REVIEW_ESCALATION_RESPONSE,
        Permission.VIEW_ESCALATIONS,
        Permission.VIEW_AUDIT_TRAIL,
    }),
    UserRole.LEADERSHIP: frozenset({
        Permission.LEADERSHIP_DECISION,
        Permission.VIEW_ESCALATIONS,
        Permission.VIEW_AUDIT_TRAIL,
    }),
}


def permissions_for(role: UserRole) -> frozenset[Permission]:
    """The capabilities `role` holds. Unknown roles hold nothing — fail closed."""
    return PERMISSIONS_BY_ROLE.get(role, frozenset())


def has_permission(user: User | None, permission: Permission) -> bool:
    """True when `user` is live and holds `permission`. `None` holds nothing."""
    return (
        user is not None
        and user.active
        and permission in permissions_for(user.role)
    )


def require_permission(*permissions: Permission):
    """Dependency factory: 403s unless the current user holds ALL of `permissions`.

    The replacement for the inline role tuples on mutating routes:
    `Depends(auth.require_permission(auth.Permission.FILE_ADVERSE_EVENT))` says what
    is being granted in the route signature, and changing who may do it is a one-line
    edit in `PERMISSIONS_BY_ROLE` rather than a hunt through every route that named
    the role.
    """

    def dependency(user: User = Depends(_current_user_or_401)) -> User:
        missing = [p for p in permissions if p not in permissions_for(user.role)]
        if missing:
            raise HTTPException(
                403,
                f"Role {user.role.value!r} does not hold: "
                f"{', '.join(p.value for p in missing)}.",
            )
        return user

    return dependency


def require_any_permission(*permissions: Permission):
    """Dependency factory: 403s unless the current user holds at least one.

    For routes where several roles may act and each one does it under a different
    capability — the escalation raise route is exactly that: Investigator under
    `RAISE_PROTOCOL_DEVIATION`, Safety Officer under `RAISE_SAFETY_CONCERN`.
    """

    def dependency(user: User = Depends(_current_user_or_401)) -> User:
        if not any(p in permissions_for(user.role) for p in permissions):
            raise HTTPException(
                403,
                f"Role {user.role.value!r} holds none of: "
                f"{', '.join(p.value for p in permissions)}.",
            )
        return user

    return dependency
