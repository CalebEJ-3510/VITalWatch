# Phase 3 — Authenticated shell & role-aware portal dashboards: build & verification record

Spec: `prompt.md` §9 (shell + portal dashboards), §7.4 (command palette), §5
(roles vs. personas), §16 Phase 3 (required work + exit gate). Built on the
Phase 1 foundation (`docs/phase1/`) and shares the Phase 2 design system.

> **Post-merge reconciliation (2026-09-16).** The backend merge (commit
> `2238e6f`) replaced the seven-role/lens model this phase was first built
> against with the five-role CTMS (`volunteer` / `company` / `investigator` /
> `safety_officer` / `leadership`, one routed dashboard per role). Everything
> below describes Phase 3 **as reconciled to that backend**. The earlier
> record (Operations Home at `/home`, four role-class compositions, lens
> switcher, pv.demo/pi.demo/monitor.demo accounts) is superseded and retained
> only in git history.

## What ships (current)

| Piece | File | Notes |
|---|---|---|
| Authenticated shell | `app/templates/base.html` | §9.2: product mark + `Demonstration` badge, workspace name (topbar), palette trigger, freshness as-of, help, user block (name/role/logout), mobile drawer as native `<details>`. **No lens/workspace switcher anywhere** — exactly one dashboard exists per role (§5), and the shell's comment says so. Nav is generated from the signed-in role and reflects the server-side gate; it never substitutes for it. |
| Portal shell | `app/templates/portal/_base.html` + `_partials.html` | Top strip (identity, portal chip, notifications, user), breadcrumbs, portal rail, flash line. The unused `portal_role_links` switcher was removed (§5: no switcher against a one-dashboard-per-role reality). The global-search form renders **only for Leadership** — `/search` is a Leadership-only route, and offering it to other roles promoted them into a 403 (§18.8). |
| Five dashboards | `app/templates/portal/{volunteer,company,investigator,safety_officer,leadership}_dashboard.html` | Each answers its own §5.1 first-screen question with its own composition (see below). |
| Company operations | `app/templates/portal/company_operations.html` | Persistent trial-context header (§5.1's Company gap): all four status dimensions shown distinctly. Fake capability removed: no trial create/edit form (no such route exists) and no Company submission-decision buttons (eligibility belongs to the Investigator). Submissions render read-only. |
| Command palette | `app/static/palette.js` + `GET /api/search` | §7.4, unchanged in shape; placeholder/aria vocabulary reconciled (`trial` / `participant code` / `escalation`, never `study` / `subject`). |
| Smoke test | `scripts/smoke_phase3.py` | 97 checks; exit-gate runner (rewritten against the five-role backend). |

## The five compositions (§9.3)

- **Volunteer** — "What is the state of my participation?": own trial,
  appointments (real columns: `title` / `scheduled_at`), consent + history,
  self-report. Strictly scoped to the linked participant; the demo account is
  now actually *linked* (`app/main.py::_migrate_legacy_users` also creates the
  `participant_user_access` row — without it the journey showed only the
  unlinked empty state).
- **Company** — "What does my trial need from me right now?": the
  awaiting-response queue with **live statutory clocks**
  (`governance.clock_progress`, never a stored snapshot), per-trial derived
  counts, corrective actions in the review loop, the issue queue.
- **Investigator** — "Which submissions and escalations need my decision
  today?": eligibility queue **oldest-waiting first** with the AI pre-screen
  beside each submission (engine + confidence, advisory); protocol-deviation
  escalations with a "Review response →" path; honest scope note — *trial
  access is a selection, not a stored assignment* (§9.3.1).
- **Safety Officer** — "Which event or reporting obligation requires attention
  next?": **statutory-clock urgency is the primary sort key** (§9.3's named
  gap — a serious AE near its 24-hour deadline outranks an uncoded mild
  event), the AI suggestion from `ae_codes` (engine + confidence) beside every
  confirm/correct/uncoded control, PRR signals with the raise-escalation path,
  safety-concern escalations.
- **Leadership** — "Is the institution safe, compliant, and inspection-
  ready?": pending decisions **first** (not KPIs first with decisions buried),
  portfolio KPIs from `kpi.portfolio_kpi`, recent decisions with their
  mandatory reasons, live audit-chain verification with the bounded-guarantee
  copy (§13.1).

## Post-merge defects found and fixed (2026-09-16)

1. **`kpi.portfolio_kpis` → AttributeError (leadership 500).** The merge
   renamed the function to `portfolio_kpi` (singular); the route was never
   updated. Fixed in `app/main.py`.
2. **Four dashboards rendered empty queues / zero metrics.** The merge changed
   route context variables (`submissions` vs `eligibility_queue`,
   `uncoded_events` vs `events`, `pending_decisions` vs `pending`,
   `appointments` columns) without reconciling the templates. Every queue
   above is now fed by its real context and the gate asserts live rows.
3. **Promotion into 403s (§18.8).** Investigator and Safety Officer portal
   rails linked `/audit` (Leadership-only); the portal-shell search form
   targeted Leadership-only `/search` for every role. Both removed/gated.
4. **Fake capability forms.** Company operations had a trial create/edit form
   and Company submission approve/reject buttons posting to routes that do
   not exist. Removed, with the boundary stated on the page.
5. **Volunteer nav linked a POST-only route** (`/portal/volunteer/reports`,
   405 on GET) — now an anchor to the on-page form.
6. **`app/workspace.py` + `app/templates/ops_home.html` — deleted** (decision
   below).
7. **Shell stale vocabulary/comments** — palette placeholder/aria-label and
   the shell comment referenced studies/subjects/`ROLE_LENS_ACCESS`/lens
   switchers; reconciled.
8. **Stale smoke gates** — `smoke_phase1.py` and `smoke_phase3.py` crashed
   against the new backend (`/home`, `/role/*`, seven-role accounts);
   `smoke_phase2.py` asserted seven personas and the `/home` redirect. All
   three rewritten; the Phase 3 gate now also *drives* the signature
   escalation workflow end-to-end (raise → nine-field response → escalate →
   leadership pause → resume) and asserts both `governance.decide` branches
   plus a still-intact audit chain after the writes.

## Decision record: `app/workspace.py` / `ops_home.html` → **deleted**

Per prompt.md §1.1.2 the module was orphaned (never imported by
`app/main.py`) *and* schema-incompatible (it referenced `studies`,
`subject_code`, and deleted `UserRole` members; it would raise
`AttributeError` on first call). The two sanctioned options were rebuild or
delete with a documented reason. **Chosen: delete.**

- The job it was built for — "signed-in users land in useful work" — is now
  natively met by the five routed `/portal/{role}` dashboards, which the
  merged backend provides and this reconciliation differentiates.
- Its good ideas (priority queue over KPI wall, live-clock-derived ordering,
  "within my authorized scope" naming) are *requirements*, not code: they
  live in prompt.md §9.3/§10.2 and will be rebuilt as the Phase 4 queue
  pattern against `app/ctms.py` / `app/governance.py` / `app/pv.py` — there
  is nothing salvageable to import (zero shared vocabulary with the current
  schema).
- Keeping it meant silently broken code on disk, which §1.1.2 forbids.
  `scripts/smoke_phase1.py` §8 now asserts both files stay gone and
  unreferenced, so the decision cannot silently regress.

## Verification evidence (2026-09-16)

- `scripts/smoke_phase1.py` — **91/91 PASS** (five-role gating, no-CDN,
  per-role routing, no-promotion, coding endpoint, orphan regression guard).
- `scripts/smoke_phase2.py` — **63/63 PASS** (landing reconciled: five
  personas, no FHIR/SDTM/BM25/investigation claims, `/portal/{role}` front
  door).
- `scripts/smoke_phase3.py` — **97/97 PASS** (shell contract ×5 roles,
  distinct compositions, live rows, end-to-end escalation workflow incl.
  both leadership-decision branches, palette backend, §9.3.1 naming).
- `pytest` — **57 passed** (the pre-merge rehearsal harness failure is gone
  with the harness).
- `npm run build:css` — Tailwind rebuilt after template changes.
- Browser pass: see `media-output/` captures referenced in the session log.

## Exit gate (§16 Phase 3)

> Each of the five portal dashboards visibly answers its own §5.1 first-screen
> question with a distinct layout. Users can identify critical, overdue,
> due-soon, in-scope, and recently changed work without opening multiple
> pages. No user is promoted to a role's dashboard or action they cannot
> access. Signed-in users land in their /portal/{role} dashboard, not the
> public landing page.

Met: distinct compositions asserted per role (mutually exclusive markers);
live-clock queues for Company and Safety Officer; no-promotion asserted in
HTML and at the server gate for all five roles; `/` 303s to `/portal/{role}`
for all five demo accounts.
