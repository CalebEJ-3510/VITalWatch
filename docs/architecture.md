# Architecture — AI-Powered CTMS

This document reflects the **current, approved implementation only**. It supersedes and
replaces earlier hackathon-pitch documents (architecture/compliance-matrix/demo-script/
qa-prep/deck-outline/cue-card/spec-coverage-gap-analysis/implementation-roadmap) that
described a different product (FHIR/SDTM export, a standalone "investigation" board,
BM25/RRF evidence retrieval, and three generic role "lenses"). Those features have been
removed from the codebase; this document does not describe them.

## Scope

A centralized, role-based Clinical Trial Management System with exactly five primary
roles — **Volunteer/Participant, Company, Investigator, Safety Officer, Leadership** —
and one governing principle: **AI assists, humans decide.** See [../README.md](../README.md)
for the workflow summary and route table.

## Process and storage

One FastAPI process, server-rendered Jinja2 templates, one relational database reached
through `app/db.py`. `DATABASE_URL` selects Postgres (Supabase); unset, it falls back to
a local SQLite file. Both engines run identical queries and produce an identical audit
chain head hash, because the audit payload is canonical JSON of the row content, not a
storage-format artifact.

```
                  browser
                     │
              HTML over HTTP
                     │
    ┌────────────────▼────────────────┐
    │        FastAPI · one process    │
    │                                 │
    │  main.py       routes, portals  │
    │  ctms.py       lifecycle services (registration, eligibility,
    │                consent, AE intake, AE coding — AI findings only)
    │  governance.py escalation / statutory clock / corrective action /
    │                leadership decision state machine
    │  auth.py       sessions, password hashing, role gate
    │  security.py   CSRF
    │  audit.py      hash-chained, append-only trail
    │  pv.py         AE term coding + statutory clock computation
    │  signals.py    PRR / disproportionality screening
    │  kpi.py        trial-level computed metrics
    │  models.py     Pydantic schema, enums, status dimensions
    │  db.py         SQLite | Postgres, schema DDL, append-only guard
    └────────────────┬────────────────┘
                      │  DATABASE_URL selects one
           ┌──────────┴──────────┐
           ▼                     ▼
 ┌───────────────────┐  ┌───────────────────┐
 │ Supabase Postgres │  │  data/ctms.db     │
 │ append-only guard  │  │  SQLite fallback  │
 │ via trigger fn     │  │  via RAISE(ABORT) │
 └───────────────────┘  └───────────────────┘
```

**Rendering.** Jinja2 templates rendered server-side. Fonts are self-hosted
(`app/static/fonts.css`, metric-matched fallbacks) and the Tailwind utility set is
compiled locally from the templates (`npm run build:css` → `app/static/vendor/tailwind.css`)
— no CDN request renders the product, so offline behaviour is deterministic. Chart.js is
not used; every figure is server-rendered HTML/CSS. Design tokens live in
`app/static/tokens.css`, the single source of truth.

## Roles and routes

Enforced server-side by `require(*roles)` in `app/main.py` on every mutating and
role-scoped route — never by hiding UI elements. See [../README.md](../README.md#ctms-routes)
for the route table and [../README.md](../README.md#security-and-auditability) for the
access-control summary.

## Trial status — four independent dimensions

A trial never collapses to one status field:

- `status` — lifecycle stage (`protocol` → `ec_approval` → `ctri_registered` →
  `site_activation` → `screening` → `enrolling` → `follow_up` → `close_out`).
- `operational_status` — `active` / `paused_protocol_review` / `paused_safety_review` /
  `under_leadership_review` / `terminated`. Owned by `app/governance.py`.
- `safety_status` — `normal` / `escalated` / `resolved`.
- `leadership_status` — `none` / `under_review` / `decided`.

Enrollment status (on-track / at-risk) is never stored — it is derived on read from
`target_enrolment` / `actual_enrolment` / plan-to-date, the same way every KPI in this
system is computed rather than cached.

## Escalation — one entity, two raisers

Investigator raises `protocol_deviation`; Safety Officer raises `safety_concern`. Both
live in the single `escalations` table, distinguished by `escalation_type` /
`raised_by_role`, so there is exactly one workflow shape (Company response → reviewer
decision → resume, or unsatisfactory/late → Leadership decision) rather than two systems
that could disagree about what "open" means. See `app/governance.py` for the state
machine and required fields.

## Statutory / regulatory clock

The response deadline is read from `app/config.py` (environment-configurable), never
hard-coded as a universal regulatory period. `governance.clock_progress` derives
remaining time, due-soon, and overdue state on read from the stored deadline against the
live clock — never from a cached status column.

## AI governance

Every AI-produced result is persisted to `ai_findings` with engine version, input
summary, finding, explanation, recommended action, and `human_reviewer` /
`human_decision` / `review_timestamp`, all NULL until a named authorized human disposes
of it. AI never sets `operational_status`, `safety_status`, `leadership_status`, an
eligibility decision, or AE coding on its own — see `app/ctms.py` (eligibility
pre-screen, AE-coding suggestion) and `app/governance.py` (`_raise_ai_finding_if_signal`,
the only place this module lets an algorithm write anything).

## Auditability

`app/audit.py` — SHA-256 hash chain (`hash = sha256(canonical_json(payload) + prev_hash)`),
gapless sequence numbers, `role` and `session_ref` on every row. Every mutation writes its
audit row in the same transaction as the change it describes (`begin_audit_append` →
write → `audit.record(commit=False)` → single `commit()`), so a write that cannot be
audited is not committable. `BEFORE UPDATE`/`BEFORE DELETE` triggers on `audit_events`
reject direct edits at the storage layer on both engines — this is verified by
`scripts/verify_ctms_lifecycle.py` and `tests/test_audit_integrity.py`, not merely
asserted.

## Configuration

Alert thresholds, statutory clock durations, and the demo seed are read from the
environment via `app/config.py` and documented in `.env.example` — never compiled in.

## Deferred / not implemented

Electronic-signature primitive distinct from the existing attributed, timestamped audit
event; backup/restore rehearsal (an operations decision, not a code artifact);
ISO/IEC 27001 and CERT-In (organisational certifications, not code properties).
