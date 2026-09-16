# Final Architecture-Compliance Report — AI-Powered CTMS

Continuation of a prior controlled-migration session (paused for credits). This report
covers only the work completed in this session, building on the already-migrated
`app/main.py` portal architecture, `app/ctms.py` lifecycle services, and
`app/governance.py` escalation state machine found on disk at resume.

---

## A. REMOVED

**Confirmed dead code (already removed before this session, verified still gone):**
`app/timeline.py`, `app/investigation.py`, `app/retrieval.py`, `app/fhir.py`,
`app/sdtm.py`, `app/corpus.csv`, `app/templates/investigation_board.html`,
`app/templates/investigation_case.html`, `aud.py`, stale rehearsal scratch dirs.

**Removed in this session:**
- `app/roles.py` — the three generic role "lenses" (investigator/safety/leadership),
  superseded entirely by the five-role `portal/*` dashboards. No longer imported or
  routed by `app/main.py`.
- `app/templates/home.html`, `app/templates/portfolio.html`, `app/templates/role.html`
  — templates for the removed lens architecture; not rendered by any surviving route.
- `scripts/rehearse.py` + `tests/test_rehearsal_safety.py` — the demo-rehearsal harness
  built entirely around the removed `/portfolio`, `/role/*`, `/investigation*`,
  `/api/fhir/*`, `/api/export/sdtm/*` routes and role vocabulary; not salvageable by
  incremental edit without rewriting it as a different tool. `scripts/verify_ctms_lifecycle.py`
  (already present) is the current lifecycle smoke check.
- Eight stale "hackathon pitch" docs describing the removed product surface (FHIR/SDTM
  export, BM25/RRF evidence retrieval, standalone investigation board, three generic
  role lenses): `docs/architecture.md` (old version), `docs/compliance-matrix.md`,
  `docs/demo-script.md`, `docs/qa-prep.md`, `docs/deck-outline.md`, `docs/cue-card.md`,
  `docs/spec-coverage-gap-analysis.md`, `docs/implementation-roadmap.md`.
- `refactor/` — untracked scratch audit notes from the prior session's cleanup pass;
  not a product artifact.
- Stray comments in `app/datagen.py`, `app/db.py`, `app/governance.py`,
  `app/templates/portal/_partials.html`, `app/models.py` referencing the deleted docs,
  `app/roles.py`, and SDTM.

## B. REFACTORED

- **`scripts/deploy_check.sh`** — rewritten to probe only routes that still exist
  (`/health`, `/robots.txt`, `/login`, `/docs`); every session-gated portal/escalation
  route requires authentication and cannot be smoke-tested by an anonymous curl probe.
- **`scripts/supabase.py`** — `EXPECTED_SEED_HEAD` updated to the current seed's audit
  chain head hash (verified by direct computation against a fresh seed); stale comment
  about "the investigation case" corrected.
- **`docs/architecture.md`** — replaced with one accurate document describing the
  current process/storage/roles/status-dimensions/escalation/AI-governance/audit design,
  in place of the eight retired documents.
- **`app/main.py` — four latent bugs fixed:** `raise_escalation`, `company_response`,
  `reviewer_response`, and `leadership_decision` all referenced `audit_session_ref(request)`
  without declaring `request: Request` as a route parameter. This was a `NameError` that
  would 500 on **every real invocation** of raising an escalation, submitting a Company
  response, recording a reviewer decision, or recording a Leadership decision — the four
  most safety/governance-critical write paths in the system. Found by the new integration
  tests (Task 4), not by static review; fixed by adding the missing parameter to each
  handler signature.

## C. ADDED

- **`tests/test_ctms_workflow.py`** (7 tests) — end-to-end HTTP-level coverage for:
  - Volunteer consent accept, reject, and re-render of an already-decided version.
  - `record_consent` decision validation.
  - `audit_events.session_ref` populated end-to-end from a real authenticated session,
    through `app/ctms.py` (registration submission) and `app/governance.py`
    (escalation raise), matching `auth.session_reference(cookie)` exactly.
  - `session_ref` stays `NULL` (never invented) for a call made with no session.

## D. DATABASE

Centralized relational schema (`app/db.py` DDL + `app/ctms.py`'s `LIFECYCLE_SCHEMA`),
SQLite or Postgres selected by `DATABASE_URL`, identical queries and audit-chain head
hash on both engines. Core entities present and populated by live code paths (not
schema-only): `trials`, `sites`, `trial_sites`, `participants`, `trial_versions`,
`eligibility_criteria`, `registration_forms`, `registration_submissions`,
`consent_forms`, `consent_records`, `participant_user_access`, `appointments`,
`enrollments`, `adverse_events`, `ae_codes`, `prr_calculations`, `safety_signals`,
`safety_reports`, `investigation_reports`, `escalations`, `statutory_clocks`,
`corrective_actions`, `leadership_decisions`, `ai_findings`, `notifications`, `users`,
`sessions`, `audit_events`. Trial status is four independent columns
(`status`/`operational_status`/`safety_status`/`leadership_status`) rather than one
overloaded field — see `docs/architecture.md`.

Foreign keys are enforced (SQLite `PRAGMA foreign_keys`, Postgres natively);
`audit_events` carries `BEFORE UPDATE`/`BEFORE DELETE` triggers rejecting direct edits
on both engines, verified live by `python -m scripts.supabase check` and
`tests/test_audit_integrity.py`.

## E. RBAC

`app/models.py::UserRole` is exactly the five approved roles (`volunteer`, `company`,
`investigator`, `safety_officer`, `leadership`) — no more, no fewer.
`LEGACY_ROLE_ALIASES`/`parse_role` is a one-way migration shim that normalizes
pre-consolidation seed/audit role strings to a primary role at read time; it does not
expose a sixth role or duplicate the role system.

`app/auth.py::PERMISSIONS_BY_ROLE` is the single readable policy table (Role →
frozenset of `Permission`), checked server-side. Every mutating and role-scoped route
in `app/main.py` composes `require(*roles)`, which 403s a request from an unauthorized
role rather than merely hiding a UI element. Volunteer dashboard/API queries are
additionally scoped to the signed-in user's own `participant_id` via
`participant_user_access` — a Volunteer cannot reach another participant's row by
guessing an ID. Leadership cannot file AEs, raise escalations, or submit a Company
response; Company cannot decide governance or code an AE; Investigator/Safety Officer
review responses but do not make the final Leadership decision.

## F. WORKFLOWS

- **Eligibility**: Registration → AI pre-screen (`ctms.submit_registration`, stored as
  an `ai_findings` row) → Investigator decision (`ctms.decide_eligibility`: eligible /
  not eligible / more information required) → enrollment record on `eligible`. AI never
  finalizes.
- **Enrollment**: `enrollments` table created only on an Investigator's `eligible`
  decision; enrollment progress is derived on read (`kpi.trial_kpi`), never cached.
- **Protocol deviation**: Investigator raises (`governance.raise_escalation`,
  `escalation_type='protocol_deviation'`) → trial `operational_status` moves to
  `paused_protocol_review` → Company response (`governance.submit_response`) →
  Investigator review (`governance.review`) → resume or `under_leadership_review`.
- **Adverse event / safety escalation**: AE report (`ctms.report_ae`) → Safety Officer
  AE coding review (`ctms.review_ae_code`) → Safety Officer may raise a
  `safety_concern` escalation → statutory clock starts (`governance.clock_progress`,
  deadline from `app/config.py`, never hard-coded) → Company response → Safety Officer
  review → resume or `under_leadership_review`.
- **Leadership escalation/decision**: `governance.decide` requires `decision`, `reason`,
  actor, and timestamp; `conditions` are tracked individually as separate rows, not a
  free-text blob.
- **Trial lifecycle**: `TrialStatus` enum (`protocol` → ... → `close_out`) is untouched
  by the governance module; `operational_status`/`safety_status`/`leadership_status`
  are the three independent governance dimensions layered on top.

All five workflows were exercised end-to-end in this session via
`scripts/verify_ctms_lifecycle.py` and the new `tests/test_ctms_workflow.py`, and the
four route-level bugs found in the escalation write paths (§B) are now fixed and covered.

## G. AI

AI is used in exactly two places, both producing a persisted, human-reviewable
`ai_findings` row and nothing more:
1. **Eligibility pre-screen** (`ctms.submit_registration`) — compares registration
   answers against configured criteria, writes `potentially_eligible` /
   `potentially_not_eligible` / `needs_investigator_review` with matched/failed/missing
   criteria in `explanation`. The Investigator's decision (`ctms.decide_eligibility`)
   is the only thing that sets `registration_submissions.status` to a final value.
2. **AE-coding suggestion** (`ctms.report_ae`, via `pv.code_best`) — suggests a term/code/
   confidence. `ai_findings.human_decision` stays `NULL` until the Safety Officer
   confirms, corrects, or leaves it uncoded (`ctms.review_ae_code`).

`governance._raise_ai_finding_if_signal` additionally attaches a PRR-signal finding to
a safety escalation for the reviewer's context; it never sets `operational_status`,
`safety_status`, or `leadership_status`, and never approves/rejects/pauses/resumes/
terminates a trial. No code path in the repository lets an AI-produced value become a
final eligibility, clinical, safety, or governance decision without a named human actor
recorded against it.

## H. AUDIT

`app/audit.py` — SHA-256 hash chain (`hash = sha256(canonical_json(payload) + prev_hash)`),
gapless sequence numbers, one row per mutation, written in the same transaction as the
change it describes (verified: a forced audit failure leaves no orphaned clinical
write). Every audit row carries actor, role, opaque `session_ref` (derived from the
session token, never the raw token), action, resource type/id, before/after JSON,
timestamp, and reason. `session_ref` population was previously wired for the escalation
routes only in argument-plumbing terms — this session's tests proved it reaches the
stored row end-to-end (and, in doing so, found and fixed the four routes where it was
never reaching the row at all because the handler crashed first). `BEFORE
UPDATE`/`BEFORE DELETE` triggers reject direct edits at the storage layer on both
SQLite and Postgres.

## I. VALIDATION

- **Build/import**: `python -c "from app.main import app"` — OK, 40 routes registered.
- **Tests**: `python -m pytest -q` — **57 passed**, 0 failed. Started this session at
  59 passed; removing the 9 rehearsal-safety tests (tied to the deleted
  `scripts/rehearse.py`) brought the baseline to 50, and the 7 new tests in
  `tests/test_ctms_workflow.py` bring the final count to 57.
- **Lifecycle**: `python scripts/verify_ctms_lifecycle.py` — `lifecycle-workflow-ok`.
- **Storage guard**: `python -m scripts.supabase check` — schema present, append-only
  guard active (UPDATE on `audit_events` refused).
- **Known issues**:
  - `app/kpi.py::portfolio_kpi` and `expected_enrolment` are now unused (their only
    caller, `app/roles.py`, was removed). Left in place — small, self-contained,
    harmless — rather than deleted, since `trial_kpi` in the same module is still used
    by `/trial/{id}`. Flagging rather than silently deleting a function outside this
    session's explicit removal list.
  - `ctms.decide_eligibility`'s fallback path (`site_id='UNASSIGNED'` when a trial has
    no `trial_sites` row) violates the hard foreign key on `participants.site_id` and
    will raise `IntegrityError` for any trial enrolled without an assigned site. Found
    while writing this session's tests (worked around there by seeding a real site);
    **not fixed**, because it is outside the scope of the cleanup/audit tasks tracked
    this session and changes enrollment-path behavior — flagging for a deliberate
    follow-up decision rather than silently patching a business-logic path.
  - `app/db.py`'s `role`/`session_ref` audit columns are added by `app/ctms.py::ensure_schema`
    via `ALTER TABLE ... ADD COLUMN` (idempotent, ignored on conflict) rather than by the
    base schema in `app/db.py` itself — a cosmetic inconsistency, not a functional gap;
    `main.py`'s startup lifespan always calls both `db.init` and `ctms.ensure_schema`.

## J. ARCHITECTURE COMPLIANCE

The final implementation has been reviewed against the approved architecture, and all
implemented functionality has been mapped to the approved CTMS scope.

The two known issues in §I (unused KPI helpers; the `UNASSIGNED`-site foreign-key edge
case) are explicitly identified rather than hidden, per the instruction not to claim
completeness where something remains unresolved.
