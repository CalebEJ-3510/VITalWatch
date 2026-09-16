# AI-Powered Clinical Trial Management System (CTMS)

A centralized, role-based CTMS for synthetic development data. The system supports the approved five-role architecture:

- Volunteer / Participant
- Company
- Investigator
- Safety Officer
- Leadership

**AI assists; authorized humans decide.** AI findings support eligibility pre-screening, adverse-event coding, PRR observation, and safety-signal review. The system does not allow AI to make final eligibility, clinical, safety, pause/resume, or governance decisions.

> **Development-only system. All records are synthetic. No real participant, trial, or institutional data is included.**

## Run locally

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

Open `http://localhost:8000`, then sign in with one of the synthetic demo accounts seeded by `app/datagen.py`.

## Database

The app uses a centralized relational model. Set `DATABASE_URL` to use PostgreSQL; otherwise it uses local SQLite.

```bash
DATABASE_URL="postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres"
```

Useful commands:

```bash
python -m scripts.supabase check
python -m scripts.supabase init
python -m scripts.supabase reset
python -m scripts.supabase verify
./scripts/seed.sh
python -m app.audit --verify
python scripts/verify_ctms_lifecycle.py
```

## Approved CTMS workflows

### Participant registration and eligibility

1. Company publishes a registration form and defines eligibility criteria.
2. Volunteer submits registration information.
3. AI stores a reviewable pre-screen finding: potentially eligible, potentially not eligible, or needs Investigator review.
4. Investigator records the final decision: eligible, not eligible, or more information required.
5. An eligible decision creates the enrollment record.

### Consent and participation

Company publishes versioned consent forms. Volunteers can view the current published version and explicitly accept or reject it. The decision, form version, timestamp, and consent history are retained in an audit record. Participants can also view their own appointments and report symptoms/adverse events.

### Protocol-deviation and safety escalation

- Investigator protocol-deviation escalation: pause for protocol review → Company response → Investigator review → resume or Leadership escalation.
- Safety escalation: adverse event → Safety Officer review → pause for safety review and configurable clock → Company response → Safety Officer review → resume or Leadership escalation.

Investigators and Safety Officers use one centralized escalation entity. Leadership receives the consolidated review package and records the final decision with mandatory reason, decision-maker, timestamp, and individually stored conditions.

## CTMS routes

| Route | Authorized use |
|---|---|
| `/` | Public landing page / role-based home redirect |
| `/login` | Authentication |
| `/portal/volunteer` | Own registrations, consent, appointments, participation status, and AE reports |
| `/portal/company` | Trial operations, forms, appointments, and corrective-action queues |
| `/portal/investigator` | Eligibility review, enrollment monitoring, deviations, and escalations |
| `/portal/safety_officer` | AE coding review, PRR/signal review, and safety escalation work |
| `/portal/leadership` | Governance dashboard and pending decisions |
| `/search` | Leadership global search across CTMS records |
| `/escalations` | Centralized escalation workflow for authorized operational and governance roles |
| `/audit` | Leadership audit review and chain verification |
| `/docs` | OpenAPI specification |

## Stack

FastAPI · Jinja2 server-rendered templates · PostgreSQL on Supabase, or stdlib `sqlite3` ·
self-hosted fonts and a locally compiled Tailwind build — **no CDN request renders the
product at runtime**. Chart.js is not used; every figure is server-rendered HTML/CSS.
One process at runtime; the stylesheet is the only ahead-of-time artefact:
`npm install && npm run build:css` (scans `app/templates/`, writes
`app/static/vendor/tailwind.css`).
See [`docs/architecture.md`](./docs/architecture.md) for details.

## Security and auditability

- Every non-public route requires an authenticated session.
- Role checks are enforced on the server.
- Volunteer views are query-scoped to their own authorized participant records.
- CSRF protection is required for mutating routes.
- Important mutations write append-only audit events in the same transaction.
- Audit events retain actor, role, opaque session reference, action, resource, before/after state, timestamp, and reason.
- The audit chain is tamper-evident and storage-level triggers reject direct updates and deletes.

## AI governance

AI findings are persisted with engine version, input summary, finding, explanation, recommended action, and human-review fields. Human review is required for consequential outcomes:

- Investigator decides eligibility.
- Safety Officer confirms, corrects, or leaves AE coding uncoded.
- Investigator or Safety Officer resolves or escalates an operational/safety issue.
- Leadership makes final governance decisions.

## Scope boundary

This repository intentionally implements CTMS workflows only. It does not provide FHIR or SDTM exports, retrieval demos, standalone investigation dashboards, hospital management, pharmacy, diagnosis, fitness, nutrition, CRM, commerce, or social features.

