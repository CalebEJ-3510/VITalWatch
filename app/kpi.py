"""KPI computation — read-only, straight from SQLite.

Nothing here is cached or stored. Every number is derived on request, so editing a row
in the database with `sqlite3` and refreshing the page changes the figure. That is the
answer to "are these numbers real or are they hardcoded?", and it is worth being able
to demonstrate rather than assert.

Definitions matter more than the arithmetic. Each metric below states what it counts,
because "open queries" and "overdue visits" are exactly the kind of thing two people
will define differently and then disagree about on stage.

**Time.** Every date-relative figure here is measured against the real server clock
(`models.utcnow()`, aware UTC), not the generator's reference date. A demo "today" that
is frozen to a constant keeps a report looking the same on stage and makes every ageing,
compliance and overdue figure a lie about the present — which is the one thing a
regulatory figure cannot be. What this means for the seeded portfolio is recorded in the
note on `_today`: the seed was generated relative to a fixed reference date, so figures
that count days move as real time passes, and the seed has to be re-anchored for a
sprint of work rather than frozen in code.
"""

from __future__ import annotations

from .db import Connection  # driver-neutral: SQLite or Postgres
from datetime import date

from . import db
from .config import settings
from .models import PortfolioKPI, TrialKPI, utcnow

#: A trial counts as active once it has ethics approval and before it closes out.
#: Protocol-stage and closed-out trials are real portfolio entries but nobody is
#: enrolling into them, so counting them would flatter the enrolment figures.
ACTIVE_STATUSES = (
    "ec_approval", "ctri_registered", "site_activation", "screening", "enrolling", "follow_up",
)

#: An SAE stays open until the participant has recovered or the outcome is final.
OPEN_SAE_OUTCOMES = ("recovering", "not_recovered", "unknown")

#: Planned enrolment duration, in days, from first-participant-in to last-participant-in.
#: Used to work out where a trial *should* be today. Matches datagen's milestone plan.
ENROLMENT_WINDOW_DAYS = 400


def expected_enrolment(start_date: str, target: int, today: date | None = None) -> int:
    """Where the straight-line plan says a trial should be by `today`.

    Public because three screens read it — the trial page, the portfolio table and the
    investigation's recruitment evidence — and three copies of a plan curve is three
    chances for two screens to quote different numbers for the same trial.
    """
    elapsed = ((today or _today()) - date.fromisoformat(start_date)).days
    return int(target * min(max(elapsed / ENROLMENT_WINDOW_DAYS, 0.0), 1.0))


def _today() -> date:
    """The current UTC date, from the server clock.

    Was pinned to the generator's reference date (`datagen.TODAY`), which made every
    date-relative figure — open-query ageing, visit compliance, overdue monitoring,
    expected enrolment — report the seed date rather than the present. That is the
    single most misleading kind of demo bug: the numbers look stable because they are
    stale, and they never disagree with each other because they are all measuring the
    same wrong day.

    Reads `models.utcnow()` through this module's own name so a test can substitute a
    fixed clock (`monkeypatch.setattr(kpi, "utcnow", ...)`) and prove the figures move.

    *Known consequence, for the seed:* `app/datagen.py` generates the portfolio relative
    to its own frozen reference date, and `app/case_data.py` carries an
    `EXPECTED_BY_TODAY` constant calibrated to it. With a live clock those anchors drift
    as real time passes; re-anchoring the seed is a data change, not a KPI change, and
    belongs with the seeder.
    """
    return utcnow().date()


def _scalar(conn: Connection, sql: str, params: tuple = ()) -> int:
    return conn.execute(sql, params).fetchone()[0] or 0


# ------------------------------------------------------------------ shared pieces


def _open_queries(conn: Connection, trial_id: str | None = None) -> int:
    """Queries raised and not yet closed. An answered-but-not-closed query is still open —
    someone still has to accept the answer."""
    where = "status != 'closed'"
    if trial_id:
        return _scalar(conn, f"SELECT COUNT(*) FROM queries WHERE {where} AND trial_id = ?", (trial_id,))
    return _scalar(conn, f"SELECT COUNT(*) FROM queries WHERE {where}")


def _overdue_monitoring_visits(
    conn: Connection, trial_id: str | None = None, today: date | None = None
) -> int:
    """Monitoring visits that are outstanding, on either of two counts:

    * scheduled more than `monitoring_overdue_days` ago and never conducted, or
    * conducted, but the monitoring report was never filed.

    The second case is the one site staff forget. A visit that happened but produced no
    report is not evidence of oversight.

    This predicate is shared with `alerts.monitoring_visit_overdue`, deliberately and
    exactly: the two places answers "how many monitoring visits are overdue" and they
    must not be able to disagree. Change one, change both.
    """
    cutoff = ((today or _today()) - _td(settings.monitoring_overdue_days)).isoformat()
    sql = """
        SELECT COUNT(*) FROM visits
         WHERE monitoring_visit = 1
           AND ( (actual_date IS NULL AND scheduled_date < ?)
                 OR (actual_date IS NOT NULL AND report_filed = 0) )
    """
    if trial_id:
        return _scalar(conn, sql + " AND trial_id = ?", (cutoff, trial_id))
    return _scalar(conn, sql, (cutoff,))


def _open_saes(conn: Connection, trial_id: str | None = None) -> int:
    placeholders = ",".join("?" * len(OPEN_SAE_OUTCOMES))
    sql = f"SELECT COUNT(*) FROM adverse_events WHERE serious = 1 AND outcome IN ({placeholders})"
    if trial_id:
        return _scalar(conn, sql + " AND trial_id = ?", (*OPEN_SAE_OUTCOMES, trial_id))
    return _scalar(conn, sql, OPEN_SAE_OUTCOMES)


def _td(days: int):
    from datetime import timedelta

    return timedelta(days=days)


# --------------------------------------------------------------------- portfolio


def portfolio_kpi(conn: Connection, today: date | None = None) -> PortfolioKPI:
    """The six headline numbers, plus the two totals they are read against.

    `today` is for tests and back-dated reporting; the default is the live UTC date.
    """
    placeholders = ",".join("?" * len(ACTIVE_STATUSES))
    active = conn.execute(
        f"""SELECT COUNT(*) AS n,
                   COALESCE(SUM(actual_enrolment), 0) AS enrolled,
                   COALESCE(SUM(target_enrolment), 0) AS target
              FROM trials WHERE status IN ({placeholders})""",
        ACTIVE_STATUSES,
    ).fetchone()
    sites = conn.execute(
        # CASE rather than SUM(status = 'activated'): Postgres will not sum a boolean.
        "SELECT COUNT(*) AS total, "
        "SUM(CASE WHEN status = 'activated' THEN 1 ELSE 0 END) AS activated FROM sites"
    ).fetchone()

    return PortfolioKPI(
        generated_at=utcnow(),
        active_trials=active["n"],
        enrolled_total=active["enrolled"],
        target_total=active["target"],
        sites_activated=sites["activated"] or 0,
        sites_total=sites["total"],
        open_queries=_open_queries(conn),
        overdue_monitoring_visits=_overdue_monitoring_visits(conn, today=today),
        open_saes=_open_saes(conn),
    )


# ------------------------------------------------------------------------- trial


def trial_kpi(conn: Connection, trial_id: str, today: date | None = None) -> TrialKPI | None:
    """Per-trial drill-down. Returns None if the trial does not exist.

    `today` is for tests and back-dated reporting; the default is the live UTC date.
    """
    trial = conn.execute("SELECT * FROM trials WHERE id = ?", (trial_id,)).fetchone()
    if trial is None:
        return None

    today = today or _today()
    target = trial["target_enrolment"]
    enrolled = trial["actual_enrolment"]

    # Where the plan says enrolment should be by now — a straight line from trial start
    # across the enrolment window. Crude, and honest about being crude: the gap between
    # this and `enrolled` is what drives the enrolment-lag alert.
    expected = expected_enrolment(trial["start_date"], target, today)

    screened = _scalar(conn, "SELECT COUNT(*) FROM participants WHERE trial_id = ?", (trial_id,))
    failed = _scalar(
        conn, "SELECT COUNT(*) FROM participants WHERE trial_id = ? AND status = 'screen_failed'", (trial_id,)
    )

    # Visit compliance counts only participant visits that were due by today. Upcoming
    # visits are not yet compliant or non-compliant, and including them would make a
    # trial look worse the more of it remains.
    due = _scalar(
        conn,
        "SELECT COUNT(*) FROM visits WHERE trial_id = ? AND monitoring_visit = 0 AND scheduled_date <= ?",
        (trial_id, today.isoformat()),
    )
    completed = _scalar(
        conn,
        """SELECT COUNT(*) FROM visits
            WHERE trial_id = ? AND monitoring_visit = 0 AND scheduled_date <= ? AND status = 'completed'""",
        (trial_id, today.isoformat()),
    )

    ageing = conn.execute(
        f"SELECT AVG({db.days_between('?', 'raised_date')}) FROM queries "
        "WHERE trial_id = ? AND status != 'closed'",
        (today.isoformat(), trial_id),
    ).fetchone()[0]
    # Postgres AVG returns Decimal; float() keeps the value the same shape on both engines.
    ageing = float(ageing) if ageing is not None else None

    deviations = _scalar(conn, "SELECT COUNT(*) FROM deviations WHERE trial_id = ?", (trial_id,))
    site_count = _scalar(conn, "SELECT COUNT(*) FROM trial_sites WHERE trial_id = ?", (trial_id,))

    nxt = conn.execute(
        """SELECT type, planned_date FROM milestones
            WHERE trial_id = ? AND actual_date IS NULL AND planned_date >= ?
            ORDER BY planned_date ASC LIMIT 1""",
        (trial_id, today.isoformat()),
    ).fetchone()

    return TrialKPI(
        generated_at=utcnow(),
        trial_id=trial_id,
        enrolment_pct=0.0 if target == 0 else round(100.0 * enrolled / target, 1),
        enrolled=enrolled,
        target=target,
        expected_by_today=expected,
        screen_failure_rate=0.0 if screened == 0 else round(100.0 * failed / screened, 1),
        visit_compliance_pct=0.0 if due == 0 else round(100.0 * completed / due, 1),
        open_queries=_open_queries(conn, trial_id),
        open_query_ageing_days=round(ageing or 0.0, 1),
        deviation_rate_per_site=0.0 if site_count == 0 else round(deviations / site_count, 1),
        open_saes=_open_saes(conn, trial_id),
        days_to_next_milestone=(date.fromisoformat(nxt["planned_date"]) - today).days if nxt else None,
        # Raw enum value; the `label` filter spells it the way the domain does.
        next_milestone=nxt["type"] if nxt else None,
    )
