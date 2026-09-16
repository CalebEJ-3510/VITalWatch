# Phase 1 — Route & capability matrix

Verified against `app/main.py`, `app/auth.py`, `app/security.py` on 2026-09-15.
Classification per prompt.md §5/§14: **implemented** (route/data/permission support
exists today) · **demo-scoped** (works, but hardcoded to the demonstration case) ·
**planned** (Phase 2–6 frontend work, no new backend needed) · **backend-dependent**
(needs schema/route/permission changes before any UI may claim it).

## Public routes (no session required)

| Route | Handler | Purpose | Classification |
|---|---|---|---|
| `GET /login` | `login_form` | Auth entry; renders `login.html` with CSRF token + safe `next` | Implemented |
| `POST /login` | `login_submit` | PBKDF2 verify → server-side session → 303 to `_safe_next_path(next)` | Implemented |
| `GET /health` | `health` | Liveness + live DB engine + row counts | Implemented |
| `GET /robots.txt` | `robots` | Disallow all indexing | Implemented |
| `/static/*` | StaticFiles | Self-hosted assets (fonts, CSS, mark) | Implemented |
| `/` (unauthenticated) | middleware | Redirects to `/login?next=/` | Implemented; **Phase 2** replaces with the public landing page |
| `/docs`, `/openapi.json` | FastAPI built-in | Swagger UI — **not** in `_PUBLIC_PATHS`, so a session is required | Implemented (intentional: the API surface is not public content) |

## Authenticated page routes (session required; middleware-enforced)

| Route | Template | Data context | Permission gate | Mutation / audit | Classification → Phase destination |
|---|---|---|---|---|---|
| `GET /` | `home.html` | counts, urgent strip, cards, chain status, `home_lens` (per-role lens link, added Phase 1) | session | — | Implemented → **Phase 2**: split into public landing; authenticated users route to Operations Home (Phase 3) |
| `GET /role/{role_id}` | `role.html` | lens metrics/worklist/signals/posture; `pi` scoping | `require_lens` (403) | — | Implemented → Phase 3: promote lens picker to real workspace switcher; per-role workspaces |
| `GET /portfolio` | `portfolio.html` | 6 KPIs, alerts, study table w/ plan-to-date | session | — | Implemented → Phase 4: reusable risk queue |
| `GET /study/{study_id}` | `study.html` | study KPIs, sites, milestones, deviations, queries | session | — | Implemented → Phase 4: persistent-context workspace + timeline |
| `GET /ae` | `ae.html` | AE register w/ live clocks, intake form, filed confirmation | session (read) | — | Implemented → Phase 5: queue + staged intake + case workspace |
| `POST /ae` | — | form: study, subject, narrative, onset, severity, causality, outcome, serious | `require_role(AE_WRITE_ROLES)` + `verify_csrf` | **audited** `CREATE adverse_event`, one transaction | Implemented |
| `GET /signals` | `signals.html` | PRR-ranked terms, threshold, contingency context | session | — | Implemented → Phase 5: signal workspace + honest investigation entry |
| `GET /investigation` | `investigation_case.html` | single hardcoded case (`case_data.py`) indicators | session | — | Demo-scoped → Phase 5: generalize presentation or label demo-scoped |
| `GET /investigation/{case_id}` | `investigation_board.html` | report, retrieval (BM25+concept+RRF), decisions; guard: only `INV-001` | session | — | Demo-scoped → Phase 5: reusable investigation board |
| `POST /investigation/{case_id}/decision` | — | form: action, reason, evidence_query (request body — the correct pattern) | `require_role(DECISION_WRITE_ROLES)` + `verify_csrf` | **audited** decision record, one transaction | Implemented |
| `GET /audit` | `audit.html` | events (≤200), filters, chain verification (walks whole chain every load) | session | — | Implemented → Phase 5: audit center redesign |

## API routes (session required; 401 JSON when absent)

| Route | Purpose | Gate | Classification |
|---|---|---|---|
| `GET /api/kpi/portfolio` | Portfolio KPIs | session | Implemented |
| `GET /api/kpi/study/{id}` | Study KPIs | session | Implemented |
| `GET /api/kpi/role/{role_id}` | Lens metrics as JSON, definitions included | `require_lens` | Implemented |
| `GET /api/audit/verify` | Chain verification result | session | Implemented |
| `GET /api/alerts` | Rule-engine alerts | session | Implemented |
| `GET /api/signals` | PRR signals + caveat text | session | Implemented |
| `GET /api/pv/code?narrative=…` | Coding demo | session | **Deprecated Phase 1** — narrative in URL query string (logs/history). Kept for `/docs` compatibility only; no UI may wire it |
| `POST /api/pv/code` (JSON body) | Coding assist, narrative in request body | session + `verify_csrf_header` (`X-CSRF-Token`) | **Added Phase 1** — the only coding route an interactive UI may call (prompt.md §0.1, §7.3) |
| `GET /api/investigation/{case_id}` | Case JSON incl. explicit `not_claimed` list | session | Demo-scoped (single case) |
| `GET /api/investigation/{case_id}/retrieve?q=…` | Retrieval inspector (BM25 / concept / RRF) | session | Demo-scoped; **note**: `q` rides the query string — acceptable for literature-corpus queries, but if it ever carries narrative text it needs the same request-body treatment (§7.3) |
| `GET /api/fhir/ResearchStudy/{id}` | FHIR R4 demo export | session | Implemented |
| `GET /api/export/sdtm/dm.csv` | SDTM DM domain CSV | session | Implemented |
| `POST /logout` | Revoke session | session + `verify_csrf` | Implemented |

## Capability map — who may do what (enforced server-side)

| Capability | Gate | Roles permitted |
|---|---|---|
| Read any page/API | middleware session check | all 7 roles |
| Open `investigator` lens | `ROLE_LENS_ACCESS` | principal_investigator (scoped to own `pi_name`), study_coordinator, monitor, administration, regulator |
| Open `safety` lens | `ROLE_LENS_ACCESS` | pharmacovigilance, administration, regulator |
| Open `leadership` lens | `ROLE_LENS_ACCESS` | ethics_committee, administration, regulator |
| File adverse event (`POST /ae`) | `AE_WRITE_ROLES` | principal_investigator, study_coordinator, pharmacovigilance |
| Record investigation decision | `DECISION_WRITE_ROLES` | principal_investigator, pharmacovigilance |
| Any mutation | `verify_csrf` / `verify_csrf_header` | role gate + CSRF, both required |
| Regulator writes | — | **none, by construction** (`REGULATOR` is never in a write-allow set) |

Lens access is checked on the page route *and* the JSON twin; the sidebar and lens
picker only list permitted lenses (a convenience over the enforced boundary, not
the boundary itself).

## Known gaps this matrix makes visible (nothing here may be faked in UI)

- **No per-record assignment model** — "Assigned to me" is backend-dependent (§9.3.1).
- **No AE lifecycle beyond intake** — no coding correction, acknowledgment, follow-up,
  closure, or submission-evidence writes.
- **Single hardcoded investigation case** — guards at `main.py` 661, 706, 735.
- **No saved views / notifications** — no persistence for either; localStorage fakes
  are forbidden (§1.2, §11).
- **`timeline.py` orphaned** — computed, never imported by any template (Phase 4 adopts
  or explicitly defers).
- **Emoji as semantic markers** in `investigation_board.html` (10 instances) — Phase 5
  replaces with the badge/evidence components.
