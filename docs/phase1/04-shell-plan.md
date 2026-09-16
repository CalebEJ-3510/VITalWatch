# Phase 1 — Public & authenticated shell plan

Two shells, one design system, one component library (prompt.md §19: Direction B
explains the product, Direction A performs daily work — they are not two paint jobs).

## Current state (after this phase)

`base.html` is the interim authenticated shell: dark rail nav, per-role lens list,
badge counts, notice component, footer. It is now CDN-free and token-driven. Phase 3
rebuilds it into the real workspace shell; this phase only made it honest and
self-hosted.

## Public shell (Phase 2 builds it as `landing.html`, NOT extending `base.html`)

| Element | Contract |
|---|---|
| Masthead | Product mark + wordmark; restrained nav: Product · How it works · Roles · Trust & safety · About · Docs |
| Actions | `Explore the demo` (primary, → `/login?next=/`), `Sign in` (secondary, → `/login`) |
| Footer | Identity, About, docs, trust/safety, accessibility, project owner, synthetic-data notice (the shared `notice_synthetic` macro) |
| Mobile | Real drawer/accessible modal menu — never squeezed horizontal links |
| Typography | Fraunces display register enabled (only here); the five-stage text-art path and reference-line motif live in this shell |
| No-JS | Fully readable ordered HTML; scroll-driven enhancements behind `@supports (animation-timeline: view())` only |

## Authenticated shell (Phase 3 rebuilds `base.html` toward this)

| Element | Contract | Status |
|---|---|---|
| Product mark + environment badge | `Demonstration` badge always visible | partial (synthetic notice exists; badge styling Phase 3) |
| Current workspace name | From the role-aware workspace resolver | Phase 3 |
| Global search / command palette | §7.4 contract: permission-filtered server-side, full keyboard, `aria-live` result counts, never the only nav | Phase 3 (backend: new search endpoint — see 06) |
| Priority inbox | Only when assignment data exists — §9.3.1 naming discipline | backend-dependent |
| Data freshness / as-of | `freshness` macro, "as of page load" semantics | component ready |
| Help/terminology | Glossary access, non-blocking | Phase 3 |
| User block | Name, actual role, scope, logout | exists in rail |
| Workspace switcher | Only for roles with >1 lens (administration, regulator today); a one-lens account sees no fake switcher | exists as lens list; Phase 3 promotes to first-class switcher |
| Mobile nav | Drawer below 1024px; rail becomes top strip (current CSS) → drawer (Phase 3) | partial |

## Shell rules (both)

1. No hidden links as a security boundary — nav reflects `ROLE_LENS_ACCESS` and
   `can_write`, never substitutes for them.
2. No universal "view as any role" switch outside an explicitly labelled demo mode.
3. ` Escape` closes any overlay and returns focus to the trigger; overlays deep-link
   state into the URL where they represent a record (§7.2).
4. Shell-level responsiveness uses viewport breakpoints (1024px sidebar collapse,
   640px drawer threshold); component-level responsiveness uses container queries
   (tokens.css documents both).
5. Focus ring is always visible (`:focus-visible`, ink on light / white on dark) —
   already global in `app.css`.
