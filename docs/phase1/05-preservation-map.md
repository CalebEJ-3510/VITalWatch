# Phase 1 — Existing-view preservation map

Every current route and template: **retained** (kept working as-is into the new
system) · **redesigned** (same route/data, new composition in a later phase) ·
**redirected** (URL moves, destination preserved) · **deprecated** (removed, reason
recorded). Nothing meaningful may silently disappear (prompt.md §16, Phase 1 gate).

## Templates

| Template | Treatment | Destination & reason |
|---|---|---|
| `base.html` | **Redesigned in place (Phase 1 partial)** | CDN removed, tokens/fonts wired, notice consolidated. Phase 3 rebuilds it as the workspace shell per 04-shell-plan |
| `login.html` | **Redesigned (Phase 1 partial → Phase 2 full)** | CDN removed this phase. Phase 2 makes it the polished product entry; safe `next` handling already server-side |
| `home.html` | **Split (Phase 2/3)** | Public content → landing page; authenticated work → Operations Home. Phase 1 fixed its false claims and forbidden link only |
| `_macros.html` | **Retained** | nav_link, badge, ref mark, page_head, note — still the primitives old templates use; new components import from it |
| `_components.html` | **Retained & extended** | The Phase 1+ component layer: states, freshness, deadline clock, queue toolbar, evidence, audit event, breadcrumb, notice |
| `portfolio.html` | **Redesigned (Phase 4)** | Portfolio overview + reusable risk queue (filter/sort/search) |
| `study.html` | **Redesigned (Phase 4)** | Persistent context header + focused subviews incl. timeline (`timeline.py` adopted after validation) |
| `role.html` | **Redesigned (Phase 3)** | Lenses preserved inside capability-aware workspaces; picker already access-checked — Phase 3 makes it a real switcher with deterministic defaults |
| `ae.html` | **Split (Phase 5)** | Case queue + staged intake + case workspace. Honest disabled-state copy and intake disclaimers are kept verbatim |
| `signals.html` | **Redesigned (Phase 5)** | Signal queue + detail; investigation entry enabled only where a case exists, else disabled with an honest reason |
| `investigation_case.html` | **Redesigned (Phase 5)** | Generalized beyond the single case where feasible; labelled demonstration-scoped where not |
| `investigation_board.html` | **Redesigned (Phase 5)** | Evidence-driven concept kept; hardcoded narrative and all 10 emoji markers replaced by evidence/badge components |
| `audit.html` | **Redesigned (Phase 5)** | Quality/audit center; precise chain-guarantee wording (§11.5) |

## Routes

| Route | Treatment | Notes |
|---|---|---|
| `GET /` | **Redirected (Phase 2/3)** | Unauthenticated → public landing; authenticated → Operations Home |
| `GET/POST /login`, `POST /logout` | **Retained** | `_safe_next_path` already blocks open redirects |
| `GET /role/{id}` (+ JSON twin) | **Retained → redesigned (Phase 3)** | Access checks unchanged |
| `GET /portfolio`, `GET /study/{id}` | **Retained → redesigned (Phase 4)** | Data contexts unchanged |
| `GET/POST /ae` | **Retained → redesigned (Phase 5)** | Audited intake untouched |
| `GET /signals` | **Retained → redesigned (Phase 5)** | |
| `GET /investigation*` | **Retained (demo-scoped)** | Guards kept until the case model generalizes |
| `GET /audit`, `GET /api/audit/verify` | **Retained → redesigned (Phase 5)** | |
| `GET /health`, `/robots.txt`, `/static/*` | **Retained** | |
| All `/api/*` JSON routes | **Retained** | Documented API surface; `/docs` stays session-gated |
| `GET /api/pv/code` | **Deprecated (Phase 1)** | Narrative-in-URL defect. Kept for compat, marked deprecated, docstring forbids UI use |
| `POST /api/pv/code` | **Added (Phase 1)** | Request-body + `X-CSRF-Token`; the only coding route UI may call |
| `GET /api/investigation/{id}/retrieve` | **Retained with flag** | `q` in query string acceptable for corpus queries; must move to a body endpoint if it ever carries narrative text (§7.3) |

## Static assets

| Asset | Treatment |
|---|---|
| `app.css` | **Retained, refactored** — consumes tokens.css; Phase 4/5 moves queue/inspector components in |
| `tokens.css`, `fonts.css`, `fonts/*.woff2` | **Created (prior session), validated & wired (this phase)** — wOF2 verified; now actually linked by both shells |
| `vendor/tailwind.css` | **Created (this phase)** — local build replaces CDN |
| `mark.svg` | **Retained** |

## Explicitly deprecated

Nothing else. No page, endpoint, export, or behavior was removed in Phase 1.
