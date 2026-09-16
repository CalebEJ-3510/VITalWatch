# Phase 1 — Claim inventory & reconciliation

Every user-visible or documentation claim checked against the code on 2026-09-15.
Verdicts: **true** (code agrees) · **false** (code contradicts) · **stale** (was true
once, code moved on) · **unverified** (cannot be checked from this repository alone).

Status column: ✅ fixed this phase · ⏭ deferred to a later phase (with reason).

## Contradictions resolved in Phase 1

| # | Claim (before) | Location | Verdict | Fix |
|---|---|---|---|---|
| 1 | "Authentication and access control… deliberately not built. The role dashboards… restrict nothing, and every screen stays reachable from every one of them." | `home.html` "Deliberately not built" panel | **False** — session middleware gates every route (`main.py:89-121`), `require_lens` 403s, `require_role` gates writes | ✅ Panel rewritten as "Boundaries of this build": licensed dictionaries, EDC/ABDM counterparty, SDTM beyond DM, external submission receipts — plus an explicit "Built, and enforced" note |
| 2 | Universal "Role dashboards" button → `/role/leadership` | `home.html:22` | **Broken promise** — 403s for 5 of 7 roles | ✅ `home()` now computes `home_lens` per role (leadership if permitted, else first permitted lens, else no link) |
| 3 | "Authentication is deliberately not built (see the home page)" | `roles.py` docstring | **Stale** | ✅ Docstring rewritten: lens ≠ access control; enforcement at route layer named |
| 4 | "Tailwind and Chart.js from a CDN. One process, no build step." | `README.md` Stack | **False** — no Chart.js anywhere in the repo; Tailwind CDN removed this phase | ✅ Stack section rewritten: self-hosted fonts, `npm run build:css`, Chart.js absence stated |
| 5 | "Not built, deliberately: Authentication and enforced permissions… PostgreSQL." | `README.md:139-146` | **False** — `app/auth.py`, `app/db.py` implement both | ✅ Section rewritten; built list (auth, RBAC, CSRF, Postgres) stated explicitly with the stale-claim correction noted |
| 6 | "Jinja2 renders server-side, Tailwind and Chart.js come from a CDN" | `main.py` docstring | **Stale** after this phase | ✅ Docstring updated to self-hosted assets |
| 7 | "Tailwind and Chart.js from a CDN. No client build…" | `docs/architecture.md:42` | **Stale** | ✅ Updated: fonts.css + tokens.css + local Tailwind build; Chart.js not used |
| 8 | `/` described as showing "what is deliberately not built" | `README.md` screens table | Accurate but referenced the old false panel | ✅ Row updated to "the boundaries of this build" |

## Claims verified as true (kept, consolidated where copy drifted)

| Claim | Location | Evidence |
|---|---|---|
| "Every page and API route requires a signed-in session; write routes additionally require a role permitted to perform that action" | `base.html` banner → now `notice_synthetic` macro | `attach_session_user` middleware; `require_role` on both mutating routes. Copy moved into the single notice component (§13.1) so banner/footer cannot drift |
| "MedDRA and WHODrug are licensed commercial dictionaries and are not used" | `README`, `home.html`, `ae.html` note | Coding runs against `app/terms.csv` (`pv.load_terms`); confirmed no MedDRA/WHODrug references in code |
| Statutory clocks: 24-hour initial report, 14-day narrative, NDCT Rules 2019 framing | `home.html` regulatory framing; `ae.html` | `config.py`: `sae_initial_report_hours=24`, `sae_narrative_days=14`; `pv.compute_clocks` stores real deadlines. Framing copy stays as demo summary, not legal specification (§12.1) |
| "Audit chain intact · N events · head …" on home | `home.html` | `audit.verify(db)` runs on every home render — live result, not cached |
| "UPDATE and DELETE are refused by the database itself" | `README`, `home.html` cards | Triggers asserted by `scripts/rehearse.py` and `tests/test_audit_integrity.py` |
| Lens picker is access-controlled | `role.html` | `permitted_role_ids` from `ROLE_LENS_ACCESS`; direct URL to an unlisted lens 403s |
| "External report submission is not tracked; do not use this as evidence of regulatory compliance" | `ae.html` intake note | No submission-receipt fields exist. Exactly the honesty the brief asks for — kept |
| Retrieval is BM25 + curated-vocabulary concept expansion + RRF(k=60), not a dense model | `README`, investigation pages | `app/retrieval.py`; `/api/investigation/{id}/retrieve` exposes all three rankings |
| Fixed seed → identical portfolio/audit head every rebuild | `README` | `datagen.py` `SEED_RANDOM_SEED=20260822`, `TODAY = date(2026, 8, 22)` |

## Defects classified (the two the brief names as shippable bugs)

| Defect | Treatment | Status |
|---|---|---|
| `GET /api/pv/code` carries the narrative in the URL query string (server logs, browser history, proxies) | `POST /api/pv/code` added in Phase 1: JSON body, session required, `X-CSRF-Token` header check. GET route kept but marked `deprecated=True` for `/docs` compatibility; its docstring forbids UI wiring. Phase 5 builds the coding-assist UI exclusively on the POST route | ✅ endpoint shipped; ⏭ UI in Phase 5 |
| Emoji as evidence/risk markers (10 instances: 📄 👥 ⚠️ ⚠ 🌿 📚 🔀 🟠 🟢🔴 ✅) | `investigation_board.html` | ⏭ Phase 5 — replaced by badge/evidence components when the board is rebuilt; touching it now would churn a template Phase 5 replaces wholesale |

## Unverified-in-this-pass (honest flags, not silent keeps)

| Claim | Where | Why it needs its own check |
|---|---|---|
| "Supabase Postgres · 11 tables · **RLS**" | `docs/architecture.md` diagram | Row-level security is Postgres-side; this repository cannot prove the hosted instance's RLS posture. Verify against the live deployment before repeating the claim publicly |
| "seeding either produces the same audit chain head, `e09de76…`" | `README` | Asserted by `scripts/rehearse.py`; confirmed green in the Phase 1 test run against SQLite. The Postgres half needs `DATABASE_URL` set |
| Live deployment URL works | `README` | External state; checked separately from this phase |

## Copy rules going forward (so this class of bug cannot regrow)

1. A page may only claim what the route serving it enforces — checked in the matrix,
   not remembered.
2. Trust copy lives in exactly one component (`_components.html::notice_synthetic`);
   no second handwritten disclaimer may be added to a template.
3. "Not built" lists get reviewed against `app/` every phase — they decay fastest.
