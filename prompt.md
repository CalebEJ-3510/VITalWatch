# VITalWatch — Final Frontend Master Prompt

**Consolidated master brief · supersedes `VITalWatch-UI-Upgrade-Blueprint.md` as the working spec. Nothing from that audit is dropped — every unique finding, citation, and gate from it is merged below, cross-checked against the live code in `app/`.**

Act as the senior frontend architect for this project. You own the full redesign: information architecture, visual language, typography engineering, interaction model, component system, accessibility, and verification. This is not a reskin. Do not change colors, add rounded cards, add gradients, or rearrange existing pages and call it done. Redesign the thing.

---

## 0. Mission

Reimagine the entire VITalWatch frontend as two connected experiences:

1. A memorable, informative, public landing page that explains the **why, what, who, how, trust, about, boundaries, and next step** of VITalWatch.
2. A role-aware healthcare operations product that helps authenticated users see risk, follow evidence, manage deadlines, take the correct action, and prove what happened.

The result should feel like a serious clinical operations product with an original visual identity: calm under pressure, dense when useful, spacious when a decision deserves focus, explicit about uncertainty, and honest about what the demonstration does and does not claim.

> **Product thesis:** See the risk. Follow the evidence. Act with confidence.

The frontend must make this promise credible:

> Bring trial operations, pharmacovigilance, evidence, and audit into one trustworthy view so the right person can see what needs attention, understand why, act safely, and prove what happened.

### 0.1 The anti-slop contract

**Backend note (read before anything else below):** since Phases 1–3 shipped, a teammate reconciled `app/` to a different, more mature backend (five primary roles, `app/ctms.py` lifecycle services, `app/governance.py` escalation state machine, `app/auth.py` permission matrix). The seven-role/three-lens model, the single hardcoded investigation board, and the FHIR/SDTM demo exports this document used to cite are **gone from the codebase** — not renamed, deleted. Every citation below is re-verified against the live code as of this revision. Do not resurrect the old vocabulary (`study`, `subject_code`, `principal_investigator`, `/role/{id}`, `/investigation/{id}`) anywhere in new work; the current vocabulary is `trial`, `participant_code`, `investigator`, `/portal/{role}`, `/escalations/{id}`.

"AI slop" is not a vibe complaint — on this project it names five specific, fixable defects. Treat each as a shipped bug, not a style note:

1. **Generic template feel.** Purple/blue SaaS gradients, stock-photo doctors, pulse-wave decoration, equal-weight KPI cards. Fix: the visual system must derive from the domain's own material — reference lines, deadlines, evidence chains, audit sequences — not from a healthcare-template library. See §6.
2. **Self-contradicting copy.** Largely resolved by the backend merge — `home.html` (the page that carried the old "auth is not built" disclaimer) is deleted, and `README.md` now matches `app/auth.py`/`app/db.py`. What remains live: the five `app/templates/portal/*.html` dashboards each repeat the same title/tiles/table/methodology-note shape (§3), and the trust-copy strings in `_components.html`'s `notice_synthetic` macro need a single audit pass so no page states a stronger or weaker guarantee than another. Fix: Phase 1 re-verifies every remaining claim against the code before a single pixel changes.
3. **Flattened role model — now mostly fixed at the backend, not yet at the surface.** The old seven-roles-into-three-lenses problem (`app/roles.py`, `role.html`) is gone; `app/models.py::UserRole` is exactly five primary roles (`volunteer`, `company`, `investigator`, `safety_officer`, `leadership`), each with its own `app/templates/portal/*_dashboard.html` and a real server-side capability matrix (`app/auth.py::PERMISSIONS_BY_ROLE`). What is *not* fixed: the five dashboards are visually undifferentiated — same panel/table/tile pattern repeated five times — which is the same "views are tabs" complaint one layer down. Fix: §5 and Phase 3 differentiate the five dashboards by the work each role actually does, not just by which rows a query returns.
4. **Orphaned code from the pre-merge redesign.** `app/workspace.py` (the Phase 3 "Operations Home" data layer, four role compositions) and `app/templates/ops_home.html` still exist on disk but reference the *deleted* schema (`studies`, `subject_code`, `UserRole.PRINCIPAL_INVESTIGATOR`) and are not imported or routed by `app/main.py` at all — `home()` now redirects straight to `/portal/{role}`. This is the same class of problem the old `app/timeline.py` (also deleted) used to be. Fix: Phase 3 either rebuilds `workspace.py` against the current 5-role schema and wires it in, or removes it with a documented reason — it does not stay orphaned, schema-mismatched code.
5. **Decoration standing in for interaction.** The templates' only bespoke script is `app/static/palette.js` (the command-palette progressive enhancement — a real, working piece, keep it) plus small per-page enhancements; `landing.js` is similarly minimal. Real backend capability — `POST /api/pv/code`, the escalation state machine in `app/governance.py`, the PRR signal detector in `app/signals.py` — is computed but under-exposed as interaction on the operational dashboards. Fix: §6 and Phase 4 turn existing endpoints into filtering, search, and assisted-coding interaction.

**The security/privacy defect this document used to flag as mandatory is already fixed.** `POST /api/pv/code` (JSON body, `verify_csrf_header`) exists in `app/main.py` today; the old `GET /api/pv/code?narrative=` route survives only as a `deprecated=True` twin kept for `/docs` compatibility. Any new UI that wires live coding-assist must call the `POST` route — never re-introduce a query-string narrative parameter anywhere else in the product (registration answers, escalation reasons, corrective-action text all carry free text and must go through request bodies, form posts, or JSON — never a GET query string).

---

## 1. Repository and domain context

The repository is a FastAPI/Jinja server-rendered application (`app/main.py`, ~520 lines) for synthetic clinical trial management and pharmacovigilance data, built around a **centralized, role-based CTMS with exactly five primary roles** — Volunteer/Participant, Company, Investigator, Safety Officer, Leadership — and one governing principle: **AI assists, humans decide**. See `docs/architecture.md` and `README.md` for the current, accurate system description. Preserve existing backend semantics unless a workflow genuinely requires an intentional, documented backend migration.

### 1.1 What is actually implemented (verified against source)

- **Trials, sites, participants** — `app/models.py`, `app/db.py`. A trial carries **four independent status dimensions**, never one overloaded field: `status` (lifecycle: `protocol` → `ec_approval` → `ctri_registered` → `site_activation` → `screening` → `enrolling` → `follow_up` → `close_out`), `operational_status` (`active`/`paused_protocol_review`/`paused_safety_review`/`under_leadership_review`/`terminated`), `safety_status` (`normal`/`escalated`/`resolved`), `leadership_status` (`none`/`under_review`/`decided`). A `Participant` has **no name and no date of birth** — the schema makes this a validation-time guarantee (`extra="forbid"`), not a UI convention, per the DPDP Act 2023. The only handle is `participant_code` (e.g. `AIIA-003-014`).
- **Registration → eligibility → enrollment lifecycle** (`app/ctms.py`): Company publishes eligibility criteria and a registration form → Volunteer submits registration answers → an AI pre-screen finding (`potentially_eligible`/`potentially_not_eligible`/`needs_investigator_review`) is written to `ai_findings`, never a final decision → Investigator records `eligible`/`not_eligible`/`more_information_required` (`decide_eligibility`) → an `eligible` decision creates the participant/enrollment record.
- **Consent** (`app/ctms.py::record_consent`): Company publishes versioned consent forms; Volunteer explicitly accepts or rejects the current published version; the decision, version, and timestamp are retained and shown as history.
- **Adverse-event intake, coding, and statutory reporting clocks** (`app/ctms.py::report_ae`, `app/pv.py`). Coding runs against a curated vocabulary (`app/terms.csv`) — **MedDRA and WHODrug are not used**, and no UI may imply otherwise; every coded row carries `coding_source` explicitly. Statutory clocks (24-hour EC/licensing-authority notification, 14-day narrative — NDCT Rules 2019, Third Schedule) are computed server-side at intake and re-derived on every read against the live clock (`pv.status_for`, `pv.with_live_status`, `pv.clock_counts`) — the stored `timeline_status` column is an intake-time snapshot only, never trusted as current.
- **Proportional reporting ratio (PRR) safety-signal detection** (`app/signals.py`, CLI: `python -m app.signals`). Screening threshold PRR ≥ 2.0 with ≥ 3 cases (`signals.PRR_THRESHOLD`, `signals.MIN_CASES`), both named constants, not magic numbers inline.
- **Escalation / statutory-clock / corrective-action / leadership-decision workflow** (`app/governance.py`) — the centerpiece of the current backend and the thing the old `investigation.py`/`retrieval.py` board has been replaced by. Investigator raises a `protocol_deviation`; Safety Officer raises a `safety_concern`. Both share **one** `escalations` table (`escalation_type`/`raised_by_role` distinguish them, not two parallel tables). Raising an escalation pauses the trial's `operational_status`; a safety concern also starts a **configurable** statutory response clock (`settings.statutory_clock_hours`, default 72h, never hard-coded). Company must respond with nine mandatory structured fields (`explanation`, `investigation_findings`, `root_cause`, `immediate_action`, `corrective_action`, `preventive_action`, `participant_impact`, `expected_resolution`, `responsible_person` — `governance.submit_response`). The raising role reviews the response and either resolves (trial resumes) or escalates to Leadership (`governance.review`). Leadership records a final decision — `continue`/`pause`/`resume`/`request_further_review`/`reject_terminate` — with a **mandatory reason** and individually tracked, independently-satisfiable conditions (`governance.decide`).
- **AI governance, enforced in the schema, not just by convention** (`app/models.py::AIFinding`, `app/governance.py::_raise_ai_finding_if_signal`). Every AI-produced result — eligibility pre-screen, AE-coding suggestion, PRR-signal flagged on a safety escalation — persists to `ai_findings` with engine version, input summary, finding, explanation, confidence, and `human_reviewer`/`human_decision`/`review_timestamp` that stay `NULL` until a named human disposes of it. No code path lets an AI finding set `operational_status`, `safety_status`, `leadership_status`, an eligibility decision, or final AE coding on its own.
- **Session-based authentication, a real capability matrix, CSRF protection, and audited mutations** (`app/auth.py`, `app/security.py`). PBKDF2-SHA256 password hashing (200,000 iterations), server-side sessions (only the SHA-256 of the token is stored), and `app/auth.py::PERMISSIONS_BY_ROLE` — a single readable Role → `frozenset[Permission]` table (`FILE_ADVERSE_EVENT`, `RAISE_PROTOCOL_DEVIATION`, `RAISE_SAFETY_CONCERN`, `REVIEW_ESCALATION_RESPONSE`, `SUBMIT_COMPANY_RESPONSE`, `LEADERSHIP_DECISION`, `VIEW_ESCALATIONS`, `VIEW_AUDIT_TRAIL`). This is real and current — no UI may describe it as absent or aspirational.
- **A tamper-evident, append-only audit chain** (`app/audit.py`): `hash = sha256(canonical_json(payload) + prev_hash)` plus a gapless sequence number; every row also carries `role` (the actor's role *at the time*) and an opaque `session_ref` (never the raw session token) — spec-section-30 fields the earlier revision of this table lacked. `UPDATE`/`DELETE` on `audit_events` are refused by database triggers on **both** SQLite and Postgres, verified by `scripts/verify_ctms_lifecycle.py` and `tests/test_audit_integrity.py`.
- **SQLite fallback and a Postgres/Supabase boundary**, selected by one environment variable (`DATABASE_URL`); `/health` reports which engine is live; both engines run identical queries and produce an identical audit-chain head hash.
- **The five role-specific dashboards already exist and are routed**: `app/templates/portal/{volunteer,company,investigator,safety_officer,leadership}_dashboard.html`, served from `/portal/{role}` in `app/main.py`. This is real, current work — do not treat "per-role dashboard" as an unbuilt Phase 3 goal; the goal now is differentiating them further (§5, §9) and closing the state/interaction gaps named in §3.

### 1.1.1 What no longer exists — do not reference, plan against, or resurrect

The following were true of an earlier version of this backend and are **not** true of the current one. They were removed by the teammate's backend-reconciliation merge, confirmed absent by direct source inspection:

- **`app/roles.py`** and the three generic role lenses (investigator/safety/leadership) — replaced entirely by the five-role `portal/*` dashboards.
- **`app/templates/home.html`, `portfolio.html`, `role.html`** — deleted; no route renders them.
- **`app/investigation.py`, `app/retrieval.py`** (BM25 + concept-expansion + RRF retrieval), **`app/case_data.py`-driven investigation board**, **`app/templates/investigation_case.html`, `investigation_board.html`** — the entire investigation/evidence-retrieval feature is gone. `app/case_data.py` itself survives only as inert seed-data constants for one demo trial (`AYU-008`) consumed by `app/datagen.py`; it backs no route, no board, no guard conditions. Do not plan an "investigation workspace," a "reusable investigation," or a BM25/RRF retrieval UI — there is nothing left to generalize.
- **`app/fhir.py` (FHIR R4 export), `app/sdtm.py` (SDTM DM-domain export)** — deleted. There is no export surface to make "truthful" or to build a UI affordance for; do not include FHIR/SDTM in any capability table, phase plan, or landing-page proof point.
- **`app/timeline.py`** — deleted (it was the orphaned-code example in the previous version of this brief; it has since been removed rather than adopted). Do not plan a "study timeline" feature around it. If a timeline view is wanted later, it is new work, not adoption of existing code.
- **`scripts/rehearse.py`** and its safety tests — removed; the demo-rehearsal harness was built entirely around the deleted routes/roles above and was not salvageable by incremental edit. Use `scripts/verify_ctms_lifecycle.py` for the current lifecycle smoke check.
- The seven-role vocabulary itself (`principal_investigator`, `study_coordinator`, `monitor`, `ethics_committee`, `pharmacovigilance`, `administration`, `regulator`) is gone from the active schema. `app/models.py::LEGACY_ROLE_ALIASES`/`parse_role` is a **one-way migration shim** that normalizes any old role string found in a pre-existing `users` row or historical audit row to one of the five primary roles at read time; it does not expose a sixth role or bring the old vocabulary back into new code.

### 1.1.2 Orphaned code introduced by the pre-merge Phase 3 work — flag for rebuild, do not wire in as-is

`app/workspace.py` (478 lines: `HomeContext`, `QueueItem`, `ROLE_CLASS`, `_safety_home`/`_investigator_home`/`_site_home`/`_oversight_home`, `home_context`) and `app/templates/ops_home.html` were built during this project's earlier Phase 3 against the **old** seven-role schema — they reference `studies`, `subject_code`, `UserRole.PRINCIPAL_INVESTIGATOR`/`STUDY_COORDINATOR`/`MONITOR`/`ETHICS_COMMITTEE`/`PHARMACOVIGILANCE`/`ADMINISTRATION`/`REGULATOR`, none of which exist in `app/models.py` anymore. `app/main.py::home()` does not import or call `workspace.py` at all; a signed-in user is redirected straight to `/portal/{role}`. This module would raise `AttributeError` on `UserRole.PRINCIPAL_INVESTIGATOR` the instant anything tried to call it.

This is exactly the class of problem `app/timeline.py` used to be (§1.1.1) — computed, well-documented, unused, and now also schema-incompatible. Treat it the same way: **before any phase reuses the "priority queue" idea it embodies, rebuild `workspace.py` against the current 5-role model** (`volunteer`/`company`/`investigator`/`safety_officer`/`leadership`, `trial_id`/`participant_code`, `app/ctms.py`/`app/governance.py` as the data sources) or delete it with a documented reason. Do not import it, route it, or extend it in its current form — its good ideas (priority queue over KPI wall, "within my authorized scope" naming discipline, live-clock-derived ordering) are still worth keeping; its code is not.

### 1.2 Known technical debt to close, not hide, during the redesign

| Issue | Evidence | Required treatment |
|---|---|---|
| Five portal dashboards share one visual shape | `app/templates/portal/*_dashboard.html` — title/tiles/table/panel repeated per role | Phase 3/4: differentiate by the work each role does (§5, §9), not just by which query ran |
| `app/workspace.py`/`ops_home.html` orphaned and schema-incompatible | Not imported by `app/main.py`; references deleted `UserRole` members and `studies`/`subject_code` | Phase 3: rebuild against the 5-role schema or delete with a documented reason (§1.1.2) — do not leave silently broken code on disk |
| No "Assigned to me" — no owner/assignment field exists on any record | `app/db.py` schema has no assignment/owner column anywhere | Label any per-role work view **"Within my authorized scope"** until an assignment schema + audited assignment writes exist |
| AE lifecycle stops at coding review | `app/ctms.py::report_ae`/`review_ae_code` — intake, AI coding suggestion, Safety Officer confirm/correct/uncoded; nothing beyond that | Case workspace shows intake + coding facts; further lifecycle (follow-up, closure) ships only with new schema |
| `ctms.decide_eligibility`'s `UNASSIGNED`-site fallback can violate the `participants.site_id` foreign key | `docs/final-compliance-report.md` §I, flagged not fixed | Known, documented backend issue — do not paper over it in the UI; surface honestly if it ever produces a visible error |
| Docs previously contradicted the implementation | Resolved: `README.md` and `docs/architecture.md` were rewritten this session to match current code | Phase 1: verify the reconciliation holds; do not let new UI copy drift back out of sync |
| Indigo is called "reserved for the reference line" but also used for primary buttons/focus/selection | `app/static/app.css` comment vs. `.btn-primary`, `:focus-visible` | Phase 1: pick one — a distinct benchmark token, or an explicitly shared accent — and say so in the token file; do not claim exclusivity while sharing the color |

### 1.3 What must survive the redesign

The backend is stronger than the current interface suggests. Preserve, and build the new UI on top of:

- Computed KPIs (`app/kpi.py`), alerts (`app/alerts.py`), coding (`app/pv.py`), reporting-clock states, and PRR signal calculations (`app/signals.py`) — nothing here is a fabricated UI constant; every figure is derived on read, never cached or stored.
- Authentication, session handling, CSRF protection, and the real capability matrix (`app/auth.py::PERMISSIONS_BY_ROLE`).
- The escalation/statutory-clock/corrective-action/leadership-decision state machine (`app/governance.py`) — this is the actual signature workflow of the current backend and should anchor the signature experience in this redesign (replacing the deleted investigation board as that role, §11).
- The audit chain and its integrity tests — the atomic relationship between a recorded decision and its audit entry must never be weakened. Every mutation writes its audit row in the same transaction as the change it describes.
- Source provenance (`coding_source` on every AE), synthetic-data disclosures, and explicit non-causality language already present in `signals.py`'s and `pv.py`'s own docstrings and copy.
- The intent behind the current CSS's semantic-color and reduced-motion handling — carry the intent into the new token system even where the implementation is replaced.
- The five existing `portal/*` dashboards as the correct architectural shape (one dashboard per role, not a shared lens) — the problem to solve is their visual/interaction sameness, not their existence.

The current frontend reads as a collection of report pages behind a sidebar. It explains the prototype better than it supports daily work. Keep the strongest existing idea — a value is only meaningful against a reference line or threshold — and evolve it into a complete product language.

---

## 2. Non-negotiable product principles

Every important operational record should expose:

1. What happened.
2. Who or what is affected.
3. Severity and urgency.
4. Event time, due time, and current as-of time.
5. What is known, unknown, inferred, or awaiting verification.
6. Who owns the next action.
7. Evidence and provenance.
8. What has already been reviewed or changed.
9. The next safe action.

System detection is not medical judgement. A statistical signal is not proof of causality or incidence. A deadline indicator is not proof that an external authority received a submission. A verified audit chain is not, by itself, proof of organizational compliance.

Prioritize unresolved safety and compliance risk above activity volume. Two unresolved serious cases should have more visual weight than hundreds of completed visits.

Use plain, active, user-facing language. Name what a person controls or recognizes, not how the database is implemented. Say `Save changes`, `Assign reviewer`, `Open investigation`, or `Verify chain`; do not use vague labels such as `Submit`, `Process`, or `Smart insight`.

Separate four concerns that are easy to conflate on any record — this is a recurring design failure mode, not just an AE-specific one:

1. **Clinical/scientific fact:** narrative, coded term, seriousness, severity, outcome, causality assessment, source.
2. **Reporting obligation:** applicable rule/protocol, trigger, deadline, recipient, status.
3. **Workflow task:** owner, acknowledgment, next step, escalation, follow-up.
4. **Audit history:** original entry, subsequent corrections, accountable actions.

Acknowledging an alert is not reporting an event. Recording evidence of submission is not proof a recipient accepted it. Closing a task does not erase a missed deadline. Keep those distinctions visible everywhere, not just in the AE workflow.

---

## 3. Current issues the redesign must solve

Explicitly address all of the following:

- The public landing page (`app/templates/landing.html`, Phase 2) and the authenticated shell (`app/templates/base.html` + `portal/_base.html`, Phase 3) already exist and already split public-vs-authenticated correctly at the route level — that specific problem from the original audit is resolved. What remains:
- The five `app/templates/portal/*_dashboard.html` pages repeat the same title/tiles/table/panel shape regardless of role — the "views are tabs" complaint has moved down one layer, from lens-switching to dashboard-sameness.
- `app/workspace.py`/`ops_home.html` — orphaned, schema-incompatible code from the pre-merge redesign (§1.1.2) — sits unused; its "priority queue over KPI wall" idea is still worth having, its code is not wireable as-is.
- `/escalations`, `/escalations/{id}`, `/ae`, `/signals`, `/audit` are functional but visually match the same repeated report-page pattern named above; the escalation detail/review/decision flow (`app/governance.py`) is the richest workflow in the backend and currently has the least distinctive interface.
- Adverse-event intake and case review are on one page (`ae.html`) with no case workspace, no lifecycle beyond intake→coding.
- Explanatory copy (the `note()` macro blocks on `ae.html`/`signals.html`) competes for visual weight with decision-critical information — both currently render at similar prominence.
- Loading, stale, connection-loss, error, permission, session-expired, success, and rich empty states are inconsistent or absent across the portal dashboards and escalation flow.
- Mobile navigation and tables rely too heavily on horizontal scrolling on the data-dense pages (`ae.html`, `signals.html`, `audit.html`, `escalations.html`).
- The frontend's only bespoke interaction beyond navigation is the command palette (`palette.js`) and small per-page enhancements (`landing.js`) — real backend capability (escalation workflow, PRR signals, AE coding-assist) is under-exposed as live interaction.
- Routine facts and urgent unresolved work (an overdue statutory clock vs. a completed appointment) receive similar visual weight across the portal dashboards.

## 4. Public/authenticated routing contract

**This is largely already implemented** — verify it holds, do not rebuild it:

- `/` is the unauthenticated public landing page (`landing.html`, Phase 2, shipped).
- An authenticated user requesting `/` is redirected to `/portal/{role}` (`app/main.py::home()`) — confirmed in the current code, not aspirational.
- `/login` is the authentication entry point; `next` defaults to `/` and only accepts safe internal paths (`app/main.py::login()`).
- `/about` redirects to `/#about` on the landing page.
- `/docs` is FastAPI's own OpenAPI UI — developer/API documentation, session-gated (not in `_PUBLIC`), not a primary clinical-workflow destination.
- `/health` and `/robots.txt` are public and unchanged.

Do not use hidden links as a security boundary. Backend authorization (`app/auth.py::require_role`/`require_permission`) remains authoritative — the nav should reflect it, never substitute for it.

### 4.1 Current route inventory (verified against `app/main.py`)

```text
/                              Public landing; authenticated users -> /portal/{role}
/login, /logout                Sign in / out
/portal/volunteer               Own registration, consent, appointments, AE self-report
/portal/volunteer/register      Registration form (GET/POST)
/portal/volunteer/consent       Consent accept/reject (POST)
/portal/volunteer/reports       AE self-report (POST)
/portal/company                 Trial list + pending/history escalations
/portal/company/operations      Criteria, forms, appointments for one trial
/portal/company/criteria        Add eligibility criterion (POST)
/portal/company/forms/registration, /forms/consent   Publish forms (POST)
/portal/company/appointments    Schedule appointment (POST)
/portal/investigator            Trial list, submissions, deviations, escalations
/portal/investigator/eligibility/{submission_id}      Eligibility decision (POST)
/portal/safety_officer          Uncoded/coded AEs, signals, safety escalations
/portal/safety_officer/ae/{id}/code   AE coding review (POST)
/portal/leadership              Portfolio KPIs, pending decisions, audit head
/search                         Leadership global search
/trial/{trial_id}               Trial detail (role-scoped for volunteers)
/ae                              AE register + intake form
/signals                         PRR-ranked safety signals
/escalations                     Inbox (role-scoped)
/escalations/new                 Raise form (investigator/safety_officer)
/escalations/{id}                 Detail (package: escalation, clock, responses, decisions, AI findings)
/escalations/{id}/respond         Company structured response (POST)
/escalations/{id}/review          Investigator/Safety Officer resolve-or-escalate (POST)
/escalations/{id}/decision         Leadership final decision (POST)
/audit                            Audit trail + chain verification
/api/search                       Palette backend (GET, permission-filtered)
/api/pv/code                       POST JSON coding-assist (the fixed, safe route)
/api/pv/code (GET, deprecated)     kept only for /docs compatibility — never wire new UI to it
```

There is no `/portfolio`, `/studies`, `/study/{id}`, `/cases`, `/case/{id}`, `/signal/{id}`, `/investigation/{id}`, or `/settings` route today, and no FHIR/SDTM export route. Any of these may be **new** frontend-enhancement or backend-dependent work (classify per §5) — they are not existing routes being redesigned.

---

## 5. Actual roles versus public personas

Do not confuse landing-page personas with currently implemented permissions.

**Current authenticated roles** (`app/models.py::UserRole`, exactly five, no more): `volunteer`, `company`, `investigator`, `safety_officer`, `leadership`. Each has its own routed dashboard (`/portal/{role}` → `app/templates/portal/{role}_dashboard.html`) and its own capability set (`app/auth.py::PERMISSIONS_BY_ROLE`) — there is no lens-picker, no shared `<select>`, and no URL that lets one role's session open another role's dashboard (`require(*roles)` / `require_permission` 403s server-side on every route, not just a nav-hiding convenience).

The landing page may describe broader personas — e.g. a "medical reviewer" framing of Safety Officer, a "quality/compliance" framing of Leadership — but the persona must map onto one of the five real roles; it must not imply a sixth account type or a permission that `PERMISSIONS_BY_ROLE` does not grant.

For every proposed workspace feature, classify it as:

- **Available now:** existing route/data/permission support is sufficient.
- **Frontend enhancement:** new composition is needed, but no new authorization model is required.
- **Backend-dependent:** requires new fields, tables, routes, permissions, or audited mutations.
- **Future concept:** may be explained publicly but must not be faked in the authenticated product.

Each of the five roles has exactly one dashboard — there is no multi-lens account in the current model, so a workspace switcher is not applicable today. If a future role gains more than one composition, define a deterministic default and a clearly labelled switcher then; do not build switcher UI against a one-dashboard-per-role reality now.

### 5.1 Role-by-role starting question and backend gap

Every role gets a genuinely different first screen answering a genuinely different question — not the same KPI wall with a different label. This is largely already true structurally (five different dashboard routes with five different queries); the redesign's job is to make each screen answer its question with a fundamentally different layout, not just different numbers in the same layout.

| Role | First-screen question | What the backend actually gives it | Gap to acknowledge |
|---|---|---|---|
| Volunteer | What is the state of my participation? | Own trial, appointments, consent status/history, AE self-report form, own published consent form (`main.py::volunteer_dashboard`) — strictly scoped to `participant_user_access`, cannot see another participant's row | None significant — this is the most complete single-purpose dashboard already |
| Company | What does my trial need from me right now? | Trial list, pending escalations (open + company_responded), full escalation history (`company_dashboard`); a separate operations screen for criteria/forms/appointments per trial | The two Company screens (dashboard + operations) could read as one workspace with a persistent trial-context header instead of two disconnected pages |
| Investigator | Which submissions and escalations need my decision today? | Trial-scoped submissions awaiting eligibility decision, deviations, trial KPIs, escalations where `escalation_type='protocol_deviation'` (`investigator_dashboard`) | Investigator's decision access is scoped by which trial is selected in a dropdown, not by a stored "my trials" assignment — this is honest today (trial list is global, not filtered to a named PI) and should stay honestly labelled if changed |
| Safety Officer | Which event or reporting obligation requires attention next? | Uncoded AEs first, then coded, PRR signals, safety-type escalations, curated-term vocabulary reference (`safety_dashboard`) | Statutory-clock urgency (`pv.with_live_status`) is computed but not yet the dashboard's primary sort key — currently uncoded-first, not clock-first |
| Leadership | Is the institution safe, compliant, and inspection-ready? | Portfolio KPIs, escalations `under_leadership_review`, recent decisions, live audit-chain verification (`leadership_dashboard`); exclusive access to `/search` and `/audit` | None significant for what exists; portfolio KPI computation (`app/kpi.py::portfolio_kpi`) is real and could be surfaced with more than the headline numbers |

Do not add a patient portal, wearable/vitals graphics, or generic chatbot merely because this is healthcare — the Volunteer role already covers the one patient-facing surface this system is scoped to have (registration, consent, appointments, self-report), and it is intentionally minimal. Expanding it into messaging, remote monitoring, or a full patient app is explicitly **not now** work (§11) and would need a separately scoped product and privacy/safety analysis.

---

## 6. The design system — engineered, not decorated

This is the section that turns "AI slop" into a considered product. Every choice below is justified by either the domain (§0.1, §1) or by verified current front-end engineering practice (research below), not by trend-chasing.

### 6.1 Typography — the distinctive brand signature

Do not use generic "healthcare blue dashboard" styling, and do not use a single grotesque sans for everything. Typography is the one element a data-dense clinical tool can use to feel deliberate without adding visual noise. Use **three typography roles**, each with a specific job:

1. **Editorial/display face** — for public headlines and a small number of large statements only (hero line, section dividers, the five-stage workflow). Never inside a data table, form, or dense panel.
2. **Humanist sans-serif** — for body copy and all operational UI: forms, tables, nav, cards, buttons.
3. **Monospace** — for identifiers, case codes, controlled terms, timestamps, and hashes. In a schema with no patient names, the coded identifier *is* the record — it should look like one immediately, everywhere it appears, as `app.css`'s existing `.code` class already establishes.

**Recommended concrete stack, chosen for engineering reasons, not just look:**

- **Display: Fraunces.** A genuine variable font with four real axes — `wght` (weight), `opsz` (optical size), `SOFT` (softness), `WONK` (a binary "wonky"/inktrap substitution switch, auto-engages above `opsz 18`). This means one font file can carry the crisp, small-optical-size register used near data *and* the warm, high-contrast, ink-trapped display register used in the hero — by moving one axis, not swapping typefaces. It is open-source (OFL) via Google Fonts and available pre-packaged for self-hosting through Fontsource (`@fontsource-variable/fraunces`). Use it sparingly: hero statement, the `DETECT → UNDERSTAND → INVESTIGATE → DECIDE → PROVE` treatment, and a few section dividers. Never in a table cell or form label.
- **Body/UI: Manrope or Source Sans 3.** Either is a solid, humanist, highly legible sans with a genuine variable axis for weight, avoiding the over-used Inter-everywhere default without sacrificing legibility at small sizes in dense tables. Pick one, document the choice, and do not mix both across the product.
- **Identifiers/mono: IBM Plex Mono.** Already used in `app.css`'s `.code` class — keep it; it is a deliberate, technical, non-decorative choice that already fits the domain (machine-assigned identifiers should look machine-assigned).

The implementation may choose a better licensed equivalent after visual testing, but it must document the final choice in the token file and preserve the three-role system regardless of which specific families are chosen.

#### 6.1.1 Font delivery — do this correctly, it is a common source of "cheap" feeling UI

The current `base.html` loads Tailwind and Google Fonts from a CDN (lines 10, 11-16). This is the single biggest "template, not product" tell, and it is also a real reliability problem (offline demo failures, third-party render-blocking requests, and non-deterministic visuals if the CDN changes). Fix it properly, not by just moving the `<link>` tags:

- **Self-host** the chosen font files (Fontsource packages are the simplest path for exactly this — they ship the WOFF2 files and the matching `@font-face` CSS already split by unicode-range and weight/axis). Do not hand-roll subsetting unless there's a specific reason to.
- Use only the weights/axis ranges actually used. A variable font with unused axis range still costs bytes; declare `font-weight: 400 700` (or whatever range is actually used) in the `@font-face`, not the full variable range if half of it is never touched.
- Set `font-display: optional` for the display face (a hero heading swapping in half a second late is jarring; showing the well-matched fallback immediately and never swapping is calmer) and `font-display: swap` for body/mono (users are reading continuously; a short unstyled flash is preferable to invisible text).
- Use `size-adjust`, `ascent-override`, and `descent-override` on the fallback `@font-face` block for the display and body faces so the system-font fallback occupies the same line-height/width envelope as the real font. This is the concrete, testable fix for Cumulative Layout Shift when a custom font finishes loading — measure the metrics once (there are free CLI tools for this), bake them into the fallback declaration, and CLS from font swap drops close to zero.
- Preload only the body-face regular weight (the one guaranteed to render above the fold on every page); do not preload the display face on operational pages where it may not appear at all.
- Define robust system fallbacks in the token file (`ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif` for body; a serif stack for display; `ui-monospace, SFMono-Regular, Menlo, monospace` for mono — the mono stack in `app.css` is already correct, keep it).

#### 6.1.2 Text art — real HTML, not flattened images

Use text art as **real, accessible HTML text**, never a flattened image or canvas-rendered glyph with no DOM text behind it. Concrete signature treatments, in priority order:

1. **The five-stage workflow as a large typographic path** — `DETECT / UNDERSTAND / INVESTIGATE / DECIDE / PROVE`, set in the display face, with one stage highlighted as the visitor scrolls or clicks. This is the signature move (§0, product thesis) and should appear once, prominently, not be repeated as decoration elsewhere.
2. **A monospace evidence chain** that visually transforms from a raw event record into an audit row — using the mono face, so the transformation itself communicates "this became tamper-evident," not an abstract animation.
3. **Large editorial statements split across columns** with small monospace metadata labels beside them (e.g., a hero paragraph broken into two asymmetric columns with a `LAST VERIFIED · 2026-09-15T18:32Z` style label floating beside it) — ties directly to the audit-chain theme instead of being generic magazine styling.
4. **A restrained typographic "reference line" motif** derived from `app.css`'s own existing `.ref`/`.ref-mark` component (§6.3) — rendered large and decoratively on the landing page using the same visual grammar the operational product uses at small size. This is the single most on-brand text-art idea available: the landing page's hero graphic and the operational product's smallest status bar are literally the same motif at different scales.

Do **not** use: a text-based "constellation" diagram with no clear reading order, decorative gradient text with no informational role, or particle/glitch text effects — those read as generic even when technically well-executed, because they carry no connection to the domain.

**Implementation technique for the scroll-linked stage highlight:** use native CSS `animation-timeline: view()` / `scroll()` (the CSS Scroll-Driven Animations spec) as a progressive enhancement layer, gated behind `@supports (animation-timeline: view())`, with the un-enhanced fallback being all five stages shown at once as plain, fully readable static HTML (which is also the required no-JS and reduced-motion state — see §6.1.3). Browser support as of current testing: Chromium-based browsers ship it; Firefox and Safari support is behind flags or partial — hence the mandatory `@supports` gate and static fallback, not a JS polyfill that reintroduces a render-blocking dependency.

#### 6.1.3 Text art constraints (non-negotiable)

- Must retain DOM reading order.
- Must work with JavaScript disabled — show all stages as readable ordered HTML.
- Must remain legible on mobile — no text art exists only at desktop width.
- Must never replace explanatory copy — it augments, the copy underneath still stands alone.
- Must respect `prefers-reduced-motion` — show the selected/final stage immediately, no forced animation.
- Any auto-playing sequence needs pause/stop controls and keyboard-reachable direct controls to jump to any stage, with the active stage announced to screen readers (`aria-live="polite"` region or equivalent).

### 6.2 Layout — asymmetric where it earns its keep, disciplined everywhere else

Current front-end layout trends worth adopting deliberately (not cosmetically): asymmetric editorial grids are effective for **narrative, low-frequency-read content** (the landing page) precisely because they slow a first-time reader down enough to notice hierarchy. They are the wrong tool for **high-frequency-read operational content** (queues, tables, case workspaces), where a predictable, scannable grid wins every time. This is why Direction A (clinical clarity, disciplined grid) and Direction B (research editorial, asymmetric) are assigned to different surfaces, not blended into one page (§9).

**Component-level responsiveness — use CSS container queries, not just viewport media queries.** The current responsive approach (implied by Tailwind's viewport breakpoints) forces every card of a given type to respond identically regardless of where it's placed — a metric card behaves the same whether it's alone in a full-width row or squeezed into a three-column dashboard grid. Container queries (`container-type: inline-size` on the card wrapper, `@container (min-width: …)` in the card's own rules) let a single card component adapt based on the space it is actually given, which is exactly the situation the priority queue → side inspector layout (§7) creates: the same row component must compress correctly whether it renders full-width in a queue or condensed inside a drawer. Container query support is solid across current evergreen browsers; use it as the primary responsive mechanism for reusable components, keeping page-level viewport breakpoints only for shell-level decisions (sidebar collapse, drawer vs. inline panel).

### 6.3 Design token system

Create a compact source of truth (a single CSS custom-property file or equivalent) for:

- Canvas, paper, ink, muted, rule, and institutional colors.
- Reference/benchmark color — **decide explicitly** whether this stays the same hue as the primary action/focus color or gets its own token (§1.2 flags the current contradiction; resolve it here, in writing, in the token file's own comments, the way the current `app.css` header comment already tries to do).
- Breach, review, within-tolerance, neutral, unknown, and stale states.
- Typography roles (§6.1) as font-family/weight/size custom properties, not hardcoded per-component.
- Spacing scale.
- Density levels (comfortable/compact, for queues vs. dashboards).
- Border and radius rules.
- Focus ring and error styles.
- Motion durations and easing — and an explicit reduced-motion override block.
- Breakpoints (viewport-level, for shell decisions only) and container-query breakpoints (component-level, for reusable cards/rows).

Keep the existing semantic rule, it is correct and should not be reinvented:

- Indigo/blue means reference, comparison line, or active context.
- Red means actual breach or immediate attention.
- Amber means review or due-soon work.
- Green means within tolerance or verified completion.
- Neutral means information without a state.

Never rely on color alone. Urgency is filled, status is tinted — the existing `.pill-breach` (solid fill) vs. `.pill-breach-soft` (tint) distinction in `app.css` is the correct pattern; carry it forward rather than replacing it with something novel.

### 6.4 Reusable primitives

Build or centralize reusable templates/macros/components for:

- Public shell.
- Authenticated shell.
- Workspace header.
- Priority item / queue row (container-query responsive, §6.2).
- Queue toolbar.
- Filter chips and filter drawer.
- Status/priority badge.
- Deadline clock.
- Evidence item.
- Timeline (adopt `app/timeline.py`'s computation, §1.2).
- Assignment control.
- Audit event.
- Search result.
- Command palette (§7.4).
- Empty state.
- Error state.
- Loading state.
- Stale-data state.
- Permission state.
- Success confirmation.
- Modal/drawer.
- Side inspector (§7.2).
- Responsive table row.

Do not scatter inline styles, hardcoded navigation, or repeated state definitions across templates — this is precisely how the current codebase ended up with five near-identical "title, metric tiles, white panels, dense table" pages (§3).

### 6.5 Backend-driven dynamicity

All operational metrics, queue rows, statuses, deadlines, counts, filters, permissions, audit entries, and detail content must derive from backend data or an explicitly documented deterministic demo fixture. Do not hardcode values into templates when the repository already computes them (most values already are computed — see §1.1 — so this is mostly a discipline rule for *new* UI, not a rebuild of the calculation layer).

If a value is a static fixture used only inside the public landing preview, label it as representative synthetic data and keep it separate from operational route data. Dynamic behavior must be real where the backend supports it: filter changes update the result set, sort order changes the data order, deadlines reflect current clock semantics, permission changes affect available actions, and successful mutations update resulting state. Never create the impression of dynamicity by changing static numbers, cycling fake alerts, or animating placeholder rows.

---

## 7. Interaction and technical strategy

### 7.1 No rewrite by reflex

Keep FastAPI, existing calculations, domain logic, and audit behavior. Redesign the information architecture and Jinja composition, self-host static assets (§6.1.1), and add a deliberately small interaction layer.

The existing HTML-first architecture can support a much stronger experience without a framework migration. An HTML-over-the-wire approach such as **htmx** can update page regions while retaining server rendering — its documentation explicitly distinguishes HTML fragment responses from JSON APIs. If adopted, add suitable fragment endpoints or adapters; **do not assume the existing JSON endpoints under `/api/*` are drop-in fragment responses** — they return JSON for the documented API surface (`/docs`), and a fragment endpoint returning an HTML partial is a distinct, additional route. Ordinary links/forms must retain sensible behavior with JS disabled, and CSRF/session protections must be preserved on every new fragment route exactly as they are on the existing form posts.

For more stateful evidence exploration (the escalation review package, §11.4), a dedicated client-side component can be introduced at that specific boundary. Do not reach for a full SPA framework migration to solve this one screen — a framework migration does not itself solve role design, scope enforcement, or clinical correctness, and this repo does not need one to hit the acceptance criteria in §12.

### 7.2 The worklist + inspector pattern

Central interaction model for every queue-shaped surface (AE register, safety signals, escalation inbox, audit events): select a row, inspect it in a side panel without losing the queue, act, see confirmation, queue updates. This directly answers the "no dynamicity" criticism (§0.1) with a concrete, testable pattern rather than more animation.

- Selecting a row opens a side inspector for quick review; complex work (an escalation's full review package — response, clock, AI finding, decision) opens a full record page (`/escalations/{id}` already is one). The inspector is not a substitute for a real, shareable record URL — deep-link the open inspector state into the URL (query param or route segment) so a link to "this event, open" is copyable and returns to the same state.
- Focus moves into the inspector on open, `Escape` closes and returns focus to the triggering row, and a small-screen breakpoint replaces the side panel with a full-page view rather than squeezing it into a sliver.
- Preserve list filters and scroll position when the inspector closes.
- Loading, empty, error, stale, and permission states are defined for the inspector independently of the queue's own states (§10.1) — an inspector failing to load must not look identical to an empty record.

### 7.3 Responsive coding-assist, done safely

The AE coding service (`app/pv.py::code`) already exists and is worth exposing as live interaction (§0.1, point 5) — the request-body endpoint it needs is already built:

- Coding preview appears after a deliberate input pause (debounce), not on every keystroke.
- The request goes to **`POST /api/pv/code`** (JSON body, `verify_csrf_header`) — the route already exists in `app/main.py`. Never wire new UI to the deprecated `GET /api/pv/code?narrative=...` twin, which is kept only for `/docs` compatibility.
- Stale in-flight responses are cancelled/ignored when newer input arrives.
- The suggestion always requires human confirmation (Safety Officer's `confirmed`/`corrected`/`uncoded` decision, `app/ctms.py::review_ae_code`) before it affects the record — a confidence score is not a probability of diagnosis and must not be styled as one (no percentage-as-confidence bar; a plain "match basis: exact / phrase / fuzzy" label, mirroring `CodingResult.method`, is enough).
- The same request-body-not-query-string rule applies to every other free-text field that could ever be searched or previewed live — escalation reasons, corrective-action text, registration answers. `app/governance.py`'s response/review/decision routes already use form-body POSTs; that is the pattern to extend, never a GET query string carrying clinical or governance narrative.

### 7.4 Command palette / global search

**This already exists and works** — `app/static/palette.js` + `GET /api/search` (server-side, permission-filtered, 2-character floor, grouped by trial/participant/case/escalation/audit-sequence). Treat the section below as the contract it already meets, and extend it rather than rebuilding it: a single accessible command-style palette (triggered by a visible search affordance in the shell, not only a hidden shortcut) for jumping to a trial ID, case ID, participant code, escalation ID, or audit sequence number:

- Results are permission-filtered server-side before they reach the palette — never filter a forbidden result out client-side after fetching it.
- Full keyboard operability: type-ahead, arrow-key navigation, `Enter` to open, `Escape` to close, and a visible keyboard-shortcut hint that doesn't assume a specific OS modifier key without checking platform.
- Never the only way to navigate — the persistent nav rail remains fully functional without it.
- Announces result count and loading state to assistive tech (`aria-live`), and shows a distinct empty-vs-loading-vs-no-permission state (§10.1).

### 7.5 Motion budget

**Public pages:** a restrained entrance transition, purposeful scroll reveal (§6.1.2's `animation-timeline`, progressively enhanced), and optional source-to-decision illustration movement. No scroll hijacking, no content hidden until an animation completes.

**Workspaces:** small focus/selection transitions, clear drawer movement (§7.2), loading feedback, and restrained change highlighting. Preserve the user's reading position across any of these.

**Clinical states:** do not animate safety counts from zero, flash red cards, bounce "urgent" badges, celebrate serious-event submission with confetti, or auto-dismiss important errors. Reduce motion when requested (`prefers-reduced-motion`). Do not let a fading toast be the only evidence that a clinical action succeeded — pair every toast with a durable state change visible in the record itself.

The premium feeling should come from continuity and precision: where focus goes, what stays visible, what changed, and how errors recover — not from decorative animation volume.

---

## 8. Public landing page: why, what, who, how, trust, and about

### 8.1 Objective

Create a real public landing page that feels like a premium life-sciences product rather than an authenticated dashboard with an introduction paragraph, and that is specific to this domain rather than a generic healthcare template (§0.1, point 1).

### 8.2 What a first-time visitor must understand

- Why VITalWatch exists.
- What it is.
- Who it helps.
- Which workflows it connects.
- How it supports safer decisions.
- Why it is trustworthy.
- What is synthetic or not built.
- How to explore the demo or sign in.

### 8.3 Navigation

Restrained public navigation: product mark and wordmark; Product; How it works; Roles/teams; Trust and safety; About; Documentation/resources; `Explore the demo` primary CTA; `Sign in` secondary action.

Mobile must use a real drawer or accessible modal menu, not tiny horizontal links squeezed to fit.

### 8.4 Landing structure

**8.4.1 Hero.** Direct thesis: *"See the risk. Follow the evidence. Act with confidence."* One concise paragraph naming clinical-trial oversight, pharmacovigilance, evidence, and audit. Primary CTA `Explore the demo`; secondary `See how it works`.

The first viewport must show meaningful product proof — a high-fidelity HTML/CSS preview built from the real design tokens (§6.3) and representative synthetic values, showing a role-aware Operations Home, a serious-event deadline entering a queue, a signal opening an investigation, evidence appearing in context, and an audit event being recorded. The concept renders already produced (`img-mu2jflqd`, `img-mu2jil9t`, `img-mu2jfp8n` in `media-output/`) demonstrate the right *idea* — evidence-graph hero, worklist+inspector, investigation board — but are illustrative concept art, not implementation; rebuild the preview from live tokens rather than treating the PNGs as final assets. Label the preview `Synthetic demonstration`. Never imply landing-page values are production telemetry.

**8.4.2 Why.** The real operational problem: trial data, safety cases, evidence, and compliance history are often fragmented; important events can disappear inside routine activity; statistical signals require human context and investigation; teams need to know what changed, why it matters, who owns it, and what action is due. Use a visual narrative of disconnected signals becoming one traceable case. No fear-based imagery, no exaggerated patient-safety claims.

**8.4.3 What.** Five connected pillars — trial oversight; safety intake and reporting clocks; signal detection and investigation; evidence and decision workflow; audit and data integrity — each with a concise explanation, a real interface state or diagram, and a link/anchor to deeper content.

**8.4.4 How it works.** The signature workflow, set as the text-art treatment from §6.1.2:

```text
Detect -> Understand -> Investigate -> Decide -> Prove
```

Each stage explains: input; system-derived output; human decision required; evidence retained; what the system does not claim. Scroll- or click-driven storytelling is fine; essential information must never depend on animation completing (§6.1.3, §7.5).

**8.4.5 Role-based value.** An interactive role selector or segmented content experience for principal investigator, study coordinator, monitor, pharmacovigilance officer, safety/medical reviewer persona, institutional leadership, and regulator/quality reviewer persona (§5.1's roles, explained here as personas). The selector changes content and preview only — it must not imply a public visitor can change application permissions.

**8.4.6 Trust and safety.** Show prominently that VITalWatch: makes evidence visible; distinguishes detected patterns from human conclusions; shows uncertainty and missing data; shows freshness and as-of timestamps; preserves before/after state for material changes; uses an append-only audit chain; minimizes participant data in the demonstration schema. Use a visual evidence-provenance or audit-chain animation showing actor, action, reason, timestamp, and linked history — this is the "monospace evidence chain" text-art idea from §6.1.2, given its proper home.

**8.4.7 Honest proof points.** Because the repository uses synthetic data, never invent customer logos, patient outcomes, regulatory approvals, or production claims. Use truthful proof points instead: synthetic data is clearly labelled; material mutations are written to the audit trail; pattern detection stops at human review; SQLite and Postgres boundaries are defined; FHIR and SDTM demonstration shapes exist.

**8.4.8 About.** Project context and intended audience; the AYUSH clinical-research and pharmacovigilance demonstration context; the design goal of operational clarity in safety-critical work; high-level architecture; the difference between this demonstration and production software; deliberate non-goals and future boundaries (§11). Do not imply institutional affiliation, clinical validation, or production approval without verified authorization.

**8.4.9 FAQ and boundaries.** Answer: Is this production clinical software? Is the data real? Does it replace medical judgement? Which dictionaries are used (curated vocabulary — not MedDRA/WHODrug, §1.1)? How are permissions enforced? What does audit-chain verification guarantee (and not guarantee)? Which integrations are demonstrated? What should users do when data is incomplete, stale, conflicting, or urgent? Use progressive disclosure and plain language.

### 8.5 Research and evidence reference presentation

The public product story and investigation workspace must not treat research as anonymous decorative copy. When showing literature, historical trials, protocol documents, or curated evidence, display source title, source type, provenance, date/version where available, retrieval method, and whether the item is synthetic, curated, or externally sourced.

The investigation experience should provide a focused evidence/reference surface with: search query and retrieval timestamp; source cards with citation/provenance metadata; distinction between lexical retrieval, concept expansion, and fused ranking (all three are genuinely computed by `app/retrieval.py` — surface all three, since the point of a fusion step is being able to see what it changed); a visible path from a source card to the evidence object or case decision it supports; an explicit "not a medical conclusion" boundary.

Do not fabricate DOI numbers, publications, customer evidence, clinical outcomes, or literature links. `AYU-008` and its constituents, historical trials, and literature are invented for this repository (`README.md:135-137`) — every corpus document carries its provenance, and the UI must keep that provenance visible, never presenting the synthetic corpus as real clinical evidence.

### 8.6 Imagery and assets

Prefer product UI, evidence graphs, timelines, document thumbnails, maps, and data visualizations over generic medical photography. The final landing page must include at least one purposeful visual asset beyond the logo: a high-fidelity product preview, evidence graph, timeline illustration, map/data visualization, or one properly licensed photo with a clear narrative role. Prefer the product preview plus typography-led text art (§6.1.2). Photography is optional in addition to that requirement; if used, it must have a narrative reason, appropriate license, no patient-identifiable content, and no implication of an unverified clinical relationship.

Avoid: generic smiling-doctor stock photos, fake hospital scenes, decorative heart-rate lines, medical crosses, abstract blobs, unlicensed imagery.

Every informative image needs meaningful alt text and, when needed, a visible caption. Decorative imagery gets empty alt text and cannot carry essential meaning. Keep attribution/licensing records. Optimize assets, lazy-load below-the-fold media, avoid background video on mobile, and provide a poster/static fallback for any video.

### 8.7 Landing interactions

Purposeful interaction only: scroll-driven product walkthrough; clickable role lens; evidence-chain reveal; product preview state changes; short hover/focus response; optional interactive diagram. Do not use continuous pulsing, random particles, decorative parallax, automatic safety-critical carousels, or motion as the only carrier of meaning.

With JavaScript disabled, show all stages as readable ordered HTML. With reduced motion, show the selected stage immediately. Keyboard users need direct controls, focus movement, active-stage announcements, and deep links to every stage. Any auto-playing sequence needs pause/stop controls (§6.1.3 repeats these as hard constraints — they apply everywhere text-art or scroll-driven treatment is used, not just here).

### 8.8 Final CTA and footer

End with: Explore the demonstration; Sign in; Read documentation; Read About/trust content; repository or architecture link if appropriate. Footer includes product identity, About, docs, trust/safety, accessibility, contact/project owner if available, and the synthetic-data notice.

---

## 9. Authenticated shell and role-aware Operations Home

### 9.1 Objective

After login, users should land in useful work, not product explanation. This is the direct fix for "there is no home page" (§0.1) — technically there is an authenticated overview and a login screen; what's missing is the deliberate public home → sign-in → authorized workspace journey.

### 9.2 Shell — persistent elements

- Product mark.
- Environment badge such as `Sandbox` or `Demonstration`.
- Current workspace name.
- Global search / command palette (§7.4) for study ID, case ID, subject code, signal term, protocol number, or audit sequence.
- Priority inbox/notifications where supported.
- Data freshness and as-of timestamp.
- Help/terminology access.
- User name, actual role, scope, and logout.
- Mobile navigation drawer.

A workspace switcher is available only to accounts actually entitled to multiple workspaces/lenses (§5). Do not expose a global "view as any role" switch in the production experience — that is a demo-mode-only affordance, clearly labeled as such if it exists at all.

### 9.3 Operations Home

**Header:** user display name; actual role and scope; current time and relevant clinical timezone; data freshness; a plain orientation statement such as "Your safety operations for today."

**Primary blocks:** critical unresolved work; overdue work; due today; assigned to me *(only once real assignment data exists — see §9.3.1)*; recently changed; studies/cases at risk; upcoming milestone or deadline; activity and handoff history.

**Suggested structure:**

```text
+-------------------------------------------------------------+
| Good morning, [name]   Safety operations · as of [time]     |
| [2 Critical] [5 Due today] [12 Assigned] [Data current]     |
+-------------------------------+-----------------------------+
| Priority queue                | Recent activity             |
| Serious case · 6h remaining   | Decision recorded           |
| Signal awaiting review        | New case received            |
| Enrollment lag                | Audit chain verified         |
+-------------------------------+-----------------------------+
| My studies / cases / actions                                |
+-------------------------------------------------------------+
```

Unresolved risk gets priority over total activity — an ordered priority queue (priority, reason for priority, study/site, responsible person, due basis, current status, next action), not six equal-weight KPI cards competing for attention. Do not show inaccessible leadership links or actions to a user who cannot open them (§0.1, point 3; §5).

#### 9.3.1 "Assigned to me" is a claim, not a label

Do not ship "Assigned to me" until actual assignment data exists in the schema. Until then, label the view "Within my authorized scope" or another accurate description. This single naming discipline point prevents the product from claiming a capability (task ownership) that §1.2 and §5.1 both flag as backend-dependent across several roles.

Users need to distinguish **no work**, **no matching results**, **no access**, **data not loaded**, and **source unavailable** — none of those should silently render as zero (§10.1 formalizes this).

### 9.4 Role workspaces

See §5.1 for the full role/question/gap table. Each workspace listed there gets its own composition, not a shared KPI-wall template with swapped labels — that reuse-without-differentiation is exactly the "views are tabs" complaint from §0.1.

---

## 10. Work queues, study workspace, and scalable interaction

### 10.1 State behavior — define before implementation, not after

This table consolidates every state contract referenced elsewhere in this document into one place, because inconsistent state handling was named directly as a current defect (§3):

| State | Behavior |
|---|---|
| **Loading** | Preserve context; use region-specific skeleton/progress feedback, not a full-page blank. |
| **Stale** | Keep last known values visible, label stale, show as-of time, provide refresh/retry. |
| **Connection loss** | Never present old data as current; preserve unsaved form input where safe. |
| **Error** | Say what failed, whether the action completed, and how to recover. |
| **Permission** | Distinguish not authorized, read-only, out of scope, and missing workflow data — four different reasons a user sees nothing, four different messages. |
| **Empty** | Distinguish no records, no filter matches, no permission, and not-loaded-yet; show the next action either way. |
| **Session expiry** | Explain, preserve safe return path, warn before discarding unsaved work. |
| **Material mutation** | Confirm where necessary, capture reason when required, show resulting state, link the audit entry when available. |

If freshness metadata is unavailable, show `as of page load` rather than pretending to be real-time. Configure freshness thresholds rather than hardcoding them in templates.

### 10.2 Queue system

Apply the same reusable queue pattern (§6.4, §7.2) to portfolio alerts, AE cases, signals, study issues, submissions, and audit events.

Required: search; filter by severity, owner, study, product, status, date, deadline, and confidence; sort by risk, deadline, age, recency, or owner; saved views only when persistence is backend-supported (do not fake durable state in local storage — §1.2, §11); URL-preserved filter state; result count and active-filter summary; pagination or explicit load-more; column selection where appropriate; row quick actions; bulk actions only with scope preview, permission check, confirmation, and partial-failure feedback; keyboard navigation; mobile row detail; loading/empty/error/stale/permission states (§10.1).

Every row should show enough context to decide whether to open it: priority/severity label; status; owner/unassigned state; due time or age; identifier; one-line reason; next action.

### 10.3 Study workspace

Replace the long vertical study page with a persistent context header: title; study ID and protocol number; phase, area, PI, CTRI state; overall health; last updated/as-of time; primary next action.

Recommended focused subviews: Overview; Enrollment; Sites and monitoring; Safety; Deviations; Queries; Milestones (rendered with `app/timeline.py`'s geometry, once validated — §1.1, §6.4); Activity/audit.

Tabs are allowed only when they represent real information architecture — a study genuinely has an Overview, Sites, Safety, etc. as sections of one entity. Do not use tabs as a substitute for a view hierarchy, and do not use them to paper over the fact that different roles need genuinely different destinations (§0.1, point 3; §5). Each subview needs its own purpose and density.

- **Overview:** exceptions and next milestone before descriptive metadata.
- **Timeline:** milestones, monitoring activity, and approval expiries on a shared scale. Show planned vs. actual only where both are stored.
- **Sites:** comparable rows and drill-down, not decorative map pins.
- **Enrollment:** dated observations and plan definitions. Do not fabricate historical curves from one current total.
- **Queries/Deviations:** open detail, owner, evidence, and resolution history when implemented.

### 10.4 Responsive data behavior

At 390px, without expanding a row, keep priority/severity, identifier, one-line reason, owner/unassigned state, and due time/status visible. Filters may move into a drawer. Simplify or disable bulk actions when scope cannot be made unambiguous.

Use tables only where bulk comparison is truly useful. On mobile, use readable record cards or expandable rows rather than forcing every table into a tiny horizontal viewport. Container queries (§6.2) drive this at the component level; viewport breakpoints drive the shell-level decisions (sidebar collapse, drawer vs. inline panel).

---

## 11. Case, signal, investigation, evidence, and audit workflows

### 11.1 Objective

Make the clinically meaningful flows complete, connected, and reusable rather than hardcoded demonstrations (§0.1, point 4).

### 11.2 Adverse-event workflow

Evolve the current AE page into:

```text
New case
 -> validate required fields
 -> triage
 -> coding review
 -> medical assessment
 -> regulatory submission where supported
 -> follow-up
 -> closure
```

Case workspace must include: persistent case ID, severity, and workflow status; 24-hour/14-day clock panel (the statutory clocks already computed in `app/pv.py`); owner and assignment history where supported; study and pseudonymous subject context; narrative; structured fields; coding term/code/confidence/source (via the request-body coding endpoint, §7.3 — never the current GET route); missing/conflicting data; timeline; related/possible duplicate cases; submission status only where tracked; follow-up status only where tracked; review controls; audit history.

When a user files an event, explain what is created, which clock begins, which fields are incomplete, and who owns the next step. Do not silently infer or finalize a clinical conclusion.

### 11.3 Signal workspace

Every flagged signal should lead to a reusable signal detail and investigation path — not silently reuse the one hardcoded demonstration case (§1.2).

Show: signal definition; study and term; case count; denominators and exclusions; time range; PRR and threshold; study/site distribution where meaningful; data-quality caveats; review state; assigned reviewer where supported; decision history.

Actions may include open investigation, assign reviewer, request evidence, mark monitoring, escalate, and record decision — but only where backend permissions and audit paths exist. "Open investigation" should work only where a case exists; a generalized "Create investigation" needs an explicit case model and permissions. The existing single-case guard (`main.py:661-662,706-707,735-736`) must not be hidden behind a button that silently redirects every signal to the same demonstration case — either the button is disabled with an honest reason, or the case model is generalized first.

### 11.4 Investigation workspace — the signature experience

Generalize the current single-case board around:

```text
Signal detected
 -> case evidence
 -> study/site context
 -> literature and historical evidence
 -> human assessment
 -> decision and rationale
 -> audit record
```

Use a deliberate evidence-to-decision composition, following the concept in `media-output/img-mu2jfp8n-971c7eba.png` as a starting point (source panel → relationship graph/timeline → decision record), rebuilt on the real token system:

- **Sources:** protocol excerpts, event reports, relevant literature, and study history with provenance/version/date.
- **Evidence view:** related events and source relationships, plus a timeline and tabular alternative — the graph is never the only way to see the same information.
- **Decision record:** reviewed evidence, explicit uncertainty, authorized decision options, rationale, identity, confirmation.

Selecting a source should highlight where it is used. Selecting an event should preserve study context. Retrieval results should explain why they matched (lexical / concept-expansion / fused — all three are real, §8.5) and expose the original source text. Keep technical ranking comparisons in an expandable "How this was retrieved" panel rather than requiring every clinician to study retrieval mathematics up front.

Graph edges must be labeled as relationships, not causation. Provide a non-graph evidence list and full keyboard navigation as co-equal alternatives, not a fallback bolted on afterward. A dark evidence canvas (as in the concept render) can be an optional focused mode — it is not a reason to force the whole product into dark mode, and its contrast, icon-only rail, and small caption text need an accessibility pass before implementation, not after.

Do not build a general AI chatbot first. The more valuable assistant behavior is to explain a coding suggestion, retrieve a traceable source, or summarize what changed with links back to evidence. Any generated summary remains visually distinguishable from source material and requires review before it is treated as final.

Each evidence object identifies source, provenance, timestamp, reported/derived/inferred/pending status, and a link to the underlying record. Use progressive disclosure for secondary evidence. Never hide severity, deadline, uncertainty, or requested action behind a disclosure toggle.

**Decision states:** Draft; Under review; Concurred; Returned; Escalated; Closed. Every decision requires a named actor, timestamp, and reason through the existing audited mutation path (`main.py:695-703`, already correctly implemented as a form-body POST — the model to follow elsewhere, §7.3).

### 11.5 Audit center

Make audit a first-class quality workspace, replacing "a wall of hashes" with human-readable event summaries and expandable technical detail: actor, role, object, action, timestamp, reason, before/after where applicable, and chain linkage. Show chain status, the result and timestamp of a specific verification run, sequence, and linked case/study where supported.

**"Chain verified" means integrity checks passed for the examined records — not that the clinical content is true, access control is complete, or the product is legally compliant.** Keep this precise guarantee language exactly; never imply chain verification certifies the whole organization or deployment.

Give filters, clear result limits, and pagination. Auditable exports need authorization, scope, export-event recording, and failure states. Do not show an "inspection-ready" completion badge without defining exactly what was checked.

---

## 12. Healthcare constraints that shape the design

### 12.1 Clinical meaning and human authority

- Seriousness, severity, reporting urgency, and clinical priority are different concepts. Give them separate fields and labels (§2 formalizes this as the four-concern separation).
- Do not translate a vocabulary-match score into clinical confidence.
- Do not infer causation from disproportionality or a visual link between events.
- Record source, version, original narrative, coding method, reviewer, and correction history.
- Validate reporting triggers, recipients, and applicable rule sets with qualified clinical/regulatory stakeholders. Existing demo summaries are not an authoritative legal specification.
- A missed deadline must remain historically visible even after follow-up work is completed.

### 12.2 Privacy and authorization

- Decide the intended read-access policy explicitly: shared institutional oversight versus assigned study/site scope. Enforce that policy at server/API/export level, not only in navigation.
- Keep unauthorized data out of search, counts, notifications, previews, and exports — not just detail pages.
- Use pseudonymous identifiers consistently. Free-text fields can still contain identifying information even when the structured schema has no name field.
- Do not place clinical narratives in URLs, third-party analytics payloads, or browser persistence by default — this is precisely the `GET /api/pv/code` defect fixed in §0.1/§7.3; treat it as the template for every future field carrying narrative text.
- Plan session-expiry warnings, safe draft handling, and shared-workstation behavior.
- Public demo credentials belong only to a demonstrably synthetic, isolated environment. Verify deployed secrets and configuration separately — the repository does not prove current production values.

### 12.3 Alert fatigue

Excessive warnings desensitize users; severity tiering and reserving interruption for high-severity alerts is well-established human-factors guidance (AHRQ PSNet's alert-fatigue primer, last reviewed 2024 — treat as general orientation, not a current implementation standard). This supports the restrained, queue-first design in §9.3 and §10.2, not an always-blinking command center.

Deduplicate related alerts, explain their cause, identify an owner, and make acknowledgment distinct from resolution (§2's four-concern separation again). Do not automatically suppress regulated obligations merely to make a dashboard greener — escalation/suppression policies need clinical governance, not a design decision.

### 12.4 Resilience

A disconnected application must not imply that a clinical write was submitted. Use explicit retry paths and preserve entered data only through an approved storage model. Distinguish stale cached reads from current data (§10.1). Do not offer offline clinical writes until synchronization, conflict handling, and audit integrity are designed.

---

## 13. Quality, accessibility, performance, and verification

### 13.1 Language and trust copy

Use language equivalent to:

- `Synthetic demonstration data — not for patient care or clinical decision-making.`
- `VITalWatch supports review and coordination; it does not replace qualified medical, regulatory, or ethics judgement.`
- `A detected signal is a hypothesis for human investigation, not proof of causality or incidence.`
- `Reporting clock started at [timestamp] and is shown in [timezone]. This view does not prove that an external authority received a submission.`
- `Audit-chain verification confirms the integrity and order of stored audit records in this demonstration. It does not by itself certify the organization, deployment, permissions, source data, or regulatory compliance.`

Do not claim the product is a medical device, clinically validated, production-approved, or compliant with ISO 27001 or any law/standard unless independently verified and approved.

Consolidate this language into one shared notice component (§6.4) so it cannot drift into contradiction the way `home.html` and `base.html` currently do (§0.1, point 2). Keep a compact persistent synthetic-data indicator with contextual detail on demand; stop repeating long implementation disclaimers above every working screen — the warning stays clear without competing visually with an actual safety warning.

### 13.2 Display rules

- `0` means measured zero.
- `—` means not applicable/no defined value.
- `Unknown` means missing or unevaluable source.
- `Pending` means expected workflow step not complete.
- `Stale` means older than declared freshness threshold.
- `Insufficient data` means denominator or minimum case threshold is not met.
- Never fabricate a percentage when denominator is zero.

Deadline displays must show source timestamp, deadline timestamp, timezone, and current as-of time. Preserve backend clock semantics; do not invent pause/restart/business-day behavior. If input is unreadable, show `Deadline unknown — review required` and name the missing input.

### 13.3 Accessibility

Target WCAG 2.2 AA-oriented quality as a proposed evaluation target — do not claim conformance before testing:

- Correct contrast.
- Visible keyboard focus (the existing `:focus-visible` rule in `app.css` using the reference color is correct — keep the pattern, verify contrast against every surface it lands on).
- Full keyboard access for navigation, filters, dialogs, queues, tables, command palette (§7.4), and walkthroughs.
- Logical landmarks/headings.
- Labels for icon-only controls.
- Text paired with color states (§6.3 — never color alone).
- Screen-reader status announcements for live-updating regions (queue changes, inspector state, palette results).
- Adequate hit areas.
- No essential hover-only information.
- Inline errors with recovery instructions.
- Correct accessible expanded/collapsed state on every disclosure, drawer, and inspector.
- Reduced-motion support everywhere motion is used (§6.1.3, §7.5).
- Critical information preserved on mobile (§10.4).

Desktop: queue + inspector. Tablet: collapsible navigation, fewer visible secondary columns. Phone: focused list and full record detail rather than squeezing a desktop graph sideways. Critical record identity, status, and next action remain available everywhere; complex comparison can favor larger screens without making essential review inaccessible on smaller ones.

### 13.4 Performance and implementation quality

The app remains server-rendered with progressive enhancement. Where client-side JavaScript is added:

- Avoid request waterfalls.
- Defer non-critical third-party scripts — and remove the CDN Tailwind/Google Fonts dependency entirely (§6.1.1) rather than just deferring it.
- Load heavy interaction modules (command palette, evidence graph) only when activated.
- Keep static content server-rendered where possible.
- Avoid unnecessary re-renders and global listeners.
- Lazy-load below-the-fold media.
- Do not use WebGL or large particle systems for essential landing content.
- Prefer local, self-hosted assets/fonts (§6.1.1) or a clear offline fallback.
- Keep operational pages fast and predictable.

### 13.5 Browser verification

Verify at 1440px desktop, 1024px tablet, 390px mobile, across a Chromium-based browser and one additional evergreen browser (test scroll-driven-animation and container-query fallbacks specifically on the second browser, per §6.1.2 and §6.2's noted support gaps).

Check: no uncaught console errors on primary routes; no page-level horizontal overflow except intentional data-region scrolling; safe login redirects; correct role-filtered navigation; forbidden/read-only states; forms, filters, search, detail links, back links, and confirmation flows; landing walkthrough with keyboard, reduced motion, and JavaScript-disabled fallback; loading, stale, error, empty, connection-loss, and session-expired states (§10.1); screenshots or recordings of the public landing page, Operations Home, one case workspace, one investigation, and mobile navigation; no unsupported clinical/regulatory/production claims; existing security, CSRF, role restrictions, audit writes, API, and export contracts remain intact.

---

## 14. Capability boundaries

Before building each feature, classify it (§5's per-role table applies this same discipline; this is the product-wide summary):

| Capability | Current repository evidence | Treatment |
|---|---|---|
| Role-aware access | Auth middleware, role permissions, lens access (`app/auth.py`, `main.py:163-168`) | Build now; generate navigation/actions from capability, not a hardcoded list |
| Portfolio/study metrics | KPI and role modules (`app/kpi.py`) | Build now; redesign presentation and add queue controls |
| AE intake and clocks | Existing form, coding, clocks, audited write (`app/pv.py`, `main.py:891-1016`) | Build now as staged UI; do not invent external receipt |
| AE assignment/follow-up/closure | Not fully established | Backend-dependent; no fake persistence |
| PRR signals | Existing detection route (`app/signals.py`) | Build now; connect to investigation carefully (§11.3) |
| Reusable investigations | Current case is heavily specific (`app/case_data.py`) | Presentation can generalize; persistence is backend-dependent |
| Saved views/notifications | Not established | Backend-dependent; do not fake durable state in local storage |
| Audit chain | Existing append-only verification (`app/audit.py`) | Build now with precise guarantee wording (§13.1) |
| Submission center | Not established | Future concept until schema/routes/audit exist |
| FHIR/SDTM export | Existing demo endpoints (`app/fhir.py`, `app/sdtm.py`) | Build truthful export/provenance affordances |
| Study timeline | Computed, unimported (`app/timeline.py`) | Build now after validating inputs/geometry — do not assume unused code is production-ready as-is |
| Coding-assist live preview | Existing coding function, unsafe transport (`main.py:874-875`) | Build now, but only behind a new request-body endpoint (§0.1, §7.3) |

The schema needs to separate clinical facts from workflow metadata. Role configuration may select navigation and capabilities; it must not conceal missing domain models behind configuration strings.

---

## 15. Anti-patterns — do not ship these

- Generic purple/blue SaaS dashboard styling.
- Marketing gradients replacing information hierarchy.
- Stock doctor photography without a narrative purpose.
- Emoji as semantic status icons.
- Random particle/text effects that reduce readability.
- Auto-playing content with no pause or static fallback.
- Equal-weight KPI cards for unrelated risk levels.
- Tabs used to hide an unclear information architecture.
- Fake live data, fake notifications, fake saved views, or fake submission status.
- Disabled buttons that do not explain why an action is unavailable.
- Hiding unauthorized items as if hiding were security.
- Claims of regulatory compliance, clinical validation, or patient-care readiness.
- Silent overwrite of material clinical or compliance information.
- Unexplained "AI" labels or conclusions.
- A landing page that is only a hero and a feature grid.
- An authenticated home page that is only an introduction.
- A patient portal, wearable/vitals graphics, or generic chatbot bolted onto a staff-oversight product (§5.1).
- A wholesale backend rewrite undertaken to fix a presentation problem.
- Clinical narrative text transmitted via URL query string (§0.1, the one mandatory security fix in this brief).

---

## 16. Six-phase implementation plan

Each phase has an explicit exit gate. Do not start the next phase until the current one's gate is met — this is what prevents visual polish from shipping over structural problems, which is the single biggest root cause of the "AI slop" feedback (§0.1).

### Phase 1 — Product truth, route inventory, and design system

**Objective:** create the foundation that prevents visual polish from hiding structural problems, and reconcile the product's contradictions about itself before any redesign work begins.

**Required work:**

- Reconcile stale UI/docs claims (§0.1, point 2; §1.2's table) — every visible action and promise gets classified as implemented, planned, or demonstration-only.
- Inventory every existing route, template, data context, permission gate, form, API call, export, and audited mutation (§1.1, §1.2 as the starting inventory — extend it, don't restart it).
- Define the route model (§4, §4.1) and document which convention is chosen.
- Build the design token system (§6.3) and resolve the indigo-dual-meaning contradiction explicitly in writing.
- Choose and license the three-role type system (§6.1), set up self-hosted delivery with correct fallback metrics (§6.1.1).
- Build the shared component/macro layer (§6.4).
- Create the existing-view preservation map (below) before deleting, merging, or renaming anything.
- Distinguish demo mode from intended operational mode; choose a deterministic demo clock or explicitly dated snapshot.
- Map role jobs to existing versus missing capabilities (§5.1, §14).

**Exit gate:** every visible action and promise is classified as implemented, planned, or demonstration-only. No universal home link points users into a forbidden lens. No application behavior is made less secure during this phase.

**Deliverables:** route and capability matrix; design tokens; shared component/macro layer; public and authenticated shell plan; approved content/claim inventory; backend-dependent feature list.

**Existing-view preservation map** — no meaningful existing capability may disappear simply because the new landing page or dashboard looks better:

| Existing surface | Required treatment |
|---|---|
| `home.html` | Split into public landing content and authenticated Operations Home; retain truthful About/system content elsewhere |
| `login.html` | Redesign as the polished authentication gateway with safe role-aware redirect |
| `portfolio.html` | Redesign as portfolio overview plus reusable risk queue |
| `study.html` | Redesign as persistent-context study workspace with focused subviews |
| `role.html` | Preserve investigator/safety/leadership domain lenses inside capability-aware workspaces; promote the `<select>` to a real switcher |
| `ae.html` | Split into case queue, staged intake, and case workspace where backend support exists |
| `signals.html` | Redesign as signal queue plus signal detail/investigation entry |
| `investigation_case.html` | Preserve as investigation entry/context, generalized beyond one hardcoded case where possible |
| `investigation_board.html` | Preserve the evidence-driven concept, replacing hardcoded narrative and emoji with reusable evidence components |
| `audit.html` | Redesign as quality/audit center with precise chain guarantees |
| `base.html` and `_macros.html` | Split public/authenticated shells and centralize reusable primitives; remove the CDN Tailwind/Google Fonts dependency |
| `app.css` | Refactor into the new token/component system without losing focus, semantic states, or responsive behavior |

Every current route must be retained, redesigned, redirected, or intentionally deprecated with a documented reason.

### Phase 2 — Public landing page

**Objective:** ship the full landing page defined in §8, built on the Phase 1 token system, not a placeholder hero-plus-grid.

**Required work:** hero with real product preview (§8.4.1); Why/What/How-it-works sections with the text-art treatment (§8.4.2-8.4.4, §6.1.2); role-based value selector (§8.4.5); trust/safety section with the evidence-chain visual (§8.4.6); honest proof points (§8.4.7); About (§8.4.8); FAQ/boundaries (§8.4.9); imagery per §8.6; interactions per §8.7 with all required fallbacks (§6.1.3); final CTA and footer (§8.8).

**Exit gate:** a first-time visitor can explain, unprompted, why VITalWatch exists, what it does, who it's for, and what is and isn't real — without a narrated demo. The page works fully with JavaScript disabled and with reduced motion enabled. No invented proof points, logos, or claims appear anywhere.

### Phase 3 — Authenticated shell and role-aware Operations Home

**Objective:** ship the shell (§9.2) and Operations Home (§9.3) so signed-in users land in useful work, not product explanation.

**Required work:** persistent shell elements including command palette (§7.4, §9.2); Operations Home header and priority-first layout (§9.3); the "assigned to me" naming discipline (§9.3.1); at least one fully differentiated role workspace beyond the default (§5.1, §9.4) to prove the pattern generalizes, not just look right for one role.

**Exit gate:** users can identify critical, overdue, due-soon, assigned/in-scope, and recently changed work without opening multiple pages. No user is promoted to a role lens or action they cannot access. Signed-in users land in a role-aware Operations Home, not the public landing page.

### Phase 4 — Work queues, study workspace, and scalable interaction

**Objective:** turn report-like tables into reusable operational views (§10), closing the "no filter/sort/search" gap named directly in §3.

**Required work:** the reusable queue pattern (§10.2) applied to portfolio alerts, AE cases, signals, and audit events; the study workspace with persistent context header and focused subviews (§10.3), including adopting `app/timeline.py`; responsive data behavior at 390px via container queries (§10.4, §6.2); the worklist + inspector interaction pattern (§7.2) built and wired to at least the safety/AE queue end-to-end.

**Exit gate:** portfolio, AE, signal, and audit views support practical filtering and sorting; durable features (saved views, bulk actions) are backed by real capability or explicitly absent, never faked. The inspector pattern works with keyboard only and with the side panel replaced by a full page at 390px.

### Phase 5 — Case, signal, investigation, evidence, and audit workflows

**Objective:** make the clinically meaningful flows complete, connected, and reusable (§11), directly resolving the hardcoded-single-case problem (§0.1, point 4; §1.2).

**Required work:** the full AE lifecycle (§11.2) including the request-body coding-assist endpoint (§0.1, §7.3 — the one mandatory security fix); the signal workspace with a real or honestly-disabled investigation entry point (§11.3); the investigation workspace as the signature experience (§11.4), generalized beyond `case_data.py` where feasible and clearly labeled demonstration-scoped where not; the audit center redesign (§11.5) with precise, non-overreaching guarantee language.

**Exit gate:** AE and signal records have clear paths into reusable detail/investigation workflows. Evidence distinguishes source records, derived patterns, uncertainty, human assessment, and final decision. The coding-assist feature, if shipped, never transmits narrative text via a URL query string. Study views have persistent context and real subview purposes rather than arbitrary tab stacks.

### Phase 6 — Quality, accessibility, performance, and verification

**Objective:** ship a coherent product, not a visually impressive but unsafe prototype (§12, §13).

**Required work:** all state contracts from §10.1 implemented consistently across every surface built in Phases 2-5; the trust-copy consolidation (§13.1) replacing the current contradictory disclaimers; display rules (§13.2) applied everywhere a value can be zero, unknown, pending, or stale; the full WCAG 2.2 AA-oriented accessibility pass (§13.3); font self-hosting and CDN removal completed if not already done in Phase 1 (§13.4, §6.1.1); the full browser verification matrix (§13.5).

**Exit gate:** the experience remains understandable with motion disabled, slow responses, no results, stale data, and expired sessions. Screenshots/recordings exist for the public landing page, Operations Home, one case workspace, one investigation, and mobile navigation. Existing security, CSRF, role restrictions, audit writes, API, and export contracts remain intact and verifiably tested, not just assumed unchanged.

---

## 17. Suggested evaluation tasks

Use these as concrete acceptance tests, not just design goals:

- Can each role reach its first meaningful task without first interpreting a portfolio KPI wall?
- Can a safety officer distinguish "needs review," "acknowledged," "reporting evidence recorded," and "recipient confirmed"?
- Can an investigator inspect the original source behind a suggestion and record a rationale without losing context?
- Can a monitor find the difference between a visit not conducted and a report not filed?
- Can a regulator inspect history and export only permitted records without seeing mutation controls?
- Do direct URLs, APIs, search, counts, and exports enforce the same scope?
- Can users identify stale data, unknown values, and failed writes instead of mistaking them for current/empty/successful states?
- Can essential flows be completed by keyboard and with reduced motion?
- Does the landing page communicate the full product story with JavaScript disabled?
- Is the clinical narrative ever visible in a URL, browser history entry, or server access log?

Measure observed task completion, errors, backtracking, assistance required, and understanding of state. Establish baselines before setting numeric targets; do not invent usability-improvement percentages.

---

## 18. Final acceptance criteria

The redesign is complete only when:

1. Unauthenticated visitors see a real landing page covering why, what, who, how, trust, About, boundaries, FAQ, and next steps.
2. The landing page has a meaningful product preview or equivalent accessible walkthrough.
3. Landing content uses intentional typography/text-art or purposeful product visualization, not decorative filler.
4. Images are licensed/attributed where necessary, accessible, optimized, and never patient-identifiable.
5. Public and authenticated routing is explicit and safe.
6. Signed-in users land in a role-aware Operations Home.
7. Users can identify critical, overdue, due-soon, assigned, and recently changed work without opening multiple pages.
8. No user is promoted to a role lens or action they cannot access.
9. Portfolio, AE, signal, and audit views support practical filtering and sorting; durable features are backed by real capability.
10. AE and signal records have clear paths into reusable detail/investigation workflows.
11. Evidence distinguishes source records, derived patterns, uncertainty, human assessment, and final decision.
12. Study views have persistent context and real subview purposes rather than arbitrary tab stacks.
13. Loading, empty, error, stale, success, forbidden, connection-loss, and session-expired states are designed.
14. Critical information is understandable on 390px mobile.
15. Status is never communicated by color alone.
16. Motion respects reduced motion and never carries the only meaning.
17. Synthetic data and prototype boundaries remain truthful without overwhelming daily work.
18. Audit, CSRF, authentication, authorization, API, and export behavior remain secure and intact.
19. No unsupported clinical, regulatory, compliance, or production claims appear.
20. Every existing meaningful frontend view/template is mapped to a retained, redesigned, redirected, or intentionally deprecated destination.
21. Operational metrics, queue content, permissions, deadlines, filters, and statuses are backend-driven or clearly marked deterministic synthetic fixtures.
22. Research/evidence displays include provenance and citation metadata without fabricated sources.
23. The landing page includes purposeful visual media beyond the logo and preserves accessible fallbacks.
24. Browser and accessibility verification is completed with evidence.
25. The `GET /api/pv/code` narrative-in-query-string defect is closed before any live coding-assist UI ships.
26. Fonts are self-hosted with metric-matched fallbacks; the CDN Tailwind/Google Fonts dependency is removed.
27. Every documentation/UI contradiction identified in §1.2 is resolved and does not reappear in the shipped copy.

---

## 19. Final design standard

Make VITalWatch memorable because its design comes from the real subject matter: evidence, reference lines, timelines, risk, accountability, and the transition from detection to human decision.

Use one bold signature — typography-led evidence storytelling (§6.1.2) and a product preview that visibly moves from signal to action (§8.4.1) — and keep the rest disciplined. Direction B (research editorial) explains and explores the product; Direction A (clinical clarity) performs daily work. They share one design system, one component library, and one set of semantic colors — they are not two arbitrary paint jobs of the same dashboard.

The final frontend should be something a visitor can understand, a clinical operations team can use repeatedly, and a reviewer can inspect without being misled.
