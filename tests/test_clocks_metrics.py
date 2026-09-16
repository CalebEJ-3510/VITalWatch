"""Clock, counter and alert tests — isolated, time-controlled, no external anything.

What these tests prove, in the order the defects were found:

1. `kpi._today()` is the live server clock, not `datagen.TODAY`. A frozen "today" makes
   every ageing, compliance and overdue figure report the seed date instead of the present.
2. The stored `timeline_status` column is a snapshot, never truth: status is derived on
   read from the stored `deadline_24h`, so advancing `now` alone changes it.
3. Boundaries are inclusive: `<= 0` hours left is breached, `<=` the due-soon window is
   due soon.
4. A serious event whose deadline is missing or malformed never reads as safe, and the
   reason stays recoverable.
5. `pv.clock_counts` partitions the table and agrees with the per-row helper over time.
6. The monitoring alert fires on both limbs of the KPI's predicate, including the
   conducted-with-no-report limb it previously missed.
7. The SAE alert path is driven by live status, never the stored column, and appears as
   time passes.

Isolation: a fresh SQLite file under pytest's `tmp_path` per test, with `db`'s Postgres
branch forced off. No `.env`, no `DATABASE_URL`, no network, no shared database file.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # `python -m pytest` from the root already does this
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402
from datetime import date, datetime, timedelta, timezone  # noqa: E402

from app import alerts, db, kpi, pv  # noqa: E402
from app.config import settings  # noqa: E402
from app.models import AlertRule, AlertSeverity, TimelineStatus, utcnow  # noqa: E402

UTC = timezone.utc

#: Fixed instant to reason from. Clock assertions pass `now` explicitly, so the suite
#: answers identically whenever it runs.
T0 = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)

#: Read from settings, not hardcoded: a test that hardcodes a threshold stops checking
#: the configuration the moment it is changed.
REPORT_HOURS = settings.sae_initial_report_hours
NARRATIVE_DAYS = settings.sae_narrative_days
DUE_SOON_HOURS = settings.sae_due_soon_hours

_UNSET = object()  # "leave alone", distinct from None = "store NULL"


# ------------------------------------------------------------------------ helpers


def _insert(conn, table: str, **values) -> None:
    columns = ", ".join(values)
    marks = ", ".join("?" * len(values))
    conn.execute(f"INSERT INTO {table} ({columns}) VALUES ({marks})", tuple(values.values()))


def add_study(conn, trial_id: str = "STU-001", **overrides) -> str:
    row = {
        "id": trial_id, "title": f"{trial_id} — Test trial", "protocol_no": f"VW/{trial_id}",
        "ctri_number": None, "phase": "III", "status": "enrolling",
        "therapeutic_area": "Rheumatology", "ec_approval_date": "2026-01-01",
        "ec_expiry_date": "2030-01-01", "ctri_registration_date": None,
        "target_enrolment": 100, "actual_enrolment": 20, "pi_name": "Dr Test",
        "start_date": "2026-01-01", "end_date": None,
    }
    row.update(overrides)
    _insert(conn, "trials", **row)
    return trial_id


def add_site(conn, site_id: str = "SITE-1") -> str:
    _insert(conn, "sites", id=site_id, name=f"{site_id} site", city="Pune", state="MH",
            status="activated", activated_date="2026-01-01", pi_name="Dr Test", capacity=100)
    return site_id


def add_subject(conn, participant_code: str = "SUBJ-1", site_id: str = "SITE-1") -> str:
    _insert(conn, "participants", id=f"ID-{participant_code}", participant_code=participant_code,
            trial_id="STU-001", site_id=site_id, screened_date="2026-01-02",
            enrolled_date="2026-01-02", status="enrolled", arm="A", age_band="31-45",
            sex="F", consent_version="v1.0", consent_date="2026-01-02")
    return participant_code


def add_event(conn, ae_id: str = "AE-1", reported_at=T0, *, serious: int = 1,
              deadline=_UNSET, stored_status: str = "not_applicable",
              outcome: str = "recovered", coded_term: str | None = None,
              trial_id: str = "STU-001", participant_code: str = "SUBJ-1") -> str:
    """Insert an adverse event.

    `deadline` defaults to 24 h after `reported_at` when serious, NULL otherwise. Pass a
    value — including `None` or a malformed string — to store exactly that, which is how
    the missing/malformed cases are built.
    """
    if deadline is _UNSET:
        deadline = reported_at + timedelta(hours=REPORT_HOURS) if serious else None
    _insert(
        conn, "adverse_events",
        id=ae_id, trial_id=trial_id, site_id="SITE-1", participant_code=participant_code,
        narrative="Patient reported a headache.", onset_date="2026-09-14", serious=serious,
        severity="moderate", causality="possible", outcome=outcome, coded_term=coded_term,
        coded_code=None, coding_confidence=None,
        coding_source="curated" if coded_term else "uncoded", suspect_drug=None,
        drug_code=None, drug_coding_source="uncoded",
        reported_at=reported_at.isoformat() if isinstance(reported_at, datetime) else reported_at,
        deadline_24h=deadline.isoformat() if isinstance(deadline, datetime) else deadline,
        deadline_14d=(reported_at + timedelta(days=NARRATIVE_DAYS)).isoformat()
        if isinstance(reported_at, datetime) and serious else None,
        timeline_status=stored_status,
    )
    return ae_id


def add_visit(conn, visit_id: str, *, scheduled: str, actual: str | None = None,
              report_filed: int = 0, monitoring: int = 1,
              trial_id: str = "STU-001") -> str:
    _insert(conn, "visits", id=visit_id, trial_id=trial_id, site_id="SITE-1",
            participant_code=None, visit_name="Monitoring visit", scheduled_date=scheduled,
            actual_date=actual, window_days=0,
            status="completed" if actual else "overdue", monitoring_visit=monitoring,
            report_filed=report_filed)
    return visit_id


# ----------------------------------------------------------------------- fixtures


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    """A fresh, isolated SQLite database per test.

    The Postgres branch is forced off so the suite cannot reach a hosted database even if
    the developer's `.env` sets `DATABASE_URL`. The file lives under `tmp_path`; pytest
    removes it.
    """
    monkeypatch.setattr(db, "is_postgres", lambda: False)
    connection = db.connect(tmp_path / "clocks-test.db")
    db.init_schema(connection)
    assert db.backend() == "sqlite"
    yield connection
    connection.close()


@pytest.fixture()
def sample(conn):
    """One trial, one site, one participant — the minimum for a row to satisfy its FKs."""
    add_study(conn)
    add_site(conn)
    add_subject(conn)
    return conn


# ------------------------------------------------------------------- the live clock


def test_today_is_the_live_server_clock(monkeypatch):
    assert kpi._today() == utcnow().date()

    injected = datetime(2031, 3, 4, 23, 30, tzinfo=UTC)
    monkeypatch.setattr(kpi, "utcnow", lambda: injected)
    assert kpi._today() == date(2031, 3, 4)


def test_today_is_not_pinned_to_the_seeders_reference_date():
    assert not hasattr(kpi, "TODAY")  # the frozen import is gone, not bypassed

    from app import datagen

    assert isinstance(datagen.TODAY, date)  # still a legitimate input to the seeder
    if datagen.TODAY != utcnow().date():
        assert kpi._today() != datagen.TODAY


def test_date_relative_kpis_move_when_the_clock_moves(monkeypatch):
    monkeypatch.setattr(kpi, "utcnow", lambda: T0)
    early = kpi.expected_enrolment("2026-01-01", 400)

    monkeypatch.setattr(kpi, "utcnow", lambda: T0 + timedelta(days=100))
    later = kpi.expected_enrolment("2026-01-01", 400)

    assert later > early
    assert early == int(400 * ((T0.date() - date(2026, 1, 1)).days / kpi.ENROLMENT_WINDOW_DAYS))


# ------------------------------------------------------------- intake clock maths


def test_compute_clocks_returns_deadlines_and_a_live_status():
    d24, d14, status = pv.compute_clocks(T0, True, now=T0)

    assert d24 == T0 + timedelta(hours=REPORT_HOURS)
    assert d14 == T0 + timedelta(days=NARRATIVE_DAYS)
    assert status is TimelineStatus.ON_TRACK
    assert pv.hours_remaining(d24, T0) == float(REPORT_HOURS)


def test_compute_clocks_boundaries_are_inclusive():
    """`<= 0` is breached; `<=` the due-soon window is due soon. Tested at the edges."""
    d24 = T0 + timedelta(hours=REPORT_HOURS)

    def at(now):
        return pv.compute_clocks(T0, True, now=now)[2]

    assert at(d24 - timedelta(hours=DUE_SOON_HOURS, seconds=1)) is TimelineStatus.ON_TRACK
    assert at(d24 - timedelta(hours=DUE_SOON_HOURS)) is TimelineStatus.DUE_SOON
    assert at(d24 - timedelta(seconds=1)) is TimelineStatus.DUE_SOON
    # Exactly on the deadline: the clock has run out, so breach, not warning.
    assert at(d24) is TimelineStatus.BREACHED
    assert at(d24 + timedelta(seconds=1)) is TimelineStatus.BREACHED


def test_a_non_serious_event_carries_no_clock():
    assert pv.compute_clocks(T0, False) == (None, None, TimelineStatus.NOT_APPLICABLE)
    assert pv.hours_remaining(None) is None
    assert pv.status_for({"serious": 0, "deadline_24h": None}) is TimelineStatus.NOT_APPLICABLE


def test_due_soon_window_is_read_from_settings(monkeypatch):
    deadline = T0 + timedelta(hours=DUE_SOON_HOURS + 1)
    assert pv.status_for_deadline(deadline, T0) is TimelineStatus.ON_TRACK

    monkeypatch.setattr(settings, "sae_due_soon_hours", DUE_SOON_HOURS + 2)
    assert pv.status_for_deadline(deadline, T0) is TimelineStatus.DUE_SOON


def test_timestamps_are_normalised_to_aware_utc():
    naive = datetime(2026, 9, 15, 12, 0)
    offset = datetime(2026, 9, 15, 17, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    expected = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)

    assert pv.as_utc(naive) == expected
    assert pv.as_utc(offset) == expected
    assert pv.parse_timestamp(naive) == expected
    assert pv.parse_timestamp("2026-09-15T12:00:00Z") == expected
    assert pv.parse_timestamp("2026-09-15T17:30:00+05:30") == expected
    assert pv.parse_timestamp("  2026-09-15T12:00:00Z  ") == expected
    assert pv.parse_timestamp(None) is None
    assert pv.parse_timestamp("") is None
    assert pv.parse_timestamp("not a date") is None

    # Intake normalises too, so a naive report and the equivalent offset report store the
    # same instant: no naive row is ever written beside aware ones.
    assert pv.compute_clocks(naive, True)[0] == pv.compute_clocks(offset, True)[0]
    assert pv.compute_clocks(naive, True)[0].tzinfo is UTC


def test_naive_and_aware_never_crash_together():
    event = {"serious": 1, "deadline_24h": "2026-09-16T12:00:00"}  # naive text
    naive_now = datetime(2026, 9, 16, 11, 0)                       # naive caller

    assert pv.status_for(event, now=naive_now) is TimelineStatus.DUE_SOON
    assert pv.hours_remaining(event["deadline_24h"], naive_now) == 1.0
    assert pv.status_for(event, now=T0) is TimelineStatus.ON_TRACK
    assert pv.hours_remaining(datetime(2026, 9, 16, 12, 0), T0) == 24.0


# ------------------------------------------------------------------ stored != truth


def test_stored_status_is_never_the_truth(sample):
    """A stored snapshot that disagrees with the deadline loses, in both directions."""
    add_event(sample, "AE-EXPIRED", T0 - timedelta(hours=REPORT_HOURS + 1),
              stored_status="on_track")
    add_event(sample, "AE-FUTURE", T0 + timedelta(days=6), stored_status="breached")

    expired = sample.execute("SELECT * FROM adverse_events WHERE id = 'AE-EXPIRED'").fetchone()
    future = sample.execute("SELECT * FROM adverse_events WHERE id = 'AE-FUTURE'").fetchone()

    assert pv.status_for(expired, T0) is TimelineStatus.BREACHED
    assert pv.status_for(future, T0) is TimelineStatus.ON_TRACK

    live = pv.with_live_status(expired, T0)
    assert live["timeline_status"] == "breached"
    assert live["stored_timeline_status"] == "on_track"
    assert live["status_source"] == "derived"


def test_a_stored_breach_on_a_non_serious_event_is_ignored(sample):
    add_event(sample, "AE-MILD", T0 - timedelta(days=5), serious=0, stored_status="breached")
    row = sample.execute("SELECT * FROM adverse_events WHERE id = 'AE-MILD'").fetchone()

    assert pv.status_for(row, T0) is TimelineStatus.NOT_APPLICABLE
    assert pv.with_live_status(row, T0)["hours_left"] is None


def test_one_event_transitions_as_time_passes(sample):
    """The whole point: nothing is written, only the clock advances."""
    add_event(sample, "AE-1", T0)
    row = sample.execute("SELECT * FROM adverse_events WHERE id = 'AE-1'").fetchone()
    deadline = T0 + timedelta(hours=REPORT_HOURS)

    for now, expected in [
        (T0, TimelineStatus.ON_TRACK),
        (deadline - timedelta(hours=DUE_SOON_HOURS, seconds=1), TimelineStatus.ON_TRACK),
        (deadline - timedelta(hours=DUE_SOON_HOURS), TimelineStatus.DUE_SOON),
        (deadline - timedelta(seconds=1), TimelineStatus.DUE_SOON),
        (deadline, TimelineStatus.BREACHED),
        (deadline + timedelta(days=30), TimelineStatus.BREACHED),
    ]:
        assert pv.status_for(row, now) is expected, now


def test_missing_deadline_on_a_serious_event_never_reads_safe(sample):
    add_event(sample, "AE-NODATE", T0, deadline=None, stored_status="on_track")
    row = sample.execute("SELECT * FROM adverse_events WHERE id = 'AE-NODATE'").fetchone()

    assert pv.clock_reason(row) == pv.REASON_MISSING
    assert pv.status_for(row, T0) is TimelineStatus.BREACHED
    assert pv.status_for(row, T0) is not TimelineStatus.ON_TRACK

    live = pv.with_live_status(row, T0)
    assert live["clock_unknown"] is True
    assert live["hours_left"] is None  # unknown, not a fabricated number
    assert live["timeline_status"] == TimelineStatus.BREACHED.value


def test_malformed_deadline_on_a_serious_event_never_reads_safe(sample):
    for ae_id, bad in (("AE-BAD", "sometime next week"), ("AE-BLANK", "   ")):
        add_event(sample, ae_id, T0, deadline=bad, stored_status="on_track")
        row = sample.execute("SELECT * FROM adverse_events WHERE id = ?", (ae_id,)).fetchone()

        assert pv.clock_reason(row) in pv.UNKNOWN_REASONS
        assert pv.status_for(row, T0) is TimelineStatus.BREACHED
        assert pv.with_live_status(row, T0)["clock_unknown"] is True
        assert pv.hours_remaining(row["deadline_24h"], T0) is None


def test_status_reads_rows_dicts_models_and_objects(sample):
    """sqlite3.Row, a dict, a plain object and the pydantic model all take one path."""
    from app.models import AdverseEvent

    add_event(sample, "AE-1", T0)
    row = sample.execute("SELECT * FROM adverse_events WHERE id = 'AE-1'").fetchone()
    assert not isinstance(row, dict)

    class Modelish:  # duck-typed stand-in, attribute access only
        serious = True
        deadline_24h = T0 + timedelta(hours=REPORT_HOURS)

    # Status derivation works for any of them, including a bare object exposing the
    # column names as attributes.
    for event in (row, dict(row), Modelish()):
        assert pv.is_serious(event) is True
        assert pv.status_for(event, T0) is TimelineStatus.ON_TRACK

    # `with_live_status` copies the record, so it needs something with columns to copy:
    # a row or a mapping (which is what a query returns).
    for event in (row, dict(row)):
        assert pv.with_live_status(event, T0)["status_source"] == "derived"
        assert pv.with_live_status(event, T0)["timeline_status"] == "on_track"

    model = AdverseEvent(
        id="AE-M", trial_id="STU-001", site_id="SITE-1", participant_code="SUBJ-1",
        narrative="n", onset_date=date(2026, 9, 14), serious=True, severity="moderate",
        causality="possible", outcome="recovered", reported_at=T0,
        deadline_24h=T0 + timedelta(hours=REPORT_HOURS),
        deadline_14d=T0 + timedelta(days=NARRATIVE_DAYS),
        timeline_status=TimelineStatus.ON_TRACK,
    )
    assert pv.status_for(model, T0) is TimelineStatus.ON_TRACK
    assert pv.status_for(model, T0 + timedelta(days=2)) is TimelineStatus.BREACHED
    assert pv.with_live_status(model, T0)["id"] == "AE-M"


def test_serious_flag_accepts_every_driver_representation():
    for truthy in (True, 1, "1", "true", "TRUE", "yes"):
        assert pv.is_serious({"serious": truthy}) is True
    for falsy in (False, 0, "0", "false", "", None):
        assert pv.is_serious({"serious": falsy}) is False
    assert pv.is_serious({}) is False  # a row that did not select the column


# ------------------------------------------------------------------- the counters


def _make_mixed_portfolio(conn) -> None:
    """One event in each clock state, plus a non-serious one."""
    add_event(conn, "AE-BREACHED", T0 - timedelta(hours=REPORT_HOURS + 5), stored_status="on_track")
    add_event(conn, "AE-DUESOON", T0 - timedelta(hours=REPORT_HOURS - 4))   # 4 h left
    add_event(conn, "AE-TRACK", T0)                                        # 24 h left
    add_event(conn, "AE-UNKNOWN", T0, deadline=None)                       # unreadable
    add_event(conn, "AE-MILD", T0 - timedelta(days=3), serious=0)


def test_clock_counts_partitions_and_matches_the_per_row_helper(sample):
    _make_mixed_portfolio(sample)
    counts = pv.clock_counts(sample, T0)

    assert counts["total"] == 5
    assert counts["serious"] == 4
    assert counts["breached"] == 2      # the expired one and the unevaluable one
    assert counts["due_soon"] == 1
    assert counts["on_track"] == 1
    assert counts["not_applicable"] == 1

    # The buckets partition the table: no event counted twice, none dropped.
    assert (counts["breached"] + counts["due_soon"] + counts["on_track"]
            + counts["not_applicable"]) == counts["total"]

    # `unknown` marks a subset of `breached` rather than a fifth bucket.
    assert counts["unknown"] == 1
    assert counts["unknown"] <= counts["breached"]
    assert counts["unknown_event_ids"] == ("AE-UNKNOWN",)

    # The aggregate is exactly the sum of the per-row helper, so they cannot drift apart.
    by_status: dict[str, int] = {}
    for row in sample.execute("SELECT * FROM adverse_events").fetchall():
        by_status[pv.status_for(row, T0).value] = by_status.get(
            pv.status_for(row, T0).value, 0) + 1
    assert by_status == {
        "breached": counts["breached"], "due_soon": counts["due_soon"],
        "on_track": counts["on_track"], "not_applicable": counts["not_applicable"],
    }


def test_clock_counts_move_with_the_clock(sample):
    _make_mixed_portfolio(sample)

    before = pv.clock_counts(sample, T0)
    later = pv.clock_counts(sample, T0 + timedelta(hours=5))  # the due-soon one breaches

    assert before["due_soon"] == 1 and later["due_soon"] == 0
    assert later["breached"] == before["breached"] + 1
    assert before["total"] == later["total"]
    assert pv.clock_counts(sample)["total"] == before["total"]  # default = real clock


def test_clock_counts_on_an_empty_table(conn):
    counts = pv.clock_counts(conn, T0)
    assert counts["total"] == 0 and counts["unknown"] == 0
    assert counts["unknown_event_ids"] == ()


# ------------------------------------------------------------------------- alerts


def metric(data: dict, label: str):
    return next(m for m in data["metrics"] if m.label == label)


def sae_alerts(conn, now=None) -> list:
    return [a for a in alerts.evaluate(conn, now) if a.rule is AlertRule.SAE_TIMELINE_BREACH]


def mv_alerts(conn, now=None) -> list:
    return [a for a in alerts.evaluate(conn, now)
            if a.rule is AlertRule.MONITORING_VISIT_OVERDUE]


def add_overdue_monitoring(conn, trial_id: str = "STU-001", today=None, ref=None) -> int:
    """One old unconducted monitoring visit and one conducted with no report filed."""
    today = today or (ref or T0).date()
    add_visit(conn, f"V-{trial_id}-OLD", scheduled=(today - timedelta(days=30)).isoformat(),
              trial_id=trial_id)
    add_visit(conn, f"V-{trial_id}-NOREPORT", scheduled=(today - timedelta(days=2)).isoformat(),
              actual=(today - timedelta(days=2)).isoformat(), report_filed=0,
              trial_id=trial_id)
    return 2


def test_every_existing_rule_is_still_registered():
    """The SAE rule was added; nothing was removed to make room for it."""
    assert len(alerts.RULES) == 4
    for preserved in (alerts.enrolment_lag, alerts.ethics_renewal_due,
                      alerts.monitoring_visit_overdue):
        assert preserved in alerts.RULES
    assert alerts.sae_timeline_breach in alerts.RULES


def test_evaluate_returns_sorted_unique_alerts(conn):
    # A trial that opened yesterday: the enrolment-lag rule has nothing to say at T0, so
    # exactly the two rules under test are the ones expected to fire.
    add_study(conn, "STU-001", start_date="2026-09-14")
    add_site(conn)
    add_subject(conn)
    add_event(conn, "AE-1", T0 - timedelta(hours=REPORT_HOURS + 2))
    add_overdue_monitoring(conn, ref=T0)
    found = alerts.evaluate(conn, T0)

    assert len(found) == 2
    assert {a.rule for a in found} == {AlertRule.SAE_TIMELINE_BREACH,
                                       AlertRule.MONITORING_VISIT_OVERDUE}
    assert found == sorted(found, key=lambda a: (alerts.SEVERITY_ORDER[a.severity], a.trial_id))
    ids = [a.id for a in found]
    assert len(ids) == len(set(ids))
    assert all(a.rule in set(AlertRule) for a in found)
    # Every alert was raised against the instant the whole evaluation was measured at.
    assert all(a.raised_at == T0 for a in found)
    # The expired SAE and the overdue monitoring visit, on one trial.
    assert {a.rule for a in found} == {AlertRule.SAE_TIMELINE_BREACH,
                                       AlertRule.MONITORING_VISIT_OVERDUE}


def test_monitoring_alert_fires_on_both_limbs_like_the_kpi(sample):
    """The conducted-with-no-report limb was the one the alert used to miss."""
    today = T0.date()
    add_visit(sample, "V-OLD", scheduled=(today - timedelta(days=30)).isoformat())
    add_visit(sample, "V-NOREPORT", scheduled=(today - timedelta(days=2)).isoformat(),
              actual=(today - timedelta(days=2)).isoformat(), report_filed=0)
    add_visit(sample, "V-RECENT", scheduled=(today - timedelta(days=3)).isoformat())
    add_visit(sample, "V-FILED", scheduled=(today - timedelta(days=60)).isoformat(),
              actual=(today - timedelta(days=59)).isoformat(), report_filed=1)
    # A participant visit that was never completed is not a monitoring visit.
    add_visit(sample, "V-SUBJECT", scheduled=(today - timedelta(days=90)).isoformat(),
              monitoring=0)

    found = mv_alerts(sample, T0)
    kpi_count = kpi.portfolio_kpi(sample, today=today).overdue_monitoring_visits

    assert kpi_count == 2          # V-OLD and V-NOREPORT, not V-SUBJECT
    assert len(found) == 1         # one alert per trial
    message = found[0].message
    assert "not conducted" in message and "no report filed" in message
    # 30 days late is overdue but not the long-stop severity.
    assert found[0].severity is AlertSeverity.WARNING

    # A visit over 90 days past schedule is the critical case.
    add_study(sample, "STU-002")
    add_visit(sample, "V-ANCIENT", scheduled=(today - timedelta(days=120)).isoformat(),
              trial_id="STU-002")
    ancient = mv_alerts(sample, T0)
    assert sorted(a.trial_id for a in ancient) == ["STU-001", "STU-002"]
    # And the more severe trial is presented first.
    by_study = {a.trial_id: a for a in ancient}
    assert by_study["STU-002"].severity is AlertSeverity.CRITICAL
    assert ancient[0].trial_id == "STU-002"


def test_monitoring_alert_agrees_with_the_kpi_on_the_default_clock(sample):
    """Same predicate, same answer, with neither given an injected instant."""
    today = utcnow().date()
    add_visit(sample, "V-OLD", scheduled=(today - timedelta(days=30)).isoformat())
    add_visit(sample, "V-NOREPORT", scheduled=(today - timedelta(days=1)).isoformat(),
              actual=(today - timedelta(days=1)).isoformat(), report_filed=0)
    add_study(sample, "STU-002")
    add_visit(sample, "V-2-NOREPORT", scheduled=(today - timedelta(days=1)).isoformat(),
              actual=(today - timedelta(days=1)).isoformat(), report_filed=0,
              trial_id="STU-002")

    assert kpi.portfolio_kpi(sample).overdue_monitoring_visits == 3
    assert sorted(a.trial_id for a in mv_alerts(sample)) == ["STU-001", "STU-002"]


def test_sae_alert_is_driven_by_live_status_not_the_stored_column(sample):
    # Expired, but stored "on track": must alert.
    add_event(sample, "AE-EXPIRED", T0 - timedelta(hours=REPORT_HOURS + 6),
              stored_status="on_track")
    # Stored "breached", but a deadline six days out: must not alert.
    add_study(sample, "STU-002")
    add_event(sample, "AE-FUTURE", T0 + timedelta(days=6), stored_status="breached",
              trial_id="STU-002")

    found = sae_alerts(sample, T0)
    assert [a.trial_id for a in found] == ["STU-001"]
    assert found[0].id == "ALERT-SAE-STU-001"
    assert found[0].severity is AlertSeverity.CRITICAL
    assert "past the 24-hour reporting deadline" in found[0].message
    assert "no external submission timestamp is recorded" in found[0].message


def test_sae_alert_flags_an_unevaluable_deadline_conservatively(sample):
    add_event(sample, "AE-UNKNOWN", T0, deadline=None, stored_status="on_track")

    found = sae_alerts(sample, T0)
    assert len(found) == 1
    assert found[0].severity is AlertSeverity.CRITICAL
    assert "no readable 24-hour deadline recorded" in found[0].message
    assert "treated as breached" in found[0].message


def test_sae_alert_appears_as_time_passes(sample):
    """Nothing is written between the two calls: only `now` moves."""
    add_event(sample, "AE-1", T0)

    assert sae_alerts(sample, T0) == []
    later = sae_alerts(sample, T0 + timedelta(hours=REPORT_HOURS + 3))
    assert len(later) == 1
    assert "the most overdue by 3h" in later[0].message


def test_injected_now_reaches_the_date_based_rules_too(sample):
    """One instant for the whole evaluation, or two rules could disagree about the day."""
    add_study(sample, "STU-002", start_date="2026-09-14")  # 1 day old at T0

    def lag(now):
        return [a for a in alerts.evaluate(sample, now)
                if a.rule is AlertRule.ENROLMENT_LAG and a.trial_id == "STU-002"]

    assert lag(T0) == []                       # too early to be behind on enrolment
    assert len(lag(T0 + timedelta(days=400))) == 1


def test_ctri_update_due_rule_is_not_invented_here(conn):
    """`AlertRule.CTRI_UPDATE_DUE` has no implementation; this records the gap."""
    assert AlertRule.CTRI_UPDATE_DUE in set(AlertRule)
    assert AlertRule.CTRI_UPDATE_DUE not in {a.rule for a in alerts.evaluate(conn, T0)}


# ---------------------------------------------------------------- the safety lens


def _safety_worklist(conn, now):
    """The Safety Officer worklist is ordered by the live statutory clock."""
    events = [pv.with_live_status(event, now) for event in conn.execute(
        "SELECT * FROM adverse_events WHERE serious=1 ORDER BY reported_at DESC"
    ).fetchall()]
    priority = {"breached": 0, "due_soon": 1, "unknown": 2, "on_track": 3, "not_applicable": 4}
    return sorted(events, key=lambda event: (priority.get(event["timeline_status"], 5), event["hours_left"] if event["hours_left"] is not None else -1))


def test_safety_metrics_are_live_counts_not_stored_ones(sample):
    add_event(sample, "AE-BREACHED", T0 - timedelta(hours=REPORT_HOURS + 5), stored_status="on_track", coded_term="Headache")
    add_event(sample, "AE-DUESOON", T0 - timedelta(hours=REPORT_HOURS - 4), coded_term="Headache")
    add_event(sample, "AE-UNKNOWN", T0, deadline=None)

    counts = pv.clock_counts(sample, T0)
    assert counts["breached"] == 2
    assert counts["due_soon"] == 1


def test_safety_metrics_move_with_the_clock(sample):
    add_event(sample, "AE-DUESOON", T0 - timedelta(hours=REPORT_HOURS - 4))
    assert (pv.clock_counts(sample, T0)["breached"], pv.clock_counts(sample, T0 + timedelta(hours=5))["breached"]) == (0, 1)


def test_safety_worklist_is_ordered_by_the_live_clock(sample):
    add_event(sample, "AE-TRACK", T0, stored_status="breached")
    add_event(sample, "AE-BREACHED", T0 - timedelta(hours=REPORT_HOURS + 5), stored_status="on_track")
    add_event(sample, "AE-DUESOON", T0 - timedelta(hours=REPORT_HOURS - 4))

    worklist = _safety_worklist(sample, T0)
    assert [event["id"] for event in worklist] == ["AE-BREACHED", "AE-DUESOON", "AE-TRACK"]
    assert [event["timeline_status"] for event in worklist] == ["breached", "due_soon", "on_track"]
    assert worklist[0]["stored_timeline_status"] == "on_track"
    assert worklist[0]["status_source"] == "derived"
    assert worklist[0]["hours_left"] == -5.0


def test_safety_worklist_puts_an_unknown_deadline_where_a_reader_looks(sample):
    add_event(sample, "AE-UNKNOWN", T0, deadline=None, stored_status="on_track")
    add_event(sample, "AE-TRACK", T0)

    worklist = _safety_worklist(sample, T0)
    assert worklist[0]["id"] == "AE-UNKNOWN"
    assert worklist[0]["clock_unknown"] is True


def test_safety_reports_nothing_serious_cleanly(conn):
    assert _safety_worklist(conn, T0) == []
    assert pv.clock_counts(conn, T0)["breached"] == 0


# ------------------------------------------------------------------------ the gaps


def test_clock_limitations_are_recorded_in_code():
    text = " ".join(pv.CLOCK_PROTOTYPE_LIMITATIONS).lower()
    assert len(pv.CLOCK_PROTOTYPE_LIMITATIONS) >= 4
    assert "not established" in text          # no regulatory applicability claimed
    assert "submission" in text               # external submission timestamps absent
    assert "utc" in text                      # the naive-timestamp convention is stated
