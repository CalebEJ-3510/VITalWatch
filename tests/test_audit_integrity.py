"""Regression tests for the audit trail: the row's id, the append sequence, tamper response.

Three failures are pinned down here, all fixed in `app/audit.py` and `app/db.py`:

* `record` returned a freshly generated UUID that was never the one it stored, so the
  identifier handed to the caller could not be used to find the row it named.
* The head read and the insert were not one atomic step. Two writers appending at the
  same moment — the ordinary case for a web request — could both read the same head and
  both claim the same `seq`. On an *empty* chain that is the first race two requests can
  ever hit, so it is tested explicitly rather than assumed.
* A failure part-way through an append could leave the clinical write it was recording
  committed without its audit row, and an unknown action could raise after the audit row
  had already been committed.

No test here may reach a database outside `tmp_path`, so the environment is isolated
before `app` is imported: `app.config` builds its `Settings` object once, at import time,
and a `.env` naming a live database would otherwise be inherited by every test in this
file.
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
import threading
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# --------------------------------------------------------------- isolation, before app
# `isolation-probe.db` is never opened: it only has to exist as a name so that a Settings
# object built before the fixtures run points somewhere harmless. The directory is removed
# on the way out, because a test suite that leaves debris behind is its own small mess.
_TEST_DIR = Path(tempfile.mkdtemp(prefix="vitalwatch-audit-tests-"))
atexit.register(shutil.rmtree, _TEST_DIR, ignore_errors=True)
os.environ["DATABASE_URL"] = ""  # falsy: app.db then takes the SQLite branch
os.environ["DB_PATH"] = str(_TEST_DIR / "isolation-probe.db")

from app import audit, db  # noqa: E402
from app.config import settings  # noqa: E402
from app.models import GENESIS_HASH, AuditAction  # noqa: E402

# Read back rather than trusted: an empty env var still loses to a `.env` in some
# pydantic-settings arrangements, and a test that silently talked to Postgres would be
# worse than a test that fails.
settings.database_url = None
settings.db_path = _TEST_DIR / "isolation-probe.db"

if db.is_postgres():  # pragma: no cover — only reachable on a misconfigured machine
    raise RuntimeError("audit integrity tests refuse to run against Postgres")


@pytest.fixture()
def conn(tmp_path):
    """A schema-initialised SQLite database of this test's own."""
    c = db.connect(tmp_path / "audit.db")
    db.init_schema(c)
    try:
        yield c
    finally:
        c.close()


def _append(conn, **overrides) -> object:
    kwargs = {
        "actor": "demo.operator",
        "action": AuditAction.CREATE,
        "resource_type": "trial",
        "resource_id": "STU-001",
        "before": None,
        "after": {"id": "STU-001", "status": "active"},
        "reason": "test",
    }
    kwargs.update(overrides)
    return audit.record(conn, **kwargs)


def _study(conn, trial_id: str = "STU-900", site_id: str = "SITE-900") -> None:
    conn.execute(
        """INSERT INTO trials
           (id, title, protocol_no, phase, status, therapeutic_area,
            target_enrolment, pi_name, start_date)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (trial_id, "Sandbox trial", "PROTO-900", "II", "active", "Ayurveda",
         100, "Dr. Test", "2026-01-01"),
    )
    conn.execute(
        """INSERT INTO sites (id, name, city, state, status, pi_name, capacity)
           VALUES (?,?,?,?,?,?,?)""",
        (site_id, "Sandbox site", "Pune", "Maharashtra", "active", "Dr. Test", 20),
    )


def _clinical_write(conn, trial_id: str = "STU-900", site_id: str = "SITE-900") -> None:
    """A stand-in for the clinical row a route writes before it calls the audit trail."""
    conn.execute(
        """INSERT INTO queries
           (id, trial_id, site_id, field, question, raised_date, raised_by, status)
           VALUES (?,?,?,?,?,?,?,?)""",
        (str(uuid.uuid4()), trial_id, site_id, "enrolment_date", "Confirm the date",
         "2026-02-01", "monitor", "open"),
    )


def _rows(conn) -> list:
    return conn.execute("SELECT * FROM audit_events ORDER BY seq ASC").fetchall()


# ------------------------------------------------------------- the returned event's id


def test_returned_event_id_is_the_stored_row_id(conn):
    """The id a caller is given must be the id in the table — otherwise it names nothing."""
    event = _append(conn)
    stored = conn.execute(
        "SELECT id, seq, hash, prev_hash FROM audit_events WHERE seq = ?", (event.seq,)
    ).fetchone()

    assert stored is not None
    assert event.id == stored["id"]
    assert event.hash == stored["hash"]
    assert event.prev_hash == stored["prev_hash"]
    # And the returned object is genuinely retrievable by the id it reports.
    fetched = conn.execute(
        "SELECT seq FROM audit_events WHERE id = ?", (event.id,)
    ).fetchone()
    assert fetched["seq"] == event.seq


def test_each_appended_event_has_its_own_id(conn):
    """A second call must not reuse the first call's id, nor invent one for the return."""
    first, second = _append(conn), _append(conn, resource_id="STU-002")
    stored_ids = {row["id"] for row in _rows(conn)}

    assert first.id != second.id
    assert {first.id, second.id} == stored_ids


# ---------------------------------------------------------- the chain, from an empty table


def test_empty_chain_starts_at_genesis(conn):
    """The initial empty chain is a state, not a special case to be discovered later."""
    assert audit.head(conn) == (0, GENESIS_HASH)
    assert audit.verify(conn) == {"ok": True, "count": 0, "head": GENESIS_HASH}

    first = _append(conn)
    assert first.seq == 1
    assert first.prev_hash == GENESIS_HASH


def test_appended_rows_link_and_verify(conn):
    events = [_append(conn, resource_id=f"STU-{n:03d}") for n in range(1, 4)]

    assert [e.seq for e in events] == [1, 2, 3]
    assert events[1].prev_hash == events[0].hash
    assert events[2].prev_hash == events[1].hash

    result = audit.verify(conn)
    assert result["ok"] is True
    assert result["count"] == 3
    assert result["head"] == events[-1].hash


def test_unknown_action_is_refused_without_writing_anything(conn):
    """An unrecognised action must fail before the row exists, not after it is committed."""
    with pytest.raises(ValueError):
        _append(conn, action="not-a-real-action")

    assert audit.verify(conn)["count"] == 0


# -------------------------------------------------------------------- tamper detection


@pytest.mark.parametrize(
    "operation, sql",
    [
        ("UPDATE", "UPDATE audit_events SET actor='mallory' WHERE seq=1"),
        ("DELETE", "DELETE FROM audit_events WHERE seq=1"),
    ],
)
def test_storage_layer_refuses_update_and_delete(conn, operation, sql):
    _append(conn)
    with pytest.raises(Exception) as caught:
        conn.execute(sql)
        conn.commit()
    conn.rollback()

    assert "append-only" in str(caught.value), operation
    assert audit.verify(conn)["ok"] is True


def test_verify_reports_an_altered_row(conn):
    """Get past the trigger and the chain still catches the edit, naming the sequence."""
    for n in range(1, 5):
        _append(conn, resource_id=f"STU-{n:03d}")

    db.drop_audit_guard(conn)
    conn.execute("UPDATE audit_events SET after_json='{}' WHERE seq=3")
    conn.commit()

    result = audit.verify(conn)
    assert result["ok"] is False
    assert result["seq"] == 3
    assert "content altered" in result["error"]


def test_verify_reports_a_deleted_row_as_a_gap(conn):
    """A missing row leaves a gap in `seq`, which is itself the finding."""
    for n in range(1, 4):
        _append(conn, resource_id=f"STU-{n:03d}")

    conn.execute("DROP TRIGGER audit_events_no_delete")
    conn.execute("DELETE FROM audit_events WHERE seq=2")
    conn.commit()

    result = audit.verify(conn)
    assert result["ok"] is False
    assert result["seq"] == 3
    assert "sequence gap" in result["error"]


# ------------------------------------------------------- a failed append writes nothing


def test_failed_append_leaves_no_partial_clinical_write(conn):
    """The main.py / investigation.py shape: clinical row first, audit row in the same
    transaction. If the audit write cannot be made, the clinical write must not survive —
    an unaudited change is worse than no change at all.
    """
    _study(conn)
    _clinical_write(conn)
    conn.execute("SELECT COUNT(*) FROM queries").fetchone()

    with pytest.raises(Exception):
        # `actor=None` violates NOT NULL: a failure after the chain has been read.
        _append(conn, action=AuditAction.CREATE, actor=None)

    assert not db.in_transaction(conn), "the failed append must leave no transaction open"
    assert conn.execute("SELECT COUNT(*) FROM queries").fetchone()[0] == 0
    assert audit.verify(conn)["count"] == 0


def test_unknown_action_with_commit_true_commits_nothing(conn):
    """The action is validated before the insert, so `commit=True` cannot half-apply."""
    with pytest.raises(ValueError):
        _append(conn, action="bogus", commit=True)

    assert audit.verify(conn)["count"] == 0


def test_commit_false_defers_to_the_caller(conn, tmp_path):
    """`commit=False` is the pattern every route uses; the row and its audit row land
    together, and neither is visible to anyone else until the caller commits."""
    _study(conn)
    _clinical_write(conn)
    event = _append(conn, action=AuditAction.CREATE, resource_type="query", commit=False)

    assert db.in_transaction(conn), "the append must have joined the caller's transaction"
    other = db.connect(tmp_path / "audit.db")
    try:
        assert other.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 0
        assert other.execute("SELECT COUNT(*) FROM queries").fetchone()[0] == 0
        conn.commit()
        assert other.execute("SELECT COUNT(*) FROM audit_events").fetchone()[0] == 1
    finally:
        other.close()

    stored = conn.execute("SELECT id FROM audit_events WHERE seq = ?", (event.seq,)).fetchone()
    assert stored["id"] == event.id


# --------------------------------------------------------------------- lock ordering


class _RecordingConnection:
    """A SQLite connection that remembers, in order, the SQL it was asked to run."""

    def __init__(self, real):
        self._real = real
        self.sql: list[str] = []

    def execute(self, sql, params=()):
        self.sql.append(" ".join(sql.split()))
        return self._real.execute(sql, params)

    def commit(self):
        self.sql.append("COMMIT")
        self._real.commit()

    def rollback(self):
        self.sql.append("ROLLBACK")
        self._real.rollback()

    @property
    def in_transaction(self):
        return self._real.in_transaction


def test_write_lock_is_taken_before_the_head_is_read(conn):
    """The ordering *is* the fix: a head read outside the lock is a race."""
    recording = _RecordingConnection(conn)
    _append(recording)

    assert recording.sql[0] == "BEGIN IMMEDIATE"
    lock_at = 0
    head_at = next(i for i, s in enumerate(recording.sql)
                   if s.startswith("SELECT seq, hash FROM audit_events"))
    insert_at = next(i for i, s in enumerate(recording.sql)
                     if s.startswith("INSERT INTO audit_events"))
    commit_at = recording.sql.index("COMMIT")

    assert lock_at < head_at < insert_at < commit_at


def test_postgres_append_takes_an_advisory_lock_before_the_head_is_read():
    """The same ordering on Postgres, where the lock is what protects an empty chain:
    row locks cannot, because there is no row yet. Exercised against a stub connection so
    the statement order can be asserted without a database to connect to."""
    pytest.importorskip("psycopg")
    from types import SimpleNamespace

    from psycopg.pq import TransactionStatus

    from app.db import PostgresConnection

    class FakeCursor:
        def __init__(self, log):
            self._log = log
            self.description = None

        def execute(self, sql, params=None):
            self._log.append(" ".join(sql.split()))

        def fetchone(self):
            return None  # an empty chain: the case that races

        def fetchall(self):
            return []

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class FakeRaw:
        def __init__(self):
            self.log: list[str] = []
            self.info = SimpleNamespace(transaction_status=TransactionStatus.IDLE)

        def cursor(self, row_factory=None):
            return FakeCursor(self.log)

        def commit(self):
            self.log.append("COMMIT")

        def rollback(self):
            self.log.append("ROLLBACK")

    raw = FakeRaw()
    event = audit.record(
        PostgresConnection(raw), actor="demo.operator", action=AuditAction.CREATE,
        resource_type="trial", resource_id="STU-001",
    )

    assert event.seq == 1 and event.prev_hash == GENESIS_HASH
    assert raw.log[0] == "SELECT pg_advisory_xact_lock(%s)"
    head_at = next(i for i, s in enumerate(raw.log)
                   if s.startswith("SELECT seq, hash FROM audit_events"))
    insert_at = next(i for i, s in enumerate(raw.log)
                     if s.startswith("INSERT INTO audit_events"))
    assert 0 < head_at < insert_at < raw.log.index("COMMIT")


# --------------------------------------------------------------------- concurrency


def _run_concurrently(path: Path, workers: int, per_worker: int):
    """Append from `workers` threads, each on its own connection, starting together."""
    events, errors = [], []
    collected = threading.Lock()
    barrier = threading.Barrier(workers)

    def worker(n: int) -> None:
        connection = db.connect(path)
        try:
            barrier.wait(timeout=30)
            for i in range(per_worker):
                event = audit.record(
                    connection,
                    actor=f"writer.{n}",
                    action=AuditAction.CREATE,
                    resource_type="probe",
                    resource_id=f"{n}-{i}",
                    after={"n": n, "i": i},
                )
                with collected:
                    events.append(event)
        except Exception as exc:  # noqa: BLE001 — collected, then asserted on
            with collected:
                errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not errors, f"concurrent writers raised: {errors!r}"
    return events


def _seeded_path(tmp_path) -> Path:
    path = tmp_path / "concurrent.db"
    setup = db.connect(path)
    db.init_schema(setup)
    setup.close()
    return path


def test_concurrent_appends_get_distinct_sequences_and_ids(tmp_path):
    """Eight writers, twenty appends: twenty distinct sequence numbers, one intact chain."""
    path = _seeded_path(tmp_path)
    events = _run_concurrently(path, workers=8, per_worker=20)

    assert len(events) == 160
    assert sorted(e.seq for e in events) == list(range(1, 161))
    assert len({e.id for e in events}) == 160

    connection = db.connect(path)
    try:
        result = audit.verify(connection)
        assert result["ok"] is True, result
        assert result["count"] == 160
        stored = {row["id"] for row in _rows(connection)}
        assert stored == {e.id for e in events}, "every returned id must be a stored id"
    finally:
        connection.close()


def test_concurrent_appends_on_an_empty_chain(tmp_path):
    """The first race two requests can ever hit: every writer wants seq 1."""
    path = _seeded_path(tmp_path)
    events = _run_concurrently(path, workers=6, per_worker=1)

    assert sorted(e.seq for e in events) == [1, 2, 3, 4, 5, 6]
    assert len({e.id for e in events}) == 6

    connection = db.connect(path)
    try:
        assert audit.verify(connection)["ok"] is True
        # Exactly one row carries the empty chain's genesis link; the rest follow it.
        assert sum(1 for e in events if e.prev_hash == GENESIS_HASH) == 1
    finally:
        connection.close()
