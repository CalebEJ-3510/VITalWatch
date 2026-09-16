"""Escalation / statutory-clock / corrective-action / leadership-decision workflow.

This module owns the five governance tables defined in `app/db.py`/`app/models.py`:
`escalations`, `statutory_clocks`, `corrective_actions`, `leadership_decisions`,
`ai_findings`. It is the protocol-deviation and safety-concern escalation paths, the
statutory response clock, the Company's structured response, and the Leadership
decision with tracked conditions — see `docs/architecture.md` for the state-machine
summary.

**One escalation entity, two raisers**: an Investigator raises a `protocol_deviation`,
a Safety Officer raises a `safety_concern`. Both live in the `escalations` table,
distinguished by `escalation_type` / `raised_by_role` rather than by being two tables
that could disagree about what "open" means.

**Trial status is four independent dimensions**, never one field overloaded to mean
several things:

  * `status`             — lifecycle stage. Never touched by this module.
  * `operational_status` — active / paused-for-review / under-leadership-review / terminated.
  * `safety_status`      — normal / escalated / resolved. Only a safety_concern moves this.
  * `leadership_status`  — none / under_review / decided.

The exact transitions are the state machine in spec section 25, reproduced at each
function below rather than left to be inferred from the code.

**AI assists, humans decide** (spec sections 31-37): `_raise_ai_finding_if_signal` is the
one place this module lets an algorithm write anything, and what it writes is a *finding*
— `ai_findings.human_decision` stays NULL until `review` records a named person's
disposition of it. Nothing here lets an AI finding change `operational_status`,
`safety_status` or `leadership_status` on its own; every transition above requires an
`actor` and, for a leadership decision, a mandatory `reason`. The discipline is
enforced, not merely described: the AI finding *write* itself appends an audit row
(attributed to the human whose action triggered it, and labelled AI-generated with its
engine version), `review` appends a second audit row for the human disposition, and
`require_human_review` is the gate any future code must pass before acting on a finding
— an unreviewed finding raises, it does not default to accepted.

**State guards, and where the late facts live.** A new escalation can only be raised
against an operationally `active` trial: a paused, under-leadership-review or
terminated trial is already inside the workflow, and a second escalation would be a
second pause on the same trial — the state machine of spec section 25 has no place
for that, so `raise_escalation` refuses it. `submit_response`, `review` and `decide`
refuse to act on a `terminated` trial at all. And a statutory clock that lapses
without a response is a *fact that survives*: the response is stamped with the time it
actually arrived, the lateness is derivable from `responded_at > deadline`, and both
`clock_progress` and the audit rows say so explicitly — a late Company response is
never written up as an on-time one.

Every write in this module opens the audit-append lock, makes its changes, and appends
its audit row in one transaction. The route layer supplies the actor's role and opaque
session reference so the audit row captures the authorized human action (spec section 30).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from . import signals
from .audit import record as audit_record
from .config import settings
from .db import Connection, begin_audit_append
from .models import (
    AIFindingKind,
    EscalationRaisedByRole,
    EscalationStatus,
    EscalationType,
    LeadershipDecisionType,
    OperationalStatus,
    utcnow,
)
from .pv import parse_timestamp

#: Which raiser role may open which escalation type. Enforced here as well as by the
#: route layer's `require_role`, so a future caller of this module cannot bypass it by
#: skipping the HTTP layer.
_ALLOWED_TYPE_FOR_ROLE = {
    EscalationRaisedByRole.INVESTIGATOR: EscalationType.PROTOCOL_DEVIATION,
    EscalationRaisedByRole.SAFETY_OFFICER: EscalationType.SAFETY_CONCERN,
}

#: engine_version stamped on every finding this module writes. Bumped by hand when the
#: detection logic underneath changes meaning, so a reviewer can tell whether a stale
#: finding was produced by the rule they are currently reading.
AI_ENGINE_VERSION = "prr-screen-1.0"


# --------------------------------------------------------------------------- helpers


def _trial(conn: Connection, trial_id: str):
    row = conn.execute("SELECT * FROM trials WHERE id = ?", (trial_id,)).fetchone()
    if row is None:
        raise ValueError(f"No trial {trial_id!r}")
    return row


def _set_trial_status(
    conn: Connection,
    trial_id: str,
    *,
    operational_status: str | None = None,
    safety_status: str | None = None,
    leadership_status: str | None = None,
) -> None:
    """Update only the governance dimensions named. `status` (lifecycle) is never here."""
    sets, params = [], []
    if operational_status is not None:
        sets.append("operational_status = ?")
        params.append(operational_status)
    if safety_status is not None:
        sets.append("safety_status = ?")
        params.append(safety_status)
    if leadership_status is not None:
        sets.append("leadership_status = ?")
        params.append(leadership_status)
    if not sets:
        return
    params.append(trial_id)
    conn.execute(f"UPDATE trials SET {', '.join(sets)} WHERE id = ?", params)


def _paused_operational_status(escalation_type: str) -> str:
    return (
        "paused_protocol_review"
        if escalation_type == EscalationType.PROTOCOL_DEVIATION.value
        else "paused_safety_review"
    )


# ---------------------------------------------------------------------------- reading


def get(conn: Connection, escalation_id: str) -> dict[str, Any] | None:
    """The Trial Review Package for one escalation (spec section 20): the escalation
    itself, the statutory clock if any, every corrective action and leadership decision,
    and any AI finding raised against it — everything Leadership's review screen needs,
    assembled in one place so it cannot show a decision from one row and evidence from
    a different one."""
    escalation = conn.execute(
        "SELECT * FROM escalations WHERE id = ?", (escalation_id,)
    ).fetchone()
    if escalation is None:
        return None
    trial = conn.execute(
        "SELECT * FROM trials WHERE id = ?", (escalation["trial_id"],)
    ).fetchone()
    clock = conn.execute(
        "SELECT * FROM statutory_clocks WHERE escalation_id = ? ORDER BY started_at DESC LIMIT 1",
        (escalation_id,),
    ).fetchone()
    corrective_actions = conn.execute(
        "SELECT * FROM corrective_actions WHERE escalation_id = ? ORDER BY submitted_at DESC",
        (escalation_id,),
    ).fetchall()
    decisions = conn.execute(
        "SELECT * FROM leadership_decisions WHERE escalation_id = ? ORDER BY decided_at DESC",
        (escalation_id,),
    ).fetchall()
    ai_findings = conn.execute(
        "SELECT * FROM ai_findings WHERE subject_type = 'escalation' AND subject_id = ? "
        "ORDER BY created_at DESC",
        (escalation_id,),
    ).fetchall()
    return {
        "escalation": escalation,
        "trial": trial,
        "clock": clock,
        "corrective_actions": corrective_actions,
        "decisions": decisions,
        "ai_findings": ai_findings,
    }


def clock_progress(clock, now=None) -> dict[str, Any]:
    """Percentage elapsed and hours remaining for a statutory clock — spec section 44's
    progress bar. Returns zeros/None for a protocol-deviation escalation, which carries
    no clock (spec section 14: only a safety concern starts one).

    `overdue` and `late` are different facts and both are preserved:

      * `overdue` — the deadline has passed and *no* response exists yet: an open breach.
      * `late`    — a response exists, but it arrived after the deadline: a closed
                    breach. Without this field a late response would render exactly
                    like an on-time one (`responded: true, overdue: false`), and the
                    fact that the statutory period was not met would be gone for good —
                    which is precisely what a regulatory clock is supposed to remember.
    """
    if clock is None:
        return {"applicable": False, "pct": 0, "hours_left": None, "overdue": False,
                "responded": False, "late": False}
    reference = now or utcnow()
    started = parse_timestamp(clock["started_at"])
    deadline = parse_timestamp(clock["deadline"])
    if started is None or deadline is None:
        return {"applicable": True, "pct": 0, "hours_left": None, "overdue": True,
                "responded": clock["responded_at"] is not None, "late": False}
    total = (deadline - started).total_seconds()
    elapsed = (reference - started).total_seconds()
    pct = 0 if total <= 0 else max(0, min(100, round(100 * elapsed / total)))
    hours_left = round((deadline - reference).total_seconds() / 3600, 1)
    responded_at = parse_timestamp(clock["responded_at"]) if clock["responded_at"] else None
    return {
        "applicable": True,
        "pct": pct,
        "hours_left": hours_left,
        "overdue": clock["responded_at"] is None and hours_left < 0,
        "responded": clock["responded_at"] is not None,
        "late": responded_at is not None and responded_at > deadline,
    }


def list_escalations(
    conn: Connection, *, status: str | None = None, trial_id: str | None = None
) -> list:
    """The inbox (spec section 19), most severe and most urgent first."""
    where, params = [], []
    if status:
        where.append("status = ?")
        params.append(status)
    if trial_id:
        where.append("trial_id = ?")
        params.append(trial_id)
    clause = f" WHERE {' AND '.join(where)}" if where else ""
    order = (
        "CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
        "WHEN 'medium' THEN 2 ELSE 3 END, created_at DESC"
    )
    return conn.execute(
        f"SELECT * FROM escalations{clause} ORDER BY {order}", params
    ).fetchall()


# ---------------------------------------------------------------------------- raising


def _raise_ai_finding_if_signal(
    conn: Connection, *, trial_id: str, escalation_id: str, actor_note: str
) -> None:
    """Attach a PRR-signal finding to a new safety-concern escalation, if one exists.

    Spec section 34 ("AI can ... calculate PRR ... highlight potential safety signals")
    and section 37 (every AI result carries engine version, confidence, and starts with
    `human_decision` NULL). This is the one place an algorithm's output is written; it
    changes nothing about the escalation or the trial by itself.
    """
    found = [s for s in signals.detect(conn) if s.trial_id == trial_id and s.flagged]
    if not found:
        return
    top = found[0]
    conn.execute(
        """INSERT INTO ai_findings
           (id, kind, subject_type, subject_id, engine_version, input_summary, finding,
            explanation, confidence, recommended_action, created_at,
            human_reviewer, human_decision, review_timestamp)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL)""",
        (
            str(uuid.uuid4()), AIFindingKind.PRR_SIGNAL.value, "escalation", escalation_id,
            AI_ENGINE_VERSION,
            f"{top.cases} coded events of '{top.coded_term}' on {trial_id}, "
            f"against {top.other_cases} elsewhere in the portfolio.",
            f"Proportional reporting ratio "
            f"{'undefined (term unseen elsewhere)' if top.prr is None else f'{top.prr:.2f}'} "
            f"for '{top.coded_term}' — {top.cases} cases, above the screening criterion "
            f"(PRR >= {signals.PRR_THRESHOLD}, n >= {signals.MIN_CASES}).",
            "A disproportionality screen is a triage statistic, not a causal finding. "
            f"Raised alongside {actor_note} for the reviewer to weigh, not to act on alone.",
            None,
            "Safety Officer to confirm coding and review against the escalation evidence "
            "before treating this as part of the safety concern.",
            utcnow().isoformat(),
        ),
    )


def raise_escalation(
    conn: Connection,
    *,
    trial_id: str,
    raised_by_role: str,
    escalation_type: str,
    severity: str,
    reason: str,
    actor: str,
    actor_role: str,
    session_ref: str | None = None,
    evidence: dict[str, Any] | None = None,
    recommended_action: str | None = None,
) -> dict[str, Any]:
    """Open an escalation. Pauses the trial and, for a safety concern, starts the
    statutory clock (spec sections 8, 12-14, 25).

    State transition on raise:
        operational_status -> paused_protocol_review | paused_safety_review
        safety_status      -> escalated   (safety_concern only)
    """
    role = EscalationRaisedByRole(raised_by_role)
    etype = EscalationType(escalation_type)
    expected_type = _ALLOWED_TYPE_FOR_ROLE[role]
    if etype is not expected_type:
        raise ValueError(
            f"{role.value} may raise {expected_type.value}, not {etype.value} "
            "(spec section 23: investigator -> protocol_deviation, safety officer -> safety_concern)"
        )
    if not reason.strip():
        raise ValueError("An escalation must state a reason.")

    _trial(conn, trial_id)  # 404s upstream if missing
    now = utcnow()
    escalation_id = f"ESC-{uuid.uuid4().hex[:8].upper()}"

    deadline = None
    if etype is EscalationType.SAFETY_CONCERN:
        deadline = now + timedelta(hours=settings.statutory_clock_hours)

    begin_audit_append(conn)
    row = {
        "id": escalation_id,
        "trial_id": trial_id,
        "raised_by": actor,
        "raised_by_role": role.value,
        "escalation_type": etype.value,
        "severity": severity,
        "reason": reason.strip(),
        "evidence_json": __import__("json").dumps(evidence or {}, default=str),
        "recommended_action": recommended_action,
        "created_at": now.isoformat(),
        "deadline": deadline.isoformat() if deadline else None,
        "status": EscalationStatus.OPEN.value,
    }
    conn.execute(
        """INSERT INTO escalations
           (id, trial_id, raised_by, raised_by_role, escalation_type, severity, reason,
            evidence_json, recommended_action, created_at, deadline, status)
           VALUES (:id,:trial_id,:raised_by,:raised_by_role,:escalation_type,:severity,
                   :reason,:evidence_json,:recommended_action,:created_at,:deadline,:status)""",
        row,
    )

    if deadline is not None:
        conn.execute(
            """INSERT INTO statutory_clocks
               (id, escalation_id, trial_id, started_at, deadline, period_hours, responded_at)
               VALUES (?,?,?,?,?,?,NULL)""",
            (
                str(uuid.uuid4()), escalation_id, trial_id, now.isoformat(),
                deadline.isoformat(), settings.statutory_clock_hours,
            ),
        )

    _set_trial_status(
        conn, trial_id,
        operational_status=_paused_operational_status(etype.value),
        safety_status="escalated" if etype is EscalationType.SAFETY_CONCERN else None,
    )

    if etype is EscalationType.SAFETY_CONCERN:
        _raise_ai_finding_if_signal(
            conn, trial_id=trial_id, escalation_id=escalation_id,
            actor_note=f"the safety concern {actor} raised",
        )

    event = audit_record(
        conn, actor=actor, role=actor_role, session_ref=session_ref, action="create", resource_type="escalation",
        resource_id=escalation_id, after=row, reason=reason.strip(), commit=False,
    )
    conn.commit()
    return {"escalation": row, "audit": event}


# --------------------------------------------------------------------------- response


_RESPONSE_FIELDS = (
    "explanation", "investigation_findings", "root_cause", "immediate_action",
    "corrective_action", "preventive_action", "participant_impact",
    "expected_resolution", "responsible_person",
)


def submit_response(
    conn: Connection,
    *,
    escalation_id: str,
    actor: str,
    actor_role: str,
    session_ref: str | None = None,
    supporting_documents: list[str] | None = None,
    **fields: str,
) -> dict[str, Any]:
    """The Company's structured response (spec section 15). Every field the spec names
    is a required column, not an optional paragraph — a response missing one is rejected
    rather than accepted as free text standing in for the rest.

    State transition: escalation.status -> company_responded. If a statutory clock is
    running, its `responded_at` is stamped now — a fact this system can state honestly:
    a response was submitted at this instant, not that it was reviewed or accepted yet.
    """
    package = get(conn, escalation_id)
    if package is None:
        raise ValueError(f"No escalation {escalation_id!r}")
    escalation = package["escalation"]
    if escalation["status"] not in (EscalationStatus.OPEN.value,):
        raise ValueError(
            f"Escalation {escalation_id} is {escalation['status']!r}; "
            "a response can only be submitted while it is open."
        )
    missing = [f for f in _RESPONSE_FIELDS if not fields.get(f, "").strip()]
    if missing:
        raise ValueError(f"Response is missing required field(s): {', '.join(missing)}")

    now = utcnow()
    row = {
        "id": str(uuid.uuid4()),
        "trial_id": escalation["trial_id"],
        "escalation_id": escalation_id,
        **{f: fields[f].strip() for f in _RESPONSE_FIELDS},
        "supporting_documents_json": __import__("json").dumps(supporting_documents or []),
        "submitted_by": actor,
        "submitted_at": now.isoformat(),
    }

    begin_audit_append(conn)
    conn.execute(
        """INSERT INTO corrective_actions
           (id, trial_id, escalation_id, explanation, investigation_findings, root_cause,
            immediate_action, corrective_action, preventive_action,
            supporting_documents_json, participant_impact, expected_resolution,
            responsible_person, submitted_by, submitted_at)
           VALUES (:id,:trial_id,:escalation_id,:explanation,:investigation_findings,
                   :root_cause,:immediate_action,:corrective_action,:preventive_action,
                   :supporting_documents_json,:participant_impact,:expected_resolution,
                   :responsible_person,:submitted_by,:submitted_at)""",
        row,
    )
    conn.execute(
        "UPDATE escalations SET status = ? WHERE id = ?",
        (EscalationStatus.COMPANY_RESPONDED.value, escalation_id),
    )
    if package["clock"] is not None:
        conn.execute(
            "UPDATE statutory_clocks SET responded_at = ? WHERE id = ?",
            (now.isoformat(), package["clock"]["id"]),
        )

    event = audit_record(
        conn, actor=actor, role=actor_role, session_ref=session_ref, action="create", resource_type="corrective_action",
        resource_id=row["id"],
        after={k: v for k, v in row.items() if k != "supporting_documents_json"},
        reason="Company structured response to escalation " + escalation_id,
        commit=False,
    )
    conn.commit()
    return {"corrective_action": row, "audit": event}


# ----------------------------------------------------------------------------- review


def review(
    conn: Connection,
    *,
    escalation_id: str,
    outcome: str,  # "resolve" | "escalate"
    reason: str,
    actor: str,
    actor_role: str,
    session_ref: str | None = None,
    ai_finding_decision: str | None = None,
) -> dict[str, Any]:
    """The Investigator's or Safety Officer's review of the Company's response (spec
    sections 8, 13, 16). Two outcomes only, matching the spec's two named paths:

        resolve  -> Path A: satisfactory. operational_status -> active,
                    safety_status -> resolved (safety_concern only), escalation closed.
        escalate -> Path B: unsatisfactory/unresolved/late.
                    operational_status -> under_leadership_review,
                    leadership_status -> under_review, escalation -> under_leadership_review.

    If an unreviewed AI finding is attached to this escalation and `ai_finding_decision`
    is given, it is marked reviewed by this same actor in the same transaction — closing
    the AI Finding -> Human Review -> Human Decision -> Audit Log chain spec section 37
    describes, instead of leaving the finding to be reviewed nowhere.
    """
    if outcome not in ("resolve", "escalate"):
        raise ValueError("outcome must be 'resolve' or 'escalate'")
    if not reason.strip():
        raise ValueError("A review decision must state a reason.")

    package = get(conn, escalation_id)
    if package is None:
        raise ValueError(f"No escalation {escalation_id!r}")
    escalation = package["escalation"]
    if escalation["status"] != EscalationStatus.COMPANY_RESPONDED.value:
        raise ValueError(
            f"Escalation {escalation_id} is {escalation['status']!r}; "
            "it can only be reviewed after the Company has responded."
        )
    trial_id = escalation["trial_id"]
    is_safety = escalation["escalation_type"] == EscalationType.SAFETY_CONCERN.value
    now = utcnow()

    begin_audit_append(conn)
    if outcome == "resolve":
        conn.execute(
            "UPDATE escalations SET status = ?, resolution_timestamp = ? WHERE id = ?",
            (EscalationStatus.RESOLVED.value, now.isoformat(), escalation_id),
        )
        _set_trial_status(
            conn, trial_id, operational_status="active",
            safety_status="resolved" if is_safety else None,
        )
    else:
        conn.execute(
            "UPDATE escalations SET status = ? WHERE id = ?",
            (EscalationStatus.UNDER_LEADERSHIP_REVIEW.value, escalation_id),
        )
        _set_trial_status(
            conn, trial_id, operational_status="under_leadership_review",
            leadership_status="under_review",
        )

    if package["clock"] is not None and package["clock"]["responded_at"] is None:
        # A review can happen after the clock lapsed with no response; stamping it now
        # records that the gap existed rather than silently closing over it.
        conn.execute(
            "UPDATE statutory_clocks SET responded_at = ? WHERE id = ?",
            (now.isoformat(), package["clock"]["id"]),
        )

    reviewed_finding = None
    unreviewed = [f for f in package["ai_findings"] if f["human_decision"] is None]
    if ai_finding_decision and unreviewed:
        finding = unreviewed[0]
        conn.execute(
            "UPDATE ai_findings SET human_reviewer = ?, human_decision = ?, "
            "review_timestamp = ? WHERE id = ?",
            (actor, ai_finding_decision.strip(), now.isoformat(), finding["id"]),
        )
        reviewed_finding = finding["id"]

    event = audit_record(
        conn, actor=actor, role=actor_role, session_ref=session_ref, action="update", resource_type="escalation",
        resource_id=escalation_id,
        before={"status": escalation["status"]},
        after={"status": "resolved" if outcome == "resolve" else "under_leadership_review",
               "reviewed_ai_finding": reviewed_finding},
        reason=reason.strip(), commit=False,
    )
    conn.commit()
    return {"outcome": outcome, "audit": event}


# -------------------------------------------------------------------------- decision


#: Decisions that close the escalation outright, versus ones that keep it open pending
#: further work. Spec section 22: conditions are tracked, which implies the matter is
#: not necessarily finished the moment Leadership speaks.
_CLOSING_DECISIONS = (
    LeadershipDecisionType.CONTINUE,
    LeadershipDecisionType.RESUME,
    LeadershipDecisionType.REJECT_TERMINATE,
)


def decide(
    conn: Connection,
    *,
    escalation_id: str,
    decision: str,
    reason: str,
    actor: str,
    actor_role: str,
    session_ref: str | None = None,
    conditions: list[str] | None = None,
) -> dict[str, Any]:
    """Leadership's final governance decision on an escalation (spec sections 17, 21, 22).

    A reason is mandatory — not by convention, by this function refusing a blank one —
    because "AI can detect and recommend, authorized humans decide" is meaningless if
    the decision carries no accountability for *why*. Conditions are stored individually
    (spec section 22's checklist), each starting unsatisfied.

    State transition, keyed off `decision`:
        CONTINUE / RESUME        -> operational_status active,   leadership_status decided,  escalation closed
        REJECT_TERMINATE         -> operational_status terminated, leadership_status decided, escalation closed
        PAUSE                    -> operational_status paused_*,  leadership_status decided,  escalation stays under_leadership_review
        REQUEST_FURTHER_REVIEW   -> operational_status unchanged, leadership_status stays under_review, escalation stays under_leadership_review
    """
    decision_type = LeadershipDecisionType(decision)
    if not reason.strip():
        raise ValueError("A leadership decision must state a reason.")

    package = get(conn, escalation_id)
    if package is None:
        raise ValueError(f"No escalation {escalation_id!r}")
    escalation = package["escalation"]
    if escalation["status"] != EscalationStatus.UNDER_LEADERSHIP_REVIEW.value:
        raise ValueError(
            f"Escalation {escalation_id} is {escalation['status']!r}; "
            "a leadership decision can only be recorded once it is under leadership review."
        )
    trial_id = escalation["trial_id"]
    now = utcnow()

    conditions_rows = [{"text": c.strip(), "satisfied": False} for c in (conditions or []) if c.strip()]
    decision_id = str(uuid.uuid4())
    row = {
        "id": decision_id,
        "escalation_id": escalation_id,
        "trial_id": trial_id,
        "decision": decision_type.value,
        "reason": reason.strip(),
        "conditions_json": __import__("json").dumps(conditions_rows),
        "decided_by": actor,
        "decided_at": now.isoformat(),
    }

    begin_audit_append(conn)
    conn.execute(
        """INSERT INTO leadership_decisions
           (id, escalation_id, trial_id, decision, reason, conditions_json, decided_by, decided_at)
           VALUES (:id,:escalation_id,:trial_id,:decision,:reason,:conditions_json,:decided_by,:decided_at)""",
        row,
    )

    closes = decision_type in _CLOSING_DECISIONS
    conn.execute(
        """UPDATE escalations
              SET leadership_decision = ?, decision_reason = ?, decision_timestamp = ?,
                  status = ?, resolution_timestamp = COALESCE(resolution_timestamp, ?)
            WHERE id = ?""",
        (
            decision_type.value, reason.strip(), now.isoformat(),
            EscalationStatus.CLOSED.value if closes else EscalationStatus.UNDER_LEADERSHIP_REVIEW.value,
            now.isoformat() if closes else None,
            escalation_id,
        ),
    )

    if decision_type in (LeadershipDecisionType.CONTINUE, LeadershipDecisionType.RESUME):
        _set_trial_status(conn, trial_id, operational_status="active", leadership_status="decided")
    elif decision_type is LeadershipDecisionType.REJECT_TERMINATE:
        _set_trial_status(conn, trial_id, operational_status="terminated", leadership_status="decided")
    elif decision_type is LeadershipDecisionType.PAUSE:
        _set_trial_status(
            conn, trial_id,
            operational_status=_paused_operational_status(escalation["escalation_type"]),
            leadership_status="decided",
        )
    else:  # REQUEST_FURTHER_REVIEW — nothing resolved yet; leadership_status stays under_review
        pass

    event = audit_record(
        conn, actor=actor, role=actor_role, session_ref=session_ref, action="create", resource_type="leadership_decision",
        resource_id=decision_id, after=row, reason=reason.strip(), commit=False,
    )
    conn.commit()
    return {"decision": row, "audit": event}
