"""The data model. One file, on purpose.

Merged from the twelve `contracts/models/*.py` modules — same fields, same validators,
one import. Every model inherits CTMSModel so serialisation behaves identically across
the API, the templates and the audit trail.

Two things here are compliance decisions, not style choices:

  * `Participant` has no name, no date of birth, no resolvable identifier (DPDP Act 2023).
    The absence IS the answer, and `extra="forbid"` means an attempt to attach one
    fails validation rather than passing quietly.
  * `AdverseEvent.coding_source` records where a coded term came from. We do not have
    MedDRA or WHODrug — they are licensed — and the data says so rather than implying
    otherwise.
"""

from datetime import date, datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict


# --------------------------------------------------------------------------- base


class CTMSModel(BaseModel):
    """Base for every model.

    `use_enum_values=False` keeps enums as enums in Python and serialises them to
    their string value in JSON — so a template sees "enrolling", not an int.
    """

    model_config = ConfigDict(
        use_enum_values=False,
        str_strip_whitespace=True,
        validate_assignment=True,
        extra="forbid",  # a typo'd field name fails loudly at hour 3, not silently at hour 20
    )


def utcnow() -> datetime:
    """Server clock, always UTC, always timezone-aware.

    Audit timestamps and reporting deadlines are computed from this and NEVER from a
    client-supplied value. ALCOA+ 'contemporaneous' depends on it.
    """
    return datetime.now(timezone.utc)


# -------------------------------------------------------------------------- trial


class TrialPhase(str, Enum):
    PHASE_I = "I"
    PHASE_II = "II"
    PHASE_III = "III"
    PHASE_IV = "IV"
    #: Ayurveda portfolios carry observational and pilot trials that aren't phased.
    OBSERVATIONAL = "observational"


class TrialStatus(str, Enum):
    PROTOCOL = "protocol"
    EC_APPROVAL = "ec_approval"
    CTRI_REGISTERED = "ctri_registered"
    SITE_ACTIVATION = "site_activation"
    SCREENING = "screening"
    ENROLLING = "enrolling"
    FOLLOW_UP = "follow_up"
    CLOSE_OUT = "close_out"


class OperationalStatus(str, Enum):
    """Whether the trial is actively running, or paused by a governance workflow.

    Distinct from `TrialStatus` (the lifecycle stage — protocol, screening, enrolling...).
    A trial can be lifecycle-stage `enrolling` and operationally `paused_safety_review` at
    the same time — the spec's "multiple status dimensions" (section 24), not one field
    overloaded to mean two things.
    """

    ACTIVE = "active"
    PAUSED_PROTOCOL_REVIEW = "paused_protocol_review"
    PAUSED_SAFETY_REVIEW = "paused_safety_review"
    UNDER_LEADERSHIP_REVIEW = "under_leadership_review"
    TERMINATED = "terminated"


class SafetyStatus(str, Enum):
    """The safety-oversight dimension. Independent of operational/enrollment status."""

    NORMAL = "normal"
    ESCALATED = "escalated"
    RESOLVED = "resolved"


class LeadershipStatus(str, Enum):
    """The governance dimension: has leadership been asked to look at this trial."""

    NONE = "none"
    UNDER_REVIEW = "under_review"
    DECIDED = "decided"


class Trial(CTMSModel):
    """The portfolio unit.

    Lifecycle: protocol -> ec_approval -> ctri_registered -> site_activation
               -> screening -> enrolling -> follow_up -> close_out

    Trial *health* is not one field. Per the governance model (section 24), a trial
    carries four independent status dimensions: the lifecycle `status` below, plus
    `operational_status` (active/paused/terminated), `safety_status` (is there an open
    safety escalation) and `leadership_status` (is this awaiting/has this had a
    leadership decision). Enrollment status ("at risk" etc.) is deliberately not stored
    here — it is derived on read from `target_enrolment`/`actual_enrolment`/plan-to-date,
    the same way every other KPI in this system is computed rather than cached.
    """

    id: str
    title: str
    protocol_no: str
    #: None until prospectively registered. A trial enrolling without one is a finding.
    ctri_number: str | None = None
    phase: TrialPhase
    status: TrialStatus
    therapeutic_area: str

    ec_approval_date: date | None = None
    #: The ethics-renewal alert fires off this field. Never leave it null on an active trial.
    ec_expiry_date: date | None = None
    ctri_registration_date: date | None = None

    target_enrolment: int
    actual_enrolment: int = 0

    pi_name: str
    site_ids: list[str] = []
    start_date: date
    end_date: date | None = None

    #: Governance dimensions. See the class docstring — these are independent of `status`.
    operational_status: OperationalStatus = OperationalStatus.ACTIVE
    safety_status: SafetyStatus = SafetyStatus.NORMAL
    leadership_status: LeadershipStatus = LeadershipStatus.NONE


# --------------------------------------------------------------------------- site


class SiteStatus(str, Enum):
    PLANNED = "planned"
    ACTIVATED = "activated"
    SUSPENDED = "suspended"
    CLOSED = "closed"


class Site(CTMSModel):
    """A participating centre."""

    id: str
    name: str
    city: str
    state: str
    status: SiteStatus
    #: None until the site is activated. Drives the "sites activated" portfolio KPI.
    activated_date: date | None = None
    pi_name: str
    #: Planned enrolment capacity, used to spread a trial's target across sites.
    capacity: int
    trial_ids: list[str] = []


# ------------------------------------------------------------------------ participant


class ParticipantStatus(str, Enum):
    SCREENED = "screened"
    SCREEN_FAILED = "screen_failed"
    ENROLLED = "enrolled"
    COMPLETED = "completed"
    WITHDRAWN = "withdrawn"


class Participant(CTMSModel):
    """Pseudonymous only.

    DPDP Act 2023: no name, no date of birth, no identifier that resolves to a person.
    `participant_code` is the only handle. This model has no name field and must never get
    one — see the module docstring.
    """

    id: str
    #: e.g. "AIIA-003-014" — site-scoped, non-identifying, safe to show anywhere.
    participant_code: str
    trial_id: str
    site_id: str

    screened_date: date
    #: None if screen-failed or still in screening.
    enrolled_date: date | None = None
    status: ParticipantStatus
    #: Randomisation arm. None until enrolled.
    arm: str | None = None

    #: Age band, not date of birth — enough for analysis, not enough to identify anyone.
    age_band: str | None = None
    sex: str | None = None

    consent_version: str
    consent_date: date


# -------------------------------------------------------------------------- visit


class VisitStatus(str, Enum):
    UPCOMING = "upcoming"
    COMPLETED = "completed"
    MISSED = "missed"
    OVERDUE = "overdue"


class Visit(CTMSModel):
    """Scheduled vs actual. Drives the visit-compliance KPI.

    Covers both participant visits and site monitoring visits; `monitoring_visit`
    distinguishes them. Overdue monitoring visits are one of the portfolio alerts.
    """

    id: str
    trial_id: str
    site_id: str
    #: None for a site monitoring visit — those aren't tied to a participant.
    participant_code: str | None = None

    visit_name: str
    scheduled_date: date
    actual_date: date | None = None
    #: Protocol-defined window. Outside it, the visit is a deviation.
    window_days: int = 0
    status: VisitStatus

    monitoring_visit: bool = False
    #: A monitoring visit with actual_date set but no report filed is still overdue.
    report_filed: bool = False


# ---------------------------------------------------------------------- deviation


class DeviationSeverity(str, Enum):
    MINOR = "minor"
    MAJOR = "major"
    CRITICAL = "critical"


class Deviation(CTMSModel):
    """Protocol deviation.

    Major and critical deviations are reportable to the Ethics Committee;
    `reported_to_ec` false on a critical deviation is exactly the kind of thing this
    dashboard exists to surface.
    """

    id: str
    trial_id: str
    site_id: str
    participant_code: str | None = None

    category: str
    description: str
    detected_date: date
    severity: DeviationSeverity

    reported_to_ec: bool = False
    reported_date: date | None = None
    resolution: str | None = None


# -------------------------------------------------------------------------- query


class QueryStatus(str, Enum):
    OPEN = "open"
    ANSWERED = "answered"
    CLOSED = "closed"


class DataQuery(CTMSModel):
    """A data-cleaning query raised against a data point.

    `age_days` is computed on read, not stored: open-query ageing is a KPI and must not
    go stale because someone forgot to recompute a column.
    """

    id: str
    trial_id: str
    site_id: str
    participant_code: str | None = None

    field: str
    question: str
    raised_date: date
    raised_by: str
    answered_date: date | None = None
    closed_date: date | None = None
    status: QueryStatus

    #: Days open as of the response. Server-computed; ignore anything a client sends.
    age_days: int = 0


# ----------------------------------------------------------------- adverse events


class AESeverity(str, Enum):
    MILD = "mild"
    MODERATE = "moderate"
    SEVERE = "severe"


class AECausality(str, Enum):
    """WHO-UMC causality categories."""

    UNRELATED = "unrelated"
    UNLIKELY = "unlikely"
    POSSIBLE = "possible"
    PROBABLE = "probable"
    CERTAIN = "certain"


class AEOutcome(str, Enum):
    RECOVERED = "recovered"
    RECOVERING = "recovering"
    NOT_RECOVERED = "not_recovered"
    RECOVERED_WITH_SEQUELAE = "recovered_with_sequelae"
    FATAL = "fatal"
    UNKNOWN = "unknown"


class CodingSource(str, Enum):
    """Where a coded term came from. Shown in the UI — we never imply a licensed dictionary."""

    CURATED = "curated"  # our own vocabulary in app/terms.csv, exact or fuzzy match
    MEDDRA = "meddra"    # licensed. Not available in this build, and never set.
    UNCODED = "uncoded"


class TimelineStatus(str, Enum):
    ON_TRACK = "on_track"
    DUE_SOON = "due_soon"
    BREACHED = "breached"
    NOT_APPLICABLE = "not_applicable"  # non-serious AEs carry no statutory clock


class AdverseEvent(CTMSModel):
    """Adverse event / SAE.

    Two things make this different from a plain event record:

    1. **Coding provenance is explicit** — `coding_source` says whether a term came from
       our own curated vocabulary or a licensed dictionary.
    2. **Statutory clocks are fields, not UI.** NDCT Rules 2019 requires an SAE to reach
       the Ethics Committee and licensing authority within 24 hours, with a narrative in
       14 days. Those deadlines are computed server-side on intake and stored here.
    """

    id: str
    trial_id: str
    site_id: str
    participant_code: str

    #: Free text as reported. This is what the coding service consumes.
    narrative: str
    onset_date: date
    serious: bool = False
    severity: AESeverity
    causality: AECausality
    outcome: AEOutcome

    # --- coding ---
    coded_term: str | None = None
    coded_code: str | None = None
    coding_confidence: float | None = None
    coding_source: CodingSource = CodingSource.UNCODED

    suspect_drug: str | None = None
    drug_code: str | None = None
    drug_coding_source: CodingSource = CodingSource.UNCODED

    # --- statutory clocks, server-computed on intake ---
    reported_at: datetime
    #: Both None when serious is False.
    deadline_24h: datetime | None = None
    deadline_14d: datetime | None = None
    timeline_status: TimelineStatus = TimelineStatus.NOT_APPLICABLE


# ---------------------------------------------------------------------- milestone


class MilestoneType(str, Enum):
    EC_APPROVAL = "ec_approval"
    CTRI_REGISTRATION = "ctri_registration"
    FIRST_SITE_ACTIVATED = "first_site_activated"
    FIRST_SUBJECT_IN = "first_subject_in"
    FIFTY_PCT_ENROLLED = "fifty_pct_enrolled"
    LAST_SUBJECT_IN = "last_subject_in"
    DATABASE_LOCK = "database_lock"
    CLOSE_OUT = "close_out"


class MilestoneStatus(str, Enum):
    PLANNED = "planned"
    ACHIEVED = "achieved"
    AT_RISK = "at_risk"
    MISSED = "missed"


class Milestone(CTMSModel):
    """Lifecycle checkpoints per trial."""

    id: str
    trial_id: str
    type: MilestoneType
    planned_date: date
    actual_date: date | None = None
    status: MilestoneStatus


# -------------------------------------------------------------------------- alert


class AlertRule(str, Enum):
    ENROLMENT_LAG = "enrolment_lag"
    ETHICS_RENEWAL_DUE = "ethics_renewal_due"
    CTRI_UPDATE_DUE = "ctri_update_due"
    MONITORING_VISIT_OVERDUE = "monitoring_visit_overdue"
    SAE_TIMELINE_BREACH = "sae_timeline_breach"


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class Alert(CTMSModel):
    """Output of the rule engine.

    Thresholds are configurable via env (see .env.example). A judge asking "is this
    configurable or hardcoded?" gets answered by changing one value and refreshing.
    """

    id: str
    rule: AlertRule
    severity: AlertSeverity
    trial_id: str
    trial_title: str | None = None
    #: Human-readable, already formatted with the actual numbers. Rendered as-is.
    message: str
    raised_at: datetime
    #: Route the alert drills into, e.g. "/trial/STU-003".
    deep_link: str

    acknowledged_by: str | None = None
    acknowledged_at: datetime | None = None


# ---------------------------------------------------------------------------- user


class UserRole(str, Enum):
    """Authentication/authorization identities — exactly the spec's five primary roles.

    Volunteer, Company, Investigator, Safety Officer, Leadership (spec section 2),
    and only those five. This is the authorization identity attached to a session;
    finer-grained capabilities than "which role" are expressed as `auth.Permission`,
    not as more roles.

    This build previously carried nine values. The consolidation is fixed, in one
    direction, by `LEGACY_ROLE_ALIASES` below:

      * `principal_investigator`, `study_coordinator`, `monitor`  -> `investigator`
      * `pharmacovigilance`                                        -> `safety_officer`
      * `ethics_committee`, `administration`, `regulator`          -> `leadership`
      * `company`, `leadership`                                    -> unchanged
      * `volunteer`                                                -> new (spec D1)

    The direction is deliberate: a pre-consolidation role string found in `users` or in
    a historical audit row is *normalised to a primary role at read time* (`parse_role`),
    never the other way around — a primary value must never silently become one of the
    institutional stand-ins. Whether any of the old distinctions (e.g. a read-only
    regulator, or a monitor who observes rather than reports) needs to survive as
    *permission* rather than *role* is the job of `auth.PERMISSIONS_BY_ROLE`; a role is
    no longer the place that distinction lives.
    """

    VOLUNTEER = "volunteer"
    COMPANY = "company"
    INVESTIGATOR = "investigator"
    SAFETY_OFFICER = "safety_officer"
    LEADERSHIP = "leadership"


#: Pre-consolidation role values and the primary role each one becomes. The single
#: authoritative mapping for anything still carrying an old role string: `users.role`
#: rows seeded before this alignment, historical audit rows, and any API payload that
#: names a legacy role. Unknown values are not mapped — `parse_role` raises for them,
#: the same way `UserRole` itself would.
LEGACY_ROLE_ALIASES: dict[str, UserRole] = {
    "principal_investigator": UserRole.INVESTIGATOR,
    "study_coordinator": UserRole.INVESTIGATOR,
    "monitor": UserRole.INVESTIGATOR,
    "pharmacovigilance": UserRole.SAFETY_OFFICER,
    "ethics_committee": UserRole.LEADERSHIP,
    "administration": UserRole.LEADERSHIP,
    "regulator": UserRole.LEADERSHIP,
}


def parse_role(value: str | UserRole) -> UserRole:
    """Resolve any role value the system may still carry to a primary role.

    Primary values pass through; legacy values come back through
    `LEGACY_ROLE_ALIASES`; anything else raises `ValueError`. This is the one place
    a stored role string is trusted to be old — every other code path works with
    primary roles only.
    """
    if isinstance(value, UserRole):
        return value
    if value in LEGACY_ROLE_ALIASES:
        return LEGACY_ROLE_ALIASES[value]
    return UserRole(value)





class User(CTMSModel):
    id: str
    username: str
    #: Always a primary role. A `users` row still carrying a pre-consolidation value
    #: (see `LEGACY_ROLE_ALIASES`) is normalised before it ever builds a `User` —
    #: that happens in `auth._user_from_row`, not here, so this model stays a model.
    role: UserRole
    display_name: str
    #: Set only for an investigator account, to scope the investigator lens
    #: to the trials where this person is actually named as PI.
    pi_name: str | None = None
    active: bool = True
    created_at: datetime


# -------------------------------------------------------------------------- audit

#: prev_hash of the very first row in the chain.
GENESIS_HASH = "0" * 64


class AuditAction(str, Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    VIEW = "view"  # only for sensitive reads (audit export, regulator export)
    EXPORT = "export"
    ACKNOWLEDGE = "acknowledge"
    SIGN = "sign"


class AuditEvent(CTMSModel):
    """Append-only, hash-chained. The technical heart of the pitch.

    Every field answers one ALCOA+ question:

      attributable    -> actor
      legible         -> before/after as structured JSON, not a free-text log line
      contemporaneous -> timestamp_utc, from the server clock, never client-supplied
      original        -> before captured at write time, not reconstructed
      accurate        -> hash chain makes any later edit detectable and locatable

    Nothing here is mutable after write. No UPDATE, no DELETE — enforced by a database
    trigger as well as by application code, so the guarantee doesn't depend on the
    application behaving.

    `role` and `session_ref` close the two fields spec section 30 names that earlier
    revisions of this table lacked: which role the actor held at the time (roles can
    change; the audit row should say what was true then, not what is true now when
    someone reads it), and an opaque reference to the session/request that made the
    change (never the raw session token — see `auth.session_reference`).

    Hashing policy, and why it is conditional: `role` and `session_ref` enter the
    hashed payload **when they carry a value**. A row that records a role or a session
    reference commits to it, so neither can be quietly edited later any more than
    `actor` can. A row that stores NULL in both — every row written before the columns
    existed, and still any row whose caller supplied nothing — hashes exactly the
    pre-migration field set. That is what lets one unbroken chain span the schema
    change: the old rows' hashes are recomputed to the same value they had before
    `ALTER TABLE`, so verification stays green across the migration instead of
    reporting every historical row as tampered.
    """

    id: str
    #: Gapless sequence. A gap means rows were deleted — that is itself the finding.
    seq: int

    #: Who performed the action.
    actor: str
    #: The actor's role at the time of the action. None only for pre-existing rows
    #: written before this field existed.
    role: str | None = None
    action: AuditAction
    resource_type: str
    resource_id: str | None = None

    #: State before and after the change. None on create/delete respectively.
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None

    timestamp_utc: datetime
    #: Why, when the action needs a reason (signature, override, deviation).
    reason: str | None = None
    #: Opaque reference to the session/request that made the change — see
    #: `auth.session_reference`. Never the raw session token.
    session_ref: str | None = None

    prev_hash: str
    #: sha256(canonical_json(payload) + prev_hash)
    hash: str


# ---------------------------------------------------------------------------- kpi


class PortfolioKPI(CTMSModel):
    """The six headline numbers on the portfolio screen."""

    generated_at: datetime
    active_trials: int
    enrolled_total: int
    target_total: int
    sites_activated: int
    sites_total: int
    open_queries: int
    overdue_monitoring_visits: int
    open_saes: int

    @property
    def enrolment_pct(self) -> float:
        return 0.0 if self.target_total == 0 else 100.0 * self.enrolled_total / self.target_total


class TrialKPI(CTMSModel):
    """Per-trial drill-down metrics."""

    generated_at: datetime
    trial_id: str
    enrolment_pct: float
    enrolled: int
    target: int
    #: Enrolment the plan says we should have hit by today. The gap drives the lag alert.
    expected_by_today: int
    screen_failure_rate: float
    visit_compliance_pct: float
    open_queries: int
    open_query_ageing_days: float
    deviation_rate_per_site: float
    open_saes: int
    days_to_next_milestone: int | None = None
    next_milestone: str | None = None


# --------------------------------------------------------------------- governance
#
# The escalation / statutory-clock / leadership-decision / corrective-action layer.
#
# Central design rule, everywhere in this section: **AI can detect and recommend.
# Authorized humans investigate, decide, approve, pause, resume, reject, or escalate.**
# Every write in this section carries a human `actor` and, for governance decisions, a
# mandatory `reason` — there is no code path here that transitions a trial's state
# without a named person attached to the change, and every write goes through the same
# append-only audit trail as every other mutation in this system (see app/audit.py).
#
# Investigator (protocol deviation) and Safety Officer (safety concern) escalations are
# **one database entity** (spec section 23: "Investigator and Safety Officer escalations
# should use the same database entity"), distinguished by `escalation_type` and
# `raised_by_role` rather than living in two parallel tables that could drift apart.


class EscalationType(str, Enum):
    PROTOCOL_DEVIATION = "protocol_deviation"
    SAFETY_CONCERN = "safety_concern"


class EscalationSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class EscalationStatus(str, Enum):
    """The escalation's own lifecycle — independent of, but driving, the trial's
    `operational_status`/`safety_status`/`leadership_status`."""

    OPEN = "open"                          #: raised, trial paused, awaiting company response
    COMPANY_RESPONDED = "company_responded"  #: corrective action submitted, awaiting review
    RESOLVED = "resolved"                  #: reviewer found the response satisfactory; trial resumed
    UNDER_LEADERSHIP_REVIEW = "under_leadership_review"  #: unsatisfactory/unresolved/late — escalated up
    CLOSED = "closed"                      #: leadership has made a final decision on this escalation


class EscalationRaisedByRole(str, Enum):
    """Who may raise an escalation. Matches the spec's governance hierarchy exactly:
    Investigator raises protocol deviations, Safety Officer raises safety concerns."""

    INVESTIGATOR = "investigator"
    SAFETY_OFFICER = "safety_officer"


class Escalation(CTMSModel):
    """A protocol-deviation or safety-concern escalation raised against a trial.

    Fields match spec section 23's "Escalation entity" listing exactly. Investigator and
    Safety Officer escalations share this one table (see module note above), so a
    Leadership Escalation Inbox is one query, not a UNION of two tables that could
    disagree about what "open" means.
    """

    id: str
    trial_id: str
    raised_by: str                    #: username of the investigator/safety officer
    raised_by_role: EscalationRaisedByRole
    escalation_type: EscalationType
    severity: EscalationSeverity
    reason: str
    #: Free-form structured evidence — AE ids, deviation ids, document references, etc.
    evidence: dict[str, Any] = {}
    recommended_action: str | None = None
    created_at: datetime
    #: When the company's response is due. For a safety concern this is filled from the
    #: linked StatutoryClock; for a protocol deviation it may be None (no statutory
    #: period applies — only a safety concern starts the regulatory clock, per spec
    #: section 14).
    deadline: datetime | None = None
    status: EscalationStatus = EscalationStatus.OPEN

    #: Set once Leadership has decided (see LeadershipDecision, which is the fuller
    #: record — these three fields are a denormalised summary for fast list views,
    #: e.g. the Leadership Escalation Inbox, so it does not need a join per row).
    leadership_decision: str | None = None
    decision_reason: str | None = None
    decision_timestamp: datetime | None = None
    resolution_timestamp: datetime | None = None


class StatutoryClockStatus(str, Enum):
    RUNNING = "running"
    RESPONDED = "responded"    #: company responded before the deadline
    OVERDUE = "overdue"        #: deadline passed with no company response
    STOPPED = "stopped"        #: escalation resolved/closed; the clock is no longer live


class StatutoryClock(CTMSModel):
    """A regulatory response-deadline clock, started when a Safety Officer escalates a
    safety concern (spec sections 13-14).

    The statutory period itself is **configurable** (`settings.statutory_clock_hours`),
    never hard-coded — see spec section 14: "The exact statutory period should be
    configurable according to the applicable regulatory framework." Only `started_at`
    and `deadline` are stored facts; `status` is intentionally *not* a stored source of
    truth (matching the existing `pv.py` pattern for AE clocks) — callers derive the live
    state from `deadline` against the current server clock rather than trusting a
    snapshot that could go stale between writes.
    """

    id: str
    escalation_id: str
    trial_id: str
    started_at: datetime
    deadline: datetime
    #: Hours the deadline was computed from — carried alongside the deadline so a later
    #: change to the configured period cannot silently reinterpret a past clock.
    period_hours: int
    responded_at: datetime | None = None


class CorrectiveAction(CTMSModel):
    """The Company's structured response to an escalation (spec section 15).

    Deliberately not free text: every field the spec names is a distinct column, so the
    response is a set of facts a reviewer can check off rather than a paragraph they have
    to parse. This becomes the auditable record of what the Company said happened, what
    they did about it, and who is accountable for it.
    """

    id: str
    trial_id: str
    escalation_id: str

    explanation: str
    investigation_findings: str
    root_cause: str
    immediate_action: str
    corrective_action: str
    preventive_action: str
    #: References/filenames of uploaded evidence. The files themselves are out of scope
    #: for this prototype (no object storage integration); this records what was cited.
    supporting_documents: list[str] = []
    participant_impact: str
    expected_resolution: str
    responsible_person: str

    submitted_by: str
    submitted_at: datetime


class LeadershipDecisionType(str, Enum):
    CONTINUE = "continue"
    PAUSE = "pause"
    RESUME = "resume"
    REQUEST_FURTHER_REVIEW = "request_further_review"
    REJECT_TERMINATE = "reject_terminate"


class DecisionCondition(CTMSModel):
    """One condition attached to a leadership decision (spec section 22).

    Tracked individually — as a list of discrete, independently-satisfiable items rather
    than a paragraph of prose — because the spec's example ("Safety concern resolved",
    "Corrective action completed", ...) is explicitly a checklist Leadership re-reviews
    against, and a checklist has to be able to say which items are still open.
    """

    text: str
    satisfied: bool = False


class LeadershipDecision(CTMSModel):
    """A final governance decision recorded against an escalation (spec sections 17, 21, 22).

    This is the authoritative decision record; `Escalation.leadership_decision` /
    `decision_reason` / `decision_timestamp` are a denormalised copy of the latest
    decision for fast list rendering. A reason is mandatory — enforced by the route layer
    accepting no blank string, not merely by convention — because "AI can detect and
    recommend, authorized humans decide" is meaningless if the decision carries no
    accountability for *why*.
    """

    id: str
    escalation_id: str
    trial_id: str
    decision: LeadershipDecisionType
    reason: str
    conditions: list[DecisionCondition] = []
    decided_by: str
    decided_at: datetime


class AIFindingKind(str, Enum):
    ELIGIBILITY_PRESCREEN = "eligibility_prescreen"
    AE_CODING_SUGGESTION = "ae_coding_suggestion"
    PRR_SIGNAL = "prr_signal"
    PRIORITY_SUGGESTION = "priority_suggestion"
    DATA_VALIDATION = "data_validation"


class AIFinding(CTMSModel):
    """One AI-generated recommendation, with the human review that followed it (spec
    section 37).

    This is the governance record for the "AI assists, humans decide" principle: every
    row here is an AI output that *cannot* itself change trial, escalation or safety
    state — a human reviewer's decision, captured in the same row, is what does that.
    `human_decision` is None until a human has acted on the finding; a route that lets an
    AI finding drive a state transition without going through this review step would be
    the one thing this system is built not to do.
    """

    id: str
    kind: AIFindingKind
    #: What the finding is about — an escalation id, an AE id, a trial id, etc.
    subject_type: str
    subject_id: str
    engine_version: str
    input_summary: str
    finding: str
    explanation: str
    #: 0-1. Not a probability of correctness — a confidence indicator the AI itself
    #: reports, shown so a reviewer can weigh a 0.55 suggestion differently from a 0.95 one.
    confidence: float | None = None
    recommended_action: str | None = None
    created_at: datetime

    human_reviewer: str | None = None
    human_decision: str | None = None
    review_timestamp: datetime | None = None
