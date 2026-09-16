# Phase 2 — Public landing page: build & verification record

Spec: `prompt.md` §8 (landing content), §6.1.2/§6.1.3 (text art and its
constraints), §16 Phase 2 (required work + exit gate). Built on the Phase 1
foundation (`docs/phase1/`), sharing `tokens.css`, `fonts.css`, the local
Tailwind build and `app.css` primitives — one design system, two registers
(§19): Direction B (research editorial) here, Direction A (clinical clarity)
in the authenticated product.

## What ships

| Piece | File | Notes |
|---|---|---|
| Landing template | `app/templates/landing.html` | Standalone public shell (does not extend `base.html` — decision in `docs/phase1/04-shell-plan.md`). Queries nothing; hero preview is a labelled static fixture (§6.5). |
| Landing styles | `app/static/landing.css` | Only what the public register adds: warm paper ground, display-face rules, landing components. All semantic colour/motion/type still from `tokens.css`. |
| Landing JS | `app/static/landing.js` | Progressive enhancement only (Escape-to-close, close-on-navigate for the drawer). Page is fully functional without it. |
| Routing | `app/main.py` | `GET /` → landing for anonymous, `303 /home` when signed in (§4). `GET /about` → `303 /#about`. `login next=/` resolves to `/home`. |
| Smoke test | `scripts/smoke_phase2.py` | 55 checks; exit-gate runner. |

### §8 required-work checklist

- §8.4.1 hero: thesis, one paragraph naming the domain, `Explore the demo` +
  `See how it works`, and a real product preview in the first viewport —
  composed from the actual primitives (`.pill`, `.ref`, `.code`, `.evidence`,
  `.audit-event`), labelled **Synthetic demonstration · not live telemetry**. ✅
- §8.4.2 why: fragments → one traceable case convergence visual. ✅
- §8.4.3 what: five pillars, each with a real interface-state diagram and an
  anchor link to deeper content; the audit pillar owns the full-width row. ✅
- §8.4.4 how: the signature `DETECT → UNDERSTAND → INVESTIGATE → DECIDE → PROVE`
  path — a real `<ol>` in DOM order, every stage stating input / system
  derives / human decides / evidence kept / not claimed; deep-link chip nav;
  scroll-linked emphasis gated `@supports (animation-timeline: view())` +
  `prefers-reduced-motion: no-preference` (§6.1.2, §6.1.3). ✅
- §8.4.5 roles: seven personas as native radio inputs (no JS possible), with
  the "changes this page's content only" permission disclaimer. ✅
- §8.4.6 trust: six engineered-trust properties + the monospace evidence
  chain (source record → append-only audit row) with bounded guarantee copy. ✅
- §8.4.7 proof: five truthful proof points + four explicit non-claims. ✅
- §8.4.8 about: AYUSH framing, audience, design goal, high-level architecture,
  demo-vs-production, deliberate non-goals. ✅
- §8.4.9 FAQ: eight boundary questions as native `<details>`. ✅
- §8.6 imagery: product-mark SVG only (decorative, `alt=""`); no stock
  photography, no concept renders shipped as assets. ✅
- §8.7 interactions: all native or CSS-gated; nothing auto-plays; no carrier
  of meaning is motion-only. ✅
- §8.8 final CTA + footer with the shared `notice_synthetic` macro. ✅

## Verification evidence (2026-09-16)

- `scripts/smoke_phase1.py` — **37/37 PASS** (Phase 1 gate intact).
- `scripts/smoke_phase2.py` — **55/55 PASS** (routing contract, no-CDN,
  structure, text-art order, role selector, honesty, no-JS/reduced-motion
  mechanics, a11y landmarks).
- `pytest` — 57 pass, 1 skip, 1 pre-existing environmental failure
  (`test_importing_the_harness_does_not_create_the_default_database`; asserts
  `data/ctms.db` absent — the real demo DB is intentionally kept).
- Browser pass (Chromium, agent-browser), desktop 1440×900: every section
  captured (`media-output/v2-1440-*.png` + `v2-1440-full.png`); role selector
  switches panels; FAQ discloses; drawer opens/closes; Escape closes drawer
  (landing.js confirmed executing); zero failed resources; no console errors.
- Resilience: reduced-motion emulation → all five stages fully visible,
  opacity 1, nothing hidden. No-JS is structural: drawer/FAQ are `<details>`,
  role selector is radio inputs — interactions cannot depend on JS.
- 390px pass (gate requires critical content understandable): no horizontal
  overflow (scrollWidth == clientWidth), preview stacks queue-over-inspector,
  drawer summary is icon-only, path/pillars/roles/chain all reflow.

### Fix applied during verification

- `.l-preview-inspector .audit-event` shattered into mid-phrase fragments in
  the narrow inspector column. Added a scoped override in `landing.css`
  (display: block; flowing text) — the shared `.audit-event` row layout on
  operational pages is untouched. Re-verified: 55/55 still green.

## Exit gate (§16 Phase 2)

> A first-time visitor can explain, unprompted, why VITalWatch exists, what it
> does, who it's for, and what is and isn't real — without a narrated demo.
> The page works fully with JavaScript disabled and with reduced motion
> enabled. No invented proof points, logos, or claims appear anywhere.

Met: the page carries why/what/who/how/trust/proof/about/FAQ in reading
order with no JS dependency; reduced-motion shows the final state
immediately; the only imagery is the product mark; every claim is either
verifiable in the demo or explicitly negated on the page.

---

## Post-merge reconciliation (2026-09-16)

The backend merge (commit `2238e6f`) deleted the seven-role lens model, the
investigation board, the BM25/RRF evidence retrieval, and the FHIR/SDTM
exports (prompt.md §1.1.1). The landing page — written against the old
backend — was re-verified claim by claim and corrected:

- **Role selector: seven personas → the five real roles** (Volunteer /
  participant, Company, Investigator, Safety Officer, Leadership), each
  panel answering its §5.1 first-screen question; no sixth account type is
  implied. CSS sibling selectors updated (`landing.css`); still pure radio
  inputs, no JS required.
- **FHIR/SDTM claims removed** from proof points, the architecture list and
  the integrations FAQ — replaced by the truthful boundary ("no export
  surface, and we say so") and the AI-governance proof point (findings stay
  human-gated with engine version and confidence).
- **BM25 / concept-expansion / RRF retrieval claims removed** from the
  architecture list, the "Investigate" stage, and the About section — the
  five-stage path keeps its §8.4.4 words, but "Investigate" now describes
  the real signature workflow: the escalation package (raised facts, paused
  trial, statutory response clock, AI finding with review state).
- **Preview fixture reconciled** — "Investigation INV-001" replaced by a
  safety-concern escalation raised from the flagged signal; "Operations
  Home · Safety" renamed to the real "Safety Officer portal"; the evidence
  chain uses `trial` / `participant` / `role` vocabulary.
- **Routing contract** — the front door is now `303 /portal/{role}` (never
  `/home`); the gate asserts it for the signed-in case.
- Gate: `scripts/smoke_phase2.py` grew 55 → **63 checks**, adding explicit
  reconciliation assertions (no BM25/RRF, FHIR/SDTM named only as an absent
  boundary, no seven-role vocabulary, no deleted-schema field names).

Re-verified after reconciliation: **63/63 PASS** (2026-09-16).
