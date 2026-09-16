"""Hash-chained, append-only audit trail.

Each row stores the hash of the row before it, so the log is a chain:

    hash_n = sha256(canonical_json(payload_n) + prev_hash_n)

Change any historical row — a value, a timestamp, an actor — and its hash no longer
matches what the next row committed to. The chain breaks at exactly the tampered row,
and `verify` reports its sequence number. Deleting a row instead leaves a gap in `seq`,
which is itself the finding.

Canonical JSON (sorted keys, no incidental whitespace) matters: two dicts that mean the
same thing must hash the same, or verification fails on formatting rather than tampering.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from typing import Any
from weakref import WeakKeyDictionary

from .db import (
    Connection,
    Row,
    begin_audit_append,
    is_postgres,
    rollback_quietly,
)  # driver-neutral
from .models import GENESIS_HASH, AuditAction, AuditEvent, utcnow

#: A failed append is retried only when this module owns the whole append (`commit=True`)
#: and only when the failure is lock contention rather than a real error. Bounded: five
#: attempts at most, so a wedged database raises instead of hanging the request.
_APPEND_ATTEMPTS = 5
_LOCK_RETRY_SLEEP_S = 0.05

#: The two spec-section-30 columns this module appends to, and only appends to, when
#: the table has them. See `record` for the migration policy around their absence.
_AUDIT_EXTRA_COLUMNS = ("role", "session_ref")


def canonical_json(payload: dict[str, Any]) -> str:
    """Deterministic serialisation. Sorted keys, tight separators, no ASCII escaping."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


def compute_hash(payload: dict[str, Any], prev_hash: str) -> str:
    return hashlib.sha256((canonical_json(payload) + prev_hash).encode("utf-8")).hexdigest()


def _optional(row: Row | dict[str, Any], key: str) -> Any:
    """A row value that is *absent* (the column does not exist yet) or NULL, and only
    that, reads as `None` — the difference between "the schema predates this column"
    and "no value was recorded" is exactly what chain verification must not conflate.
    """
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


def _payload(row: Row | dict[str, Any]) -> dict[str, Any]:
    """The hashed fields. `hash` and `prev_hash` are excluded — one is the output, the
    other is mixed in separately.

    `role` and `session_ref` join the payload only when they carry a value (see
    `AuditEvent`'s docstring for the policy). A row with NULL in both therefore hashes
    the pre-migration field set byte-for-byte, which is what keeps one chain verifiable
    across the `ALTER TABLE` that adds the columns: historical rows still recompute to
    the hashes their successors committed to.
    """
    payload = {
        "seq": row["seq"],
        "actor": row["actor"],
        "action": row["action"],
        "resource_type": row["resource_type"],
        "resource_id": row["resource_id"],
        "before_json": row["before_json"],
        "after_json": row["after_json"],
        "timestamp_utc": row["timestamp_utc"],
        "reason": row["reason"],
    }
    role = _optional(row, "role")
    session_ref = _optional(row, "session_ref")
    if role is not None:
        payload["role"] = role
    if session_ref is not None:
        payload["session_ref"] = session_ref
    return payload


# ------------------------------------------------------------------ schema detection
#
# The `role`/`session_ref` columns are an integration point owned by `app/db.py`'s DDL
# (see the migration notes in `refactor/security/`). This module has to work against
# both the pre-migration table and the post-migration one, on both engines, so it
# detects what the table actually has rather than assuming either way.


_audit_column_cache: "WeakKeyDictionary[Any, bool]" = WeakKeyDictionary()


def _has_audit_extra_columns(conn: Connection) -> bool:
    """Whether `audit_events` already carries the `role` and `session_ref` columns.

    Cached per connection (a weak key, so a closed connection cannot pin a stale
    answer, and no connection can inherit another's — the cache is keyed by the
    object, not its address). The consequence of the cache's lifetime is part of the
    migration procedure: apply the DDL, then restart, so no long-lived connection
    keeps answering "no" to a table it no longer describes.
    """
    try:
        return _audit_column_cache[conn]
    except (KeyError, TypeError):
        pass

    if is_postgres():
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'audit_events'"
        ).fetchall()
        columns = {r["column_name"] for r in rows}
    else:
        rows = conn.execute("PRAGMA table_info(audit_events)").fetchall()
        columns = {r[1] for r in rows}

    result = all(name in columns for name in _AUDIT_EXTRA_COLUMNS)
    try:
        _audit_column_cache[conn] = result
    except TypeError:  # pragma: no cover — a connection type without weakref support
        pass  # is served a fresh lookup every time; the answer is still correct
    return result


def head(conn: Connection) -> tuple[int, str]:
    """Sequence number and hash of the last row. `(0, GENESIS_HASH)` on an empty chain."""
    row = conn.execute("SELECT seq, hash FROM audit_events ORDER BY seq DESC LIMIT 1").fetchone()
    return (row["seq"], row["hash"]) if row else (0, GENESIS_HASH)


def record(
    conn: Connection,
    *,
    actor: str,
    action: AuditAction | str,
    resource_type: str,
    resource_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
    timestamp: str | None = None,
    role: str | None = None,
    session_ref: str | None = None,
    commit: bool = True,
) -> AuditEvent:
    """Append one event. The only way rows enter this table.

    `timestamp` exists so the seeder can lay down a plausible history; application code
    never passes it, and the server clock is used instead — ALCOA+ 'contemporaneous'.

    `role` is the actor's role at the moment of the action — pass the session user's
    `user.role.value`, a primary `UserRole` value; the audit row says what was true
    then, even if the account's role changes later. `session_ref` is the opaque
    reference from `auth.session_reference` — never the raw session token.

    **Schema policy for those two fields.** The columns are added to `audit_events` by
    a DDL owned elsewhere (`app/db.py`); until it has been applied this function
    degrades to the pre-migration behaviour — the values are dropped from *both* the
    INSERT and the hashed payload — because a hash must be recomputable from the stored
    row, and a row cannot verify against a value it never kept. Once the columns exist,
    values are stored and, when non-NULL, hashed. The returned event reports what was
    actually persisted, not what was asked for.

    Three properties this has to have, all of them load-bearing:

    1. **The returned event is the stored event.** The row's `id` is generated once and
       used for both the INSERT and the returned object. Generating a second UUID for the
       return value — as this did — hands the caller an identifier that resolves to
       nothing, which is worse than useless in a trail that is supposed to be traceable.
    2. **The sequence is atomic across writers.** The head read and the insert happen
       under the write lock `begin_audit_append` takes, retained until commit. Two
       concurrent appends therefore get `seq` 1 and 2, never 1 and 1.
    3. **A failed append leaves nothing behind.** The `AuditEvent` is built (and the
       action validated) before anything is written, and any failure rolls the
       transaction back — including a caller's open transaction. A clinical change that
       could not be audited must not be committable, so aborting the transaction is the
       only safe outcome; the caller sees the exception, not a commit without its trail.
    """
    action_value = action.value if isinstance(action, AuditAction) else str(action)
    # Validated up front, so an unknown action cannot leave a committed row from a call
    # that raised, nor a half-written transaction behind it.
    try:
        AuditAction(action_value)
    except ValueError:
        known = ", ".join(a.value for a in AuditAction)
        raise ValueError(f"{action_value!r} is not a known audit action ({known})") from None
    # ALCOA+ 'attributable': a row with no actor is not an audit row, and refusing it
    # here — before the lock, before the head read — is refusing it where it is cheapest.
    if actor is None or not str(actor).strip():
        # Callers may already have made the clinical write in this transaction. An
        # unauditable write must never survive even when validation fails before a
        # chain head is read, so close the caller's transaction before raising.
        rollback_quietly(conn)
        raise ValueError("An audit event must name its actor; a row with none is not attributable.")
    if role is not None:
        role = str(role)
    if session_ref is not None:
        session_ref = str(session_ref)

    last_error: Exception | None = None
    for attempt in range(1, _APPEND_ATTEMPTS + 1):
        try:
            # Taken before the head read, and held to the commit: see begin_audit_append.
            begin_audit_append(conn)
            prev_seq, prev_hash = head(conn)
            row = {
                "seq": prev_seq + 1,
                "actor": actor,
                "action": action_value,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "before_json": canonical_json(before) if before is not None else None,
                "after_json": canonical_json(after) if after is not None else None,
                "timestamp_utc": timestamp or utcnow().isoformat(),
                "reason": reason,
            }
            # The two extra columns are carried — and enter the hashed payload — only
            # when the table has them. `_payload` picks them up from `row` by name, so
            # this one branch is the whole write-side of the migration policy.
            if _has_audit_extra_columns(conn):
                row["role"] = role
                row["session_ref"] = session_ref
                stored_role, stored_ref = role, session_ref
            else:
                stored_role = stored_ref = None
            row_hash = compute_hash(_payload(row), prev_hash)
            event_id = str(uuid.uuid4())
            # Built before the INSERT: every way this can fail — an unknown action, a
            # missing actor — fails while the database is still untouched.
            event = AuditEvent(
                id=event_id, seq=row["seq"], actor=actor, role=stored_role,
                action=AuditAction(row["action"]), resource_type=resource_type,
                resource_id=resource_id, before=before, after=after,
                timestamp_utc=row["timestamp_utc"], reason=reason,
                session_ref=stored_ref,
                prev_hash=prev_hash, hash=row_hash,
            )
            if "role" in row:
                conn.execute(
                    """INSERT INTO audit_events
                       (id, seq, actor, role, action, resource_type, resource_id,
                        before_json, after_json, timestamp_utc, reason, session_ref,
                        prev_hash, hash)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        event_id, row["seq"], row["actor"], row["role"], row["action"],
                        row["resource_type"], row["resource_id"], row["before_json"],
                        row["after_json"], row["timestamp_utc"], row["reason"],
                        row["session_ref"], prev_hash, row_hash,
                    ),
                )
            else:
                conn.execute(
                    """INSERT INTO audit_events
                       (id, seq, actor, action, resource_type, resource_id,
                        before_json, after_json, timestamp_utc, reason, prev_hash, hash)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        event_id, row["seq"], row["actor"], row["action"],
                        row["resource_type"], row["resource_id"], row["before_json"],
                        row["after_json"], row["timestamp_utc"], row["reason"],
                        prev_hash, row_hash,
                    ),
                )
            if commit:
                conn.commit()
            return event
        except sqlite3.OperationalError as exc:
            last_error = exc
            rollback_quietly(conn)
            # Retried only when this call owns the append: on `commit=False` the
            # transaction being retried also holds the caller's clinical write, which
            # the rollback above has already discarded.
            if (not commit or attempt == _APPEND_ATTEMPTS
                    or not _is_lock_contention(exc)):
                raise
            time.sleep(_LOCK_RETRY_SLEEP_S * attempt)
        except Exception:
            rollback_quietly(conn)
            raise

    raise last_error  # pragma: no cover — the loop either returns or raises above


def _is_lock_contention(exc: Exception) -> bool:
    """True for SQLite's two lock errors, and only those.

    `busy` is the upgrade path (another writer holds a shared lock), `locked` the plain
    one. Everything else — a missing table, a constraint violation — is a real error and
    must not be retried.
    """
    message = str(exc).lower()
    return "database is locked" in message or "database is busy" in message


def verify(conn: Connection) -> dict[str, Any]:
    """Walk the chain from genesis.

    Returns `{"ok": True, "count": n}`, or `ok: False` with the sequence number of the
    first row that fails and why. Three distinct failures are reported separately
    because they mean different things: a broken link means a row was edited, a gap
    means a row was deleted, a bad hash means the row's own contents were changed.
    """
    prev_hash = GENESIS_HASH
    expected_seq = 1
    count = 0

    for row in conn.execute("SELECT * FROM audit_events ORDER BY seq ASC"):
        if row["seq"] != expected_seq:
            return {
                "ok": False, "seq": row["seq"], "count": count,
                "error": f"sequence gap: expected {expected_seq}, found {row['seq']} — "
                         f"{row['seq'] - expected_seq} row(s) deleted",
            }
        if row["prev_hash"] != prev_hash:
            return {
                "ok": False, "seq": row["seq"], "count": count,
                "error": "broken link: prev_hash does not match the preceding row's hash",
            }
        if compute_hash(_payload(row), prev_hash) != row["hash"]:
            return {
                "ok": False, "seq": row["seq"], "count": count,
                "error": "content altered: this row's contents no longer hash to its stored hash",
            }
        prev_hash = row["hash"]
        expected_seq += 1
        count += 1

    return {"ok": True, "count": count, "head": prev_hash}


if __name__ == "__main__":
    import sys

    from .db import connect

    # `--verify` is accepted because that is how the command is written down in
    # ROADMAP.md and the demo script. Verifying is the only thing this module does from
    # the command line, so the flag is optional rather than required.
    if set(sys.argv[1:]) - {"--verify"}:
        print("usage: python -m app.audit [--verify]")
        raise SystemExit(2)

    conn = connect()
    result = verify(conn)
    if result["ok"]:
        print(f"OK — {result['count']} events, chain intact")
        print(f"head {result['head']}")
    else:
        print(f"TAMPERED at seq {result['seq']} — {result['error']}")
        print(f"{result['count']} event(s) verified before the break")
        raise SystemExit(1)
