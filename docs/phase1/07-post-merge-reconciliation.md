# 07 — Post-merge reconciliation addendum (2026-09-16)

**This addendum supersedes the route inventory, role model, and account names
in 01–06 wherever they disagree.** Documents 01–06 remain the historical
record of Phase 1 as built against the pre-merge backend; this note is the
re-verified truth after the backend merge (commit `2238e6f`).

## What the merge changed underneath Phase 1

- **Seven roles → five primary roles** (`app/models.py::UserRole`):
  `volunteer`, `company`, `investigator`, `safety_officer`, `leadership`.
  `LEGACY_ROLE_ALIASES`/`parse_role` is a one-way read-time migration shim
  for old rows, not a sixth role. Demo accounts are now one per role:
  `volunteer.demo`, `company.demo`, `investigator.demo`, `safety.demo`,
  `leadership.demo` (see `app/datagen.py::DEMO_USERS`; passwords unchanged
  where the account survived: `AiiaTrialLead#01`, `AiiaSafety#01`, …).
- **Lens routes gone**: `/home`, `/role/{id}`, `/portfolio`, `/investigation*`,
  `/study/{id}`, `/api/alerts`, `app/roles.py`. The authenticated front door
  is `GET / → 303 /portal/{role}` (`app/main.py::home`).
- **Feature deletions (§1.1.1)**: investigation board + evidence retrieval
  (`investigation.py`, `retrieval.py` — BM25/concept-expansion/RRF), FHIR/SDTM
  exports (`fhir.py`, `sdtm.py`), `timeline.py`, `rehearse.py`. None may be
  referenced by UI copy, gates, or docs as a capability.
- **Signature workflow**: the escalation / statutory-clock / corrective-action
  / leadership-decision state machine in `app/governance.py` (routes
  `/escalations*`) — this is what the redesign anchors on, replacing the
  deleted investigation board in that role.

## Re-verified route inventory (smoke-gate enforced)

The §4.1 table in `prompt.md` is the canonical list; `scripts/smoke_phase1.py`
(91 checks) and `scripts/smoke_phase3.py` (97 checks) now enforce the parts
the old gate covered, against the five-role backend:

- Public: `/`, `/about`, `/login`, `/health`, `/robots.txt` — everything else
  303s to `/login` (pages) or 401s (API).
- One dashboard per role at `/portal/{role}`; cross-role access 403s
  server-side and is never offered in nav (asserted per role).
- `/audit` and `/search` are Leadership-only; `/ae`, `/signals` Safety
  Officer-only; `/escalations` closed to Volunteers.
- `POST /api/pv/code` (JSON body, header CSRF) is the only coding-assist
  route wired in UI; the deprecated GET twin answers only for `/docs`.

## Phase 1 deliverables: what still stands

- Design tokens (`tokens.css`), self-hosted fonts, local Tailwind build,
  `_components.html` trust-copy single source, `POST /api/pv/code` — all
  intact and gate-enforced.
- Claim-inventory rule (02): re-applied to the landing page and shell during
  reconciliation; the landing now describes only what the five-role backend
  ships (`docs/phase2/README.md` reconciliation section).
- Preservation map (05): `workspace.py`/`ops_home.html` row resolved —
  **deleted with a documented reason** (`docs/phase3/README.md`, decision
  record); `home.html`/`role.html`/`portfolio.html` were deleted by the
  merge itself; every other row holds.

## Smoke-gate lineage

| Gate | Pre-merge | Post-merge |
|---|---|---|
| `smoke_phase1.py` | 38 checks (lens routes) | **91 checks** (five-role gating, no-promotion, orphan guard) |
| `smoke_phase2.py` | 55 checks (seven personas) | **63 checks** (five personas + reconciliation assertions) |
| `smoke_phase3.py` | 38 checks (Operations Home) | **97 checks** (five dashboards + end-to-end escalation workflow) |
