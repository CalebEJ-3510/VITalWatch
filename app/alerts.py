"""Alert rules.

Four rules, each reading its threshold from `config.py` and therefore from the
environment. That is deliberate and worth demonstrating: change `ENROLMENT_LAG_PCT`
in `.env`, restart, and the alert count moves. A rule with a number baked into an `if`
is a slide; a rule with a configurable threshold is a system.

Alerts are computed on read, never stored. A stored alert has to be invalidated when
the underlying data changes, and a stale critical alert on a dashboard is worse than no
alert — people learn to ignore the banner.

**Time.** Every rule takes an optional `now`, defaulting to `models.utcnow()`, and reads
no frozen reference clock. A rule that measured against a constant "today" would stop
firing the moment real time moved past it, which is the failure mode that makes an alert
engine worse than useless: it is quiet and it looks fine.
"""

from __future__ import annotations

from .db import Connection  # driver-neutral: SQLite or Postgres
from datetime import date, datetime, timedelta

from . import db, pv
from .config import settings
from .kpi import ACTIVE_STATUSES, ENROLMENT_WINDOW_DAYS
from .models import Alert, AlertRule, AlertSeverity, TimelineStatus, utcnow

#: Only trials that are actually recruiting can be behind on recruitment. A trial
#: awaiting site activation is at zero enrolment by design, and flagging it buries the
#: trials that are genuinely slipping.
ENROLLING_STATUSES = ("screening", "enrolling", "follow_up")

#: Ordering for display. A breached statutory deadline outranks a slipping recruitment
#: curve, and the dashboard must not make the reader work that out for themselves.
SEVERITY_ORDER = {AlertSeverity.CRITICAL: 0, AlertSeverity.WARNING: 1, AlertSeverity.INFO: 2}


def enrolment_lag(conn: Connection, now: datetime | None = None) -> list[Alert]:
    """Trials recruiting below `ENROLMENT_LAG_PCT` of where the plan says they should be.

    Measured against plan-to-date, not against the final target. A trial four months into
    a two-year window at 20% of target is on track; the same number at month twenty is not.
    """
    reference = now or utcnow()
    today = reference.date()
    out: list[Alert] = []
    placeholders = ",".join("?" * len(ENROLLING_STATUSES))

    for s in conn.execute(
        f"SELECT * FROM trials WHERE status IN ({placeholders})", ENROLLING_STATUSES
    ):
        elapsed = (today - date.fromisoformat(s["start_date"])).days
        progress = min(max(elapsed / ENROLMENT_WINDOW_DAYS, 0.0), 1.0)
        expected = int(s["target_enrolment"] * progress)
        if expected <= 0:
            continue  # too early to be behind

        attainment = 100.0 * s["actual_enrolment"] / expected
        if attainment >= settings.enrolment_lag_pct:
            continue

        out.append(
            Alert(
                id=f"ALERT-LAG-{s['id']}",
                rule=AlertRule.ENROLMENT_LAG,
                severity=AlertSeverity.CRITICAL if attainment < 50 else AlertSeverity.WARNING,
                trial_id=s["id"],
                trial_title=s["title"],
                message=(
                    f"Enrolment at {attainment:.0f}% of plan — {s['actual_enrolment']} participants "
                    f"against {expected} expected by today "
                    f"(threshold {settings.enrolment_lag_pct:.0f}%)."
                ),
                raised_at=reference,
                deep_link=f"/trial/{s['id']}",
            )
        )
    return out


def ethics_renewal_due(conn: Connection, now: datetime | None = None) -> list[Alert]:
    """Ethics approvals expiring within `ETHICS_RENEWAL_DAYS`, or already expired.

    An expired approval is not a reminder, it is a stop-work condition: the trial has no
    current ethical clearance to be recruiting under.
    """
    reference = now or utcnow()
    today = reference.date()
    out: list[Alert] = []
    placeholders = ",".join("?" * len(ACTIVE_STATUSES))

    for s in conn.execute(
        f"""SELECT *, {db.days_between('ec_expiry_date', '?')} AS days_left
              FROM trials
             WHERE status IN ({placeholders}) AND ec_expiry_date IS NOT NULL""",
        (today.isoformat(), *ACTIVE_STATUSES),
    ):
        days = s["days_left"]
        if days is None or days > settings.ethics_renewal_days:
            continue

        expired = days < 0
        out.append(
            Alert(
                id=f"ALERT-EC-{s['id']}",
                rule=AlertRule.ETHICS_RENEWAL_DUE,
                severity=AlertSeverity.CRITICAL if expired else AlertSeverity.WARNING,
                trial_id=s["id"],
                trial_title=s["title"],
                message=(
                    f"Ethics approval expired {abs(days)} days ago ({s['ec_expiry_date']}) — "
                    f"the trial has no current clearance."
                    if expired
                    else f"Ethics approval expires in {days} days ({s['ec_expiry_date']}). "
                         f"Renewal submission is due."
                ),
                raised_at=reference,
                deep_link=f"/trial/{s['id']}",
            )
        )
    return out


def monitoring_visit_overdue(conn: Connection, now: datetime | None = None) -> list[Alert]:
    """Monitoring visits that are outstanding, on either of two counts:

    * scheduled more than `MONITORING_OVERDUE_DAYS` ago and never conducted, or
    * conducted, but the monitoring report was never filed.

    This is the same predicate as `kpi._overdue_monitoring_visits`, exactly and on
    purpose. The second case was previously missing here, which meant the KPI counted a
    conducted-but-unreported visit as overdue while no alert existed for it: the
    dashboard reported a number with nothing behind it. A conducted visit with no report
    is not evidence of oversight, so it is overdue by both counts.

    One alert per trial rather than one per visit. Twelve rows saying the same thing
    about the same trial is noise, and noise is how a real breach gets scrolled past.
    """
    reference = now or utcnow()
    today = reference.date()
    cutoff = date.fromordinal(today.toordinal() - settings.monitoring_overdue_days).isoformat()
    out: list[Alert] = []

    for row in conn.execute(
        """SELECT s.id, s.title,
                  SUM(CASE WHEN v.actual_date IS NULL THEN 1 ELSE 0 END) AS not_conducted,
                  SUM(CASE WHEN v.actual_date IS NOT NULL AND v.report_filed = 0
                           THEN 1 ELSE 0 END) AS no_report,
                  MIN(CASE WHEN v.actual_date IS NULL THEN v.scheduled_date END) AS oldest
             FROM visits v JOIN trials s ON s.id = v.trial_id
            WHERE v.monitoring_visit = 1
              AND ( (v.actual_date IS NULL AND v.scheduled_date < ?)
                    OR (v.actual_date IS NOT NULL AND v.report_filed = 0) )
            GROUP BY s.id, s.title""",
        (cutoff,),
    ):
        missed = row["not_conducted"] or 0
        unreported = row["no_report"] or 0
        total = missed + unreported
        oldest = row["oldest"]
        days_late = (today - date.fromisoformat(oldest)).days if oldest else None

        reasons = []
        if missed:
            reasons.append(
                f"{missed} not conducted"
                + (f", the oldest scheduled {days_late} days ago" if days_late is not None else "")
            )
        if unreported:
            reasons.append(f"{unreported} conducted with no report filed")

        out.append(
            Alert(
                id=f"ALERT-MV-{row['id']}",
                rule=AlertRule.MONITORING_VISIT_OVERDUE,
                # A visit never conducted and long past schedule is the serious case; a
                # filed-less report is a documentation gap. Both are overdue, neither is
                # the same finding.
                severity=(
                    AlertSeverity.CRITICAL
                    if days_late is not None and days_late > 90
                    else AlertSeverity.WARNING
                ),
                trial_id=row["id"],
                trial_title=row["title"],
                message=(
                    f"{total} monitoring visit{'' if total == 1 else 's'} overdue — "
                    + "; ".join(reasons)
                    + f" (threshold {settings.monitoring_overdue_days} days for a visit not "
                      "yet conducted)."
                ),
                raised_at=reference,
                deep_link=f"/trial/{row['id']}",
            )
        )
    return out


def sae_timeline_breach(conn: Connection, now: datetime | None = None) -> list[Alert]:
    """Serious events whose 24-hour reporting deadline has arrived or passed.

    The status is **derived on read** from the stored `deadline_24h` by `pv.status_for`;
    the stored `timeline_status` column is never read. A rule driven by the stored column
    would freeze the judgement at intake, so an event entered with 23 hours left would go
    on reading "on track" forever — the clock would be a decoration.

    A serious event whose stored deadline is missing or unreadable is included, at
    critical severity, because an unevaluable clock must not read as a met one. It is
    counted separately so the message can say which kind of problem it is.

    One alert per trial, on the same noise policy as the monitoring rule; the message
    names the most overdue event.

    The message states the *deadline passage* and nothing more. No external submission
    timestamp is recorded by this system (see `pv.CLOCK_PROTOTYPE_LIMITATIONS`), so a
    breach here is not a finding that a report was filed late, and the wording is not
    allowed to imply one.
    """
    reference = now or utcnow()
    rows = conn.execute(
        # `a.serious` is selected as well as filtered on: `pv.status_for` reads the flag
        # from the row it is handed, so a query that filtered on it without selecting it
        # would classify every event as non-serious — silently, and in the safe-looking
        # direction, which is exactly the failure this rule exists to prevent.
        """SELECT a.id, a.trial_id, a.participant_code, a.serious, a.deadline_24h,
                  a.timeline_status, s.title AS trial_title
             FROM adverse_events a JOIN trials s ON s.id = a.trial_id
            WHERE a.serious = 1"""
    ).fetchall()

    worst: dict[str, dict] = {}
    for row in rows:
        if pv.status_for(row, reference) is not TimelineStatus.BREACHED:
            continue
        group = worst.setdefault(
            row["trial_id"],
            {"title": row["trial_title"], "n": 0, "unknown": 0,
             "hours": None, "deadline": None},
        )
        group["n"] += 1
        if pv.clock_reason(row) in pv.UNKNOWN_REASONS:
            group["unknown"] += 1
            continue
        hours = pv.hours_remaining(pv.event_deadline(row), reference)
        if hours is not None and (group["hours"] is None or hours < group["hours"]):
            group["hours"] = hours
            group["deadline"] = pv.event_deadline(row)

    out: list[Alert] = []
    for trial_id, group in sorted(worst.items()):
        n = group["n"]
        unevaluable = group["unknown"]
        if group["hours"] is None:
            detail = (
                f"{unevaluable} serious event{'' if unevaluable == 1 else 's'} with no "
                "readable 24-hour deadline recorded — the clock cannot be evaluated and is "
                "being treated as breached. Verify the intake record."
            )
        else:
            detail = (
                f"{n} serious event{'' if n == 1 else 's'} past the 24-hour reporting "
                f"deadline — the most overdue by {abs(group['hours']):.0f}h "
                f"(deadline {group['deadline'].isoformat()})."
            )
            if unevaluable:
                detail += (
                    f" {unevaluable} of these ha{'' if unevaluable == 1 else 've'} no "
                    "readable deadline recorded either."
                )
        detail += " (Deadline passage only: no external submission timestamp is recorded.)"

        out.append(
            Alert(
                id=f"ALERT-SAE-{trial_id}",
                rule=AlertRule.SAE_TIMELINE_BREACH,
                severity=AlertSeverity.CRITICAL,
                trial_id=trial_id,
                trial_title=group["title"],
                message=detail,
                raised_at=reference,
                deep_link="/ae",
            )
        )
    return out


#: The rule set. Adding a rule means adding a function here, nothing else.
RULES = (sae_timeline_breach, enrolment_lag, ethics_renewal_due, monitoring_visit_overdue)


def evaluate(conn: Connection, now: datetime | None = None) -> list[Alert]:
    """Run every rule and return the alerts, most severe first.

    `now` is passed to every rule so a whole evaluation is measured against one instant;
    without it each rule would read the clock separately and two rules could disagree
    about the day.
    """
    raised = [alert for rule in RULES for alert in rule(conn, now)]
    return sorted(raised, key=lambda a: (SEVERITY_ORDER[a.severity], a.trial_id))


if __name__ == "__main__":
    from .db import connect

    alerts = evaluate(connect())
    print(f"{len(alerts)} alert(s) at thresholds "
          f"lag<{settings.enrolment_lag_pct:.0f}%  ec<{settings.ethics_renewal_days}d  "
          f"mv>{settings.monitoring_overdue_days}d")
    for a in alerts:
        print(f"  [{a.severity.value:<8}] {a.trial_id}  {a.message}")
