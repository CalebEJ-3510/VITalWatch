# Phase 1 — Backend-dependent feature list & role-capability map

Features the UI may **not** fake (prompt.md §9.3.1, §11, §14): anything listed here
needs schema/route/permission/audit work before a pixel promises it. Each item names
what exists, what's missing, and the honest interim treatment.

## Backend-dependent features

| Feature | What exists today | What's missing | Honest interim treatment |
|---|---|---|---|
| "Assigned to me" work view | Role lenses, per-PI scoping for `principal_investigator` | No assignment/owner field on any record; no task model | Label the view **"Within my authorized scope"** (§9.3.1) until an assignment schema + audited assignment writes exist |
| AE lifecycle beyond intake | Intake + coding + clocks + audited CREATE | Coding corrections, acknowledgment, follow-up, closure, assignment — each needing audited mutation semantics | Case workspace shows intake facts; lifecycle controls ship only with the schema |
| Submission-evidence recording | Clock computation (`deadline_24h/14d`) | No fields for recipient, submitted-at, method, proof; no audited write | UI states explicitly: "this system does not record that an authority received a filing" (already in `ae.html` — keep) |
| Reusable investigations (multi-case) | One hardcoded case (`case_data.py`) + guards at `main.py` 661/706/735 | Case model: table, permissions, audited creation | Signal → investigation button disabled with honest reason unless the one case is the target |
| Saved views / notifications | Nothing | Persistence + per-user storage | Absent — never faked in localStorage (§1.2) |
| Command palette / global search | — | Server-side permission-filtered search endpoint (study/case/subject/signal/protocol/audit-seq) | Phase 3: endpoint + palette together; results filtered server-side (§7.4) |
| Ethics-committee workflow | `ethics_committee` role → leadership lens (named mapping) | Approval/renewal queue semantics, document versions, committee decisions | Lens mapping is labelled on the page; no renamed-leadership fakery |
| Monitor visit/report workflow | Monitoring visits in schema, overdue rule | Report-filing interaction, visit completion writes | Read-only status display; "not conducted" vs "report not filed" distinguished in copy where data supports it |
| Admin user provisioning | Seeded demo users | User management routes + audit | Absent from UI |
| Regulator export auditing | FHIR/SDTM demo exports | Export-event recording, scope-limited dossier packaging | Exports remain demo-labelled; regulator sees no mutation controls (enforced today) |
| `timeline.py` adoption | Milestone/deadline geometry computed, unimported | Input/geometry validation pass before use | Phase 4: validate, then render in study workspace; otherwise document deferral reason |
| Retrieval `q` transport | `GET /api/investigation/{id}/retrieve?q=…` | Nothing today — corpus queries are not narrative-bearing | Flag stands: if `q` ever carries clinical narrative, move to request body first (§7.3) |

## Role → capability map (verified against `ROLE_LENS_ACCESS`, `AE_WRITE_ROLES`, `DECISION_WRITE_ROLES`)

| Role | Lens access | Write gates | Deterministic default workspace (Phase 3 target) | First-screen question (§5.1) |
|---|---|---|---|---|
| principal_investigator | investigator (scoped to own `pi_name`) | file AE, record decision | Investigator workspace | Which study risks require intervention today? |
| study_coordinator | investigator | file AE | Coordinator view of investigator lens + AE intake shortcut | What do I need to complete or correct? |
| monitor | investigator | none | Monitor view (site/deviation emphasis) | Which site needs review, and what evidence is missing? |
| ethics_committee | leadership | none | EC view (renewals, related safety/deviations) | What needs ethical review or follow-up? |
| pharmacovigilance | safety | file AE, record decision | Safety workspace (reporting worklist first) | Which event or reporting obligation requires attention next? |
| administration | all three | none (by design: oversight, not conduct) | Portfolio/administration home | Where is the portfolio blocked? |
| regulator | all three | none (read-only by construction) | Read-only dossier view | Can I trace what changed, who changed it, and why? |

Notes the UI must honor:

- Two roles (`study_coordinator`, `ethics_committee`) have no bespoke lens; the
  current mapping to the nearest lens is **named on the page**, and Phase 3/5 either
  builds their workspaces or keeps the honest mapping — never a silent relabel.
- `administration` and `regulator` both see all lenses but for different reasons;
  only a role with >1 lens ever sees a switcher (§5, §9.2).
- A role's *default* must be deterministic: the single permitted lens, else
  leadership-as-portfolio-overview, else a designed read-only home with an access
  explanation.

## What Phase 1 proved is already strong enough to build on (§1.3)

Computed KPIs/alerts/clocks/signals, session auth + RBAC + CSRF, the append-only
audit chain with database-level UPDATE/DELETE refusal, three-way retrieval
transparency, live chain verification on every `/audit` load, and the audited
decision path whose form-body pattern (`main.py` 695-703) is now the template for
the new coding endpoint.
