# Phase 1 — Product truth, route inventory, and design system

**Status: complete.** Exit gate assessed 2026-09-15. **Re-verified against the
post-merge five-role backend on 2026-09-16 — wherever 01–06 name the old
seven-role model, [07-post-merge-reconciliation.md](07-post-merge-reconciliation.md)
is the current truth.**

| Deliverable | File |
|---|---|
| Route & capability matrix | [01-route-capability-matrix.md](01-route-capability-matrix.md) |
| Claim inventory & reconciliation | [02-claim-inventory.md](02-claim-inventory.md) |
| Decisions (route model, demo clock, indigo, type, assets, CSRF, trust copy) | [03-decisions.md](03-decisions.md) |
| Public & authenticated shell plan | [04-shell-plan.md](04-shell-plan.md) |
| Existing-view preservation map | [05-preservation-map.md](05-preservation-map.md) |
| Backend-dependent feature list & role-capability map | [06-backend-dependent.md](06-backend-dependent.md) |
| **Post-merge reconciliation addendum (supersedes)** | [07-post-merge-reconciliation.md](07-post-merge-reconciliation.md) |
| Design tokens (single source of truth, indigo resolved in writing) | `app/static/tokens.css` |
| Self-hosted type system (metric-matched fallbacks) | `app/static/fonts.css` + `app/static/fonts/` |
| Shared component/macro layer | `app/templates/_components.html` |
| Local Tailwind build (CDN removed) | `tailwind.config.js` + `app/static/src/tailwind.input.css` → `app/static/vendor/tailwind.css` (`npm run build:css`) |
| Request-body coding endpoint (privacy fix, Phase 5 enabler) | `POST /api/pv/code` in `app/main.py`; `verify_csrf_header` in `app/security.py` |
| Exit-gate smoke test | `scripts/smoke_phase1.py` |

## Exit gate (prompt.md §16, Phase 1)

1. **Every visible action and promise is classified as implemented, planned, or
   demonstration-only.** → 01 (routes), 02 (claims), 06 (backend-dependent).
2. **No universal home link points users into a forbidden lens.** → `home()` now
   computes the per-role lens link; smoke checks 11–12 and 33–34 prove pv.demo is
   never offered `/role/leadership` and admin.demo is.
3. **No application behavior is made less secure.** → Nothing removed except the
   false claims; additions are strictly hardening (request-body coding route with
   header CSRF; GET twin deprecated but intact). Auth, RBAC, CSRF, audit, API and
   export contracts unchanged.

## Verification evidence

- `scripts/smoke_phase1.py`: **36/36 checks pass** (sandbox DB; the real
  `data/ctms.db` is never touched).
- `pytest tests/`: **57 passed, 1 skipped, 1 failed** — the failure is
  `test_importing_the_harness_does_not_create_the_default_database`, which asserts
  `data/ctms.db` does not exist. A development database exists at that path from
  before this phase (created 2026-09-15 16:03, pre-dating every Phase 1 change);
  the test is environmental and fails identically on the pre-Phase-1 tree. The
  database was deliberately left untouched.
- Frozen Tailwind build spot-checked for arbitrary-value and opacity-modifier
  classes used across all 13 templates (`text-[10.5px]`, `lg:grid-cols-[1.4fr_1fr]`,
  `bg-[color:var(--breach-bg)]`, `border-white/10`, `bg-red-950/40`, …): all present.
- Font files verified as valid WOFF2 (`wOF2` magic), latin subsets, served 200.

## What Phase 2 can now assume

A CDN-free, token-driven, self-hosted shell; a component layer with the eight §10.1
states; one trust-copy source; a claim inventory whose copy rules keep the product
honest; and a route matrix that says exactly what each screen may promise. The
landing page (Phase 2) builds on `tokens.css`/`fonts.css` with the Fraunces display
register enabled — nothing in Phase 1 needs to be redone to start it.
