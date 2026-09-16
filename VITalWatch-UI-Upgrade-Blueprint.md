# VITalWatch — UI/UX Upgrade Blueprint

**Design review and proposal · 15 September 2026 · No application code changed**

## 1. The recommendation

**Do not start by reskinning the dashboard. Reorganize VITalWatch around the work people perform, then give that work a distinctive visual language.**

The requested upgrade is not simply “more animation.” It is a move from a demonstration that displays capabilities to a coherent product where people arrive, understand their responsibilities, investigate a situation, act, and see reliable confirmation of what changed.

The direction I recommend is **an expressive public entrance, calm clinical workspaces, and a focused evidence-review environment**. These should share one design system. They should not be unrelated themes or seven separate applications.

VITalWatch is a clinical-trial oversight and pharmacovigilance project, not a consumer fitness app or hospital appointment system. A generic healthcare template with pulse waves, doctor portraits, bed occupancy, patient avatars and appointment cards would be a category error. The product's distinctive material is already in the repository: studies, timelines, reporting obligations, evidence provenance, controlled terminology, and traceable decisions.

### What your criticism is pointing to

- **“It looks like AI slop”**: too much generic explanatory copy, repeated presentation patterns, and claims that are not reconciled with the current implementation. The issue is weak product specificity and editorial coherence—not the mere presence of cards or a particular framework.
- **“The views are tabs”**: account roles are being treated as alternative summaries over a common page rather than different work environments.
- **“It is hardcoded”**: some important behavior is genuinely computed, but the demo dataset, single investigation case and presentation narratives make the experience feel frozen.
- **“There is no home page”**: technically there is an authenticated overview and a login screen. What is missing is the deliberate public home → sign-in → authorized workspace journey.
- **“There is no dynamicity”**: the product rarely preserves context while users explore, filter or act; it lacks many loading, update, completion and recovery behaviors that make software feel responsive and dependable.
- **“It needs powerful UX”**: the highest-value improvement is turning a detected problem into an owned, actionable, auditable workflow—not adding a larger chart.

## 2. Scope and confidence

This is a **source-based repository audit**, not a browser usability study. Application modules, templates, styles, source data, documentation, tests, scripts and root configuration were reviewed. The initial delegated audit sampled vocabulary/corpus data; those files were subsequently read in full. Git reported a clean working tree before the review.

The running application was not launched, and the public deployment was not inspected or mutated. Current deployed configuration, live database contents, rendered contrast, responsive behavior and runtime performance are therefore **not verified**. No database seed, migration, deployment or clinical write was performed.

The images below are **generated design concepts**, not screenshots, working prototypes or production specifications. They illustrate hierarchy and composition. Their proposed workflows are not necessarily implemented. Their small text and iconography are not an accessibility certification. In particular, retain the existing project mark during implementation unless a separate brand change is approved; decorative botanical details in the concepts are exploratory.

Repository references without line numbers name the relevant source area. Exact line references are supplied for key findings checked directly during this review.

## 3. What the repository actually supports

### Evidence-backed diagnosis

| Finding | Repository evidence | Product consequence |
|---|---|---|
| A login and overview exist, but no public product entrance | `app/templates/login.html`; authentication in `app/main.py`; overview in `app/templates/home.html` | The user encounters a gate before understanding the product, then a general introduction rather than their work |
| Sign-in defaults to the same destination | `app/main.py:374–379` defaults `next` to `/` | No role-aware first screen when there is no valid deep link |
| Seven roles collapse into three lenses | `app/main.py:131–139`; `app/roles.py`; `app/templates/role.html` | Coordinator, monitor and ethics responsibilities do not get a genuinely tailored workspace |
| Lens navigation is repeated | `app/templates/base.html:47–53` plus the role page's pill-link switcher | Roles look like navigation tabs rather than accountable work contexts |
| Home contains a role-inappropriate link | `app/templates/home.html:20–24` points all users to `/role/leadership`; `main.py:163–168` enforces lens access | Some users are invited to open a destination they cannot access |
| The product contradicts itself about auth | `home.html:118–129` says auth is not built; `base.html:89–94` says sessions and write permissions are enforced | Trust is undermined before a user evaluates the actual security |
| Other documentation is stale | `README.md:86–89` advertises Chart.js; `README.md:139–146` lists authentication and PostgreSQL as not built despite corresponding code | A visual upgrade alone will not fix the sense of an unfinished, mechanically assembled product |
| Bespoke client-side interaction is minimal | Template search found Tailwind CDN scripts in `base.html` and `login.html`, and a role-picker `onchange` submission in `role.html:37`; no custom fetch/chart interaction layer was found | Most filtering and actions involve navigation or full form submission |
| Existing effects are real but limited | `app/static/app.css` includes button transitions, card hover lift, expanding evidence, cluster animation and reduced-motion handling | “No effects at all” is not literally accurate; effects are not connected to enough meaningful workflow transitions |
| Useful backend functions are underexposed | `/api/pv/code`, `/api/alerts`, `/api/signals`, and investigation retrieval in `app/main.py` | Live assistance, contextual evidence and filtering can be introduced without replacing the calculation engine |
| A timeline module is not connected to the interface | `app/timeline.py`; no importer found in the review | A product about deadlines and study progression lacks a strong temporal view |
| Investigation is tied to one demonstration case | `app/case_data.py`; guards in `main.py:661–662`, `706–707`, `735–736` | The most distinctive screen is not a general investigation workflow |
| Work items often stop at visibility | `app/alerts.py`, `app/models.py`, `app/templates/ae.html`, `role.html`, `study.html` | Alerts, query gaps and reporting obligations are displayed without a full owner → action → evidence → completion lifecycle |
| Authentication is not the same as data scoping | Global session middleware, lens checks and write allowlists in `app/main.py`; shared study/event/API read routes | “My studies” must not imply inaccessible other studies unless server-side study/site assignments enforce that boundary |
| Frozen seed inputs interact with a moving clock | `app/datagen.py`, `app/case_data.py`, `app/kpi.py`, `app/pv.py` | Demonstration counts and urgency can drift from the demo script; this is a code-level risk, not a claim about the current deployment |

### What should survive the redesign

The backend is stronger than the current interface suggests:

- KPIs, alerts, coding, reporting-clock states and signal calculations are computed from stored inputs. They are not all fabricated UI constants.
- Authentication, session handling, CSRF protection and role-restricted writes already exist.
- The audit chain and its integrity tests are a genuine differentiator. Preserve the atomic relationship between a recorded decision and its audit entry.
- Retrieval exposes lexical, concept-expanded and fused results. That is more interesting than an unexplained “AI answer.”
- Source provenance, synthetic-data disclosures and limits on causality claims are useful trust mechanisms.
- Existing CSS distinguishes status from urgency and already includes reduced-motion handling. Preserve the intent while simplifying implementation.
- The investigation environment already attempts a different visual treatment. Develop it rather than pretending every existing design decision is worthless.

One nuance: the CSS describes indigo as a reserved reference color but also uses it for primary buttons, focus and selection. In the new system, explicitly decide whether a benchmark marker has a unique semantic token or shares an accent. Do not describe a meaning as exclusive while using it for unrelated things.

## 4. The new product structure

### Separate three experiences

**Public product site** answers: What is this? Who is it for? What can it actually do? How do I enter?

**Authenticated workspaces** answer: What needs my attention? What am I permitted to see and do? Where did I leave off?

**Records and investigations** answer: What happened? What evidence supports it? What action is allowed? Who did what, and when?

Navigation must follow that hierarchy. A role is not a tab within a generic dashboard. A study can still have local tabs—Overview, Sites, Safety, Timeline, Documents—because those are sections of the same entity. The problem is not tabs themselves; it is using them to stand in for different professional responsibilities.

### Proposed route structure — illustrative, not implemented

- `/`: public homepage; an already signed-in visitor gets an obvious “Open my workspace” action.
- `/login`: one shared authentication flow.
- `/app`: authorized landing resolver. Honor a safe, permitted deep link first; otherwise open the person's default workspace.
- `/app/workspaces/...`: actual workspaces for existing roles. The URL never grants a role.
- `/app/studies/...`: shared study records with permission-appropriate content.
- `/app/safety/events/...`: event details and reporting evidence.
- `/app/investigations/...`: investigation index and case records.
- `/app/audit`: traceability and verification.
- `/app/settings`: only appropriate account/admin settings.

Existing routes can remain during a staged transition with deliberate redirects and compatibility tests. There is no need to break the API just to rename the interface.

### Shared application shell

Keep a stable sidebar, a compact context header and one obvious page action. Suggested shared destinations: **My work, Studies, Safety, Investigations, Audit**. Context-specific destinations such as Monitoring or Ethics should appear when relevant. Move API documentation into a technical/help area instead of making it a primary clinical destination.

The header carries authorized workspace, study/site scope, global search, help and user identity. A workspace switcher is available only to accounts actually entitled to multiple workspaces. Do not expose a global “view as any role” switch in the production experience.

Record pages need breadcrumbs, copyable pseudonymous identifiers, shareable authorized deep links, a clear return path and preservation of list filters/scroll position. The selected row opens a side inspector for quick review; complex work opens a full page. The inspector is not a substitute for a real record URL.

## 5. Public homepage and sign-in

### Homepage concept

![Proposed expressive VITalWatch public homepage](media-output/img-mu2jflqd-777e1d94.png)

**Why this direction:** a research-oriented editorial page is more specific than a generic blue medical template. The evidence illustration explains the product's purpose rather than pretending it monitors heartbeats.

Recommended page sequence:

1. **Clear masthead:** project identity, product overview, workspaces, about, sign in. No app sidebar before login.
2. **Specific hero:** “See the evidence. Coordinate the response.” Supporting text names clinical-trial oversight and pharmacovigilance. Primary action: Sign in. Secondary: Explore the demo, only if a safe demo mode is implemented.
3. **A real product preview:** demonstrate a representative worklist and its evidence trail, labeled as synthetic. Do not add invented adoption numbers, institutional endorsements or compliance badges.
4. **Who uses it:** investigator, coordinator, monitor, safety, ethics, administration and regulator. Describe the job each experience supports rather than presenting arbitrary colorful role cards.
5. **How work moves:** Observe → Investigate → Decide → Trace. These are the product story, not four unrelated features.
6. **Capability and limitation panel:** distinguish implemented, demonstration-only and planned functionality. Put dictionary and interoperability qualifications here in plain language.
7. **Entry/help footer:** access assistance, project information and the synthetic-data notice. No dead “contact sales” or password-reset links.

This page should not expose participant/study data simply because it is public. The existing synthetic-data environment can support a demo, but a public demonstration and a future institutional deployment must be unmistakably different modes.

### Login should choose identity, not grant authority

Use one coherent sign-in screen, not seven separate login implementations. An optional workspace preference can shape the landing experience, but the server determines permissions from the authenticated account.

After login:

- A single-role account goes to its relevant work queue.
- A multi-role account sees only its authorized workspaces and can remember a default preference.
- A valid permitted deep link returns to the requested record.
- A forbidden destination gives a branded explanation and a safe return action, not raw framework output.

Support password managers, paste and accessible field labels. Preserve form values appropriately after validation errors, show pending state during submission, and provide an actual access-help route. Do not display SSO, MFA or password-recovery buttons until the underlying capability exists. Those are production identity decisions, not decorative UI elements.

A demo explorer can offer role previews, but only in a clearly isolated/read-only synthetic environment or a properly isolated per-visitor sandbox. It must never become a way to choose privileges on a shared production account.

## 6. All existing roles need distinct starting points

**Shared components; different jobs.** A coordinator and a regulator should not have to infer their next action from the same KPI wall.

| Existing role | First-screen question | Proposed home and navigation emphasis | Backend gap to acknowledge |
|---|---|---|---|
| Principal investigator | What in my studies needs a clinical or study decision? | Assigned-study exception list; pending decisions; enrollment against dated plan; safety items; upcoming milestones | Current PI lens narrowing is not full record-level assignment enforcement; decision access must be checked against study scope |
| Study coordinator | What do I need to complete or correct? | Query inbox; data-completeness tasks; AE intake shortcut; study/site operational checklist | Task ownership, query resolution and relevant scheduling workflows need explicit models/endpoints; do not invent participant visit schedules from monitoring-visit records |
| Monitor | Which site needs review, and what evidence is missing? | Monitoring plan; visit/report status; deviations; site issue list; follow-up evidence | Visit completion/report filing and issue lifecycles are not a complete interactive workflow today |
| Pharmacovigilance officer | Which event or reporting obligation requires attention first? | Prioritized safety queue; uncoded items; reporting evidence; follow-ups; signal-to-investigation path | Coding corrections, assignments, acknowledgments and recorded reporting evidence require additional writes and audit semantics |
| Ethics committee | What needs ethical review or follow-up? | Approval/renewal queue; amendments where supported; relevant safety/deviation reports; review history | A dedicated ethics workflow, document versions and committee decisions must be designed; this cannot just be the leadership dashboard renamed |
| Administration | Where is the portfolio blocked and what needs coordination? | Study/site exceptions; workload and ownership when measured; readiness summary; access administration | User provisioning, assignments and workload histories are not automatically supplied by the existing KPI engine; administration must not inherit clinical decision authority |
| Regulator | Can I trace a study's evidence and history? | Read-only study dossier; reporting evidence; provenance; dated verification result; authorized exports | Inspection packaging and export auditing need work; a regulator must not gain mutation controls through a shared component |

Do not add a patient portal merely because this is healthcare. The repository models a staff/research oversight product. Patient consent, messaging, appointments and remote monitoring would require a separately scoped product and privacy/safety analysis.

## 7. Rebuild the most important screens around decisions

### A. My work: replace the KPI wall

Start with an ordered queue: priority, reason for priority, study/site, responsible person, due basis, current status and next action. Put relevant summary numbers above or beside it—not six equal cards competing for attention.

Users need to tell the difference between **no work**, **no matching results**, **no access**, **data not loaded**, and **source unavailable**. None of those should silently become zero.

Do not put “Assigned to me” into production until actual assignment data exists. Before then, label the view “Within my authorized scope” or another accurate description.

### B. Safety: the strongest first vertical slice

![Proposed calm VITalWatch safety worklist and inspector](media-output/img-mu2jil9t-f21a5180.png)

The proposed pattern is a worklist plus an inspector: select an event, inspect the source narrative, understand the coding suggestion, review reporting evidence, then take an authorized action without losing the queue.

**What the image demonstrates:** layout, information hierarchy and context preservation. “Assigned to me,” coding review, uploads and reporting-evidence actions are proposed capabilities, not claims about current routes. In the production design, the header needs actual source and refresh timestamps; the concept intentionally says “Synthetic” and “Snapshot only.”

Separate four concerns that are easy to conflate:

1. **Clinical record:** narrative, coded term, seriousness, severity, outcome, causality assessment and source.
2. **Reporting obligation:** applicable rule/protocol, trigger, deadline, recipient and status.
3. **Workflow task:** owner, acknowledgment, next step, escalation and follow-up.
4. **Audit history:** original entry, subsequent corrections and accountable actions.

Acknowledging an alert is not reporting an event. Recording evidence of submission is not proof that a recipient accepted it. Closing a task does not erase a missed deadline. Preserve those distinctions visibly.

### C. Adverse-event intake: assisted, not magical

Proposed sequence: select authorized study/subject context → enter narrative and source information → inspect suggested coding → complete seriousness/outcome/causality fields as applicable → review → submit → show a persistent confirmation with record ID and audit reference.

The coding service already exists. Expose its suggestion, match basis and vocabulary provenance while preserving the original narrative. Allow “uncoded—needs review.” A similarity score is not a probability of diagnosis or causality, and should not be presented as one.

**Privacy detail:** the current coding endpoint accepts narrative through a GET query parameter (`main.py:874–875`). Do not wire clinical free text into URL-based requests for a production implementation. Design a protected request-body endpoint and appropriate logging policy before enabling live narrative assistance. The same concern applies to sensitive retrieval queries.

Use a review step and prevent double submission. Do not display success until the server confirms the write. Amendments should be attributable and versioned, not destructive overwrites of the original record. Draft recovery requires a deliberate storage policy; do not casually persist clinical narratives in browser local storage.

### D. Study record: a navigable dossier

Use a persistent study header with identity, status, scope and key dates. Below it, use meaningful local sections: Overview, Sites, Timeline, Safety, Queries/Deviations, Documents and History, limited to what data and permissions support.

- Overview: exceptions and next milestone before descriptive metadata.
- Timeline: milestones, monitoring activity and approval expiries on a shared scale. Show planned versus actual only where both are stored.
- Sites: comparable rows and drill-down, not decorative map pins.
- Enrollment: dated observations and plan definitions. Do not fabricate historical curves from one current total.
- Queries/deviations: open detail, owner, evidence and resolution history when implemented.
- Documents: distinguish a displayed source excerpt from an actual version-controlled document system.

The unused timeline module is a candidate for reuse after validating its inputs and geometry; dead code is not automatically production-ready.

### E. Signals: an analytical workspace

Give users visible study/term filters and a supported minimum-case control. Preserve filters in the URL where they contain no sensitive narrative. Show counts, denominators, calculation definition, date scope and missing-data state. A threshold crossing must lead to the underlying events, not merely change a cell color.

Use a sortable table as the default. A plot is useful only if it improves comparison and carries honest uncertainty/scale. Do not invent confidence intervals, causality scores or time trends the backend does not calculate.

“Open investigation” should work only where a case exists; a generalized “Create investigation” needs an explicit case model and permissions. The existing single-case guard must not be hidden behind a button that silently redirects every signal to the same demonstration.

### F. Investigation: make this the signature experience

![Proposed expressive VITalWatch evidence-review workspace](media-output/img-mu2jfp8n-971c7eba.png)

Use a deliberate evidence-to-decision composition:

- **Sources:** protocol excerpts, event reports, relevant literature and study history with provenance/version/date.
- **Evidence view:** related events and source relationships, plus timeline and tabular alternatives.
- **Decision record:** reviewed evidence, explicit uncertainty, authorized decision options, rationale, identity and confirmation.

Selecting a source should highlight where it is used. Selecting an event should preserve study context. Retrieval results should explain why they matched and expose original source text. Keep technical ranking comparisons in an expandable “How this was retrieved” panel rather than requiring every clinician to study retrieval mathematics.

Graph edges must be labeled as relationships, not causation. Provide a non-graph evidence list and keyboard navigation. A dark evidence canvas can be an optional focused mode; it is not a reason to force the whole product into dark mode. The concept's faint lines, icon-only rail and small caveat require accessibility refinement before implementation.

Do not build a general AI chatbot first. The more valuable assistant behavior is to explain a coding suggestion, retrieve a traceable source, or summarize what changed with links back to evidence. Any generated summary remains distinguishable from source material and requires appropriate review.

### G. Audit: make traceability understandable

Replace a wall of hashes with human-readable event summaries and expandable technical detail: actor, role, object, action, timestamp, reason, before/after where applicable, and chain linkage.

Show the result and timestamp of a specific verification run. **“Chain verified” means integrity checks passed for the examined records—not that the clinical content is true, access control is complete, or the product is legally compliant.**

Give filters, clear result limits and pagination. Auditable exports need authorization, scope, export event recording and failure states. Do not show an “inspection-ready” completion badge without defining exactly what was checked.

## 8. Dynamic behavior that actually earns its place

| Behavior | User benefit | Required boundary |
|---|---|---|
| Search/filter updates within a worklist | Keeps the task context visible | Preserve back/forward navigation and announce result changes accessibly |
| Side inspector with a full-record link | Rapid triage without repeated navigation | Focus management, Escape/close behavior and a small-screen full-page alternative |
| Coding preview after deliberate input pause | Makes a hidden capability useful during intake | Protected request body, cancellation of stale responses, human confirmation |
| Source highlighting in investigation | Shows why a piece of evidence matters | No implied causality; keyboard and list alternative |
| Visible pending/saved/error states | Reduces repeat submissions and uncertainty | Server-confirmed completion for clinical writes |
| Freshness indicator and refresh action | Users know whether data is current | Server timestamp; distinguish stale, disconnected and live rather than using a cosmetic green dot |
| “Updates available” indicator | Makes changing work visible | Never unexpectedly reorder the row a person is reading or overwrite their form |
| Deadline display with absolute time and context | Makes urgency actionable | Server-authoritative rules, timezone, trigger and recipient; relative countdown is secondary |
| Search/navigation command palette | Faster movement for experienced users | Permission-filtered results; accessible shortcut help; never the only navigation path |
| Saved filters and density preference | Personalization without clutter | Store UI preferences separately from sensitive records |

For initial refresh behavior, use bounded background requests only where valuable. Consider server-pushed updates only when multi-user latency requirements justify the complexity. A continuously moving screen is not necessarily a better clinical screen.

### Motion budget

**Public pages:** a restrained entrance transition, purposeful scroll reveal and optional source-to-decision illustration movement can communicate the product. No scroll hijacking or content hidden until animation completes.

**Workspaces:** small focus/selection transitions, clear drawer movement, loading feedback and restrained change highlighting. Preserve the user's reading position.

**Clinical states:** do not animate safety counts from zero, flash red cards, bounce “urgent” badges, celebrate serious-event submission with confetti, or auto-dismiss important errors. Reduce motion when requested. Do not let a fading toast be the only evidence that a clinical action succeeded.

The premium feeling should come from continuity and precision: where focus goes, what stays visible, what changed, and how errors recover.

## 9. Two visual directions, one recommended combination

### Direction A — Clinical clarity

Best for daily safety, coordinator, monitoring and regulatory work.

- Warm-neutral canvas, opaque surfaces, dark readable text and clear separators.
- Ink-blue structural navigation; botanical teal for ordinary actions; semantic amber/red only for labeled urgency.
- Humanist sans-serif for clinical content and controls; monospaced identifiers and timestamps.
- Data-dense tables with breathing room, quiet headers, clear selected rows and secondary inspectors.
- Restrained shadows, purposeful icons and visible keyboard focus.

Its risk is becoming another bland enterprise table application. Avoid that with strong page composition, a useful study timeline, clear object identity, excellent empty/error states and source-to-action continuity—not gratuitous decoration.

### Direction B — Research editorial

Best for the public homepage, guided demonstrations and optional investigation focus mode.

- Editorial typography in short display headings; clinical body text stays practical.
- Ivory papers against ink-blue evidence fields, restrained botanical accents and precise diagram rules.
- Asymmetrical composition and narrative progression instead of repeated equal cards.
- Evidence relationships and traceability supply the visual identity.

Its risk is becoming a beautiful pitch deck that is awkward to operate. Limit large display typography to appropriate areas, remove ornamental paper details from dense working screens, and keep all critical information independent of animation and graph interpretation.

### Recommendation

Use **Direction B to explain and explore the product; Direction A to perform daily work**. Keep navigation behavior, components, terminology and status meanings consistent across both. Do not equate one color theme with one role.

The concept images explore this combined direction rather than offering two arbitrary paint jobs of the same dashboard.

## 10. A design system instead of scattered styling

Create a small, explicit system before rolling the redesign through every page:

- Tokens for background/surface hierarchy, text, borders, action, selection, focus, benchmark, urgency and chart series.
- A readable type scale with fewer tiny labels. Reserve monospaced type for machine-assigned identifiers and metadata, not long narratives.
- Spacing/density rules for forms, tables, evidence and navigation.
- Components: application shell, page header, task row, status badge, freshness indicator, filter bar, data table, record inspector, form field/error summary, deadline panel, evidence excerpt, decision review, audit event, empty/loading/error state.
- Content rules: use verbs for actions; distinguish unknown from none; name the actor/record in confirmations; explain disabled actions when the user can legitimately resolve the prerequisite.
- State contracts for each component, not just its happy-path appearance.

Do not make a giant universal “dashboard card” component and feed every role different strings. Reuse primitives and domain components while composing genuinely different screens.

Consolidate login/app identity and shared notices so they cannot drift. Keep a compact persistent synthetic-data indicator and contextual explanations; stop repeating long implementation disclaimers above every working screen. The warning remains clear, but should not compete visually with an actual safety warning.

## 11. Healthcare constraints that shape the design

### Clinical meaning and human authority

- Seriousness, severity, reporting urgency and clinical priority are different concepts. Give them separate fields and labels.
- Do not translate a vocabulary-match score into clinical confidence.
- Do not infer causation from disproportionality or a visual link between events.
- Record source, version, original narrative, coding method, reviewer and correction history.
- Validate reporting triggers, recipients and applicable rule sets with qualified clinical/regulatory stakeholders. Existing demo summaries are not an authoritative legal specification.
- A missed deadline must remain historically visible even after follow-up work is completed.

### Privacy and authorization

- Decide the intended read-access policy explicitly: shared institutional oversight versus assigned study/site scope. Enforce that policy at server/API/export level, not only in navigation.
- Keep unauthorized data out of search, counts, notifications, previews and exports—not just detail pages.
- Use pseudonymous identifiers consistently. Free-text fields can still contain identifying information even when the structured schema has no name field.
- Do not place clinical narratives in URLs, third-party analytics payloads or browser persistence by default.
- Plan session-expiry warnings, safe draft handling and shared-workstation behavior.
- Public demo credentials belong only to a demonstrably synthetic, isolated environment. Verify deployed secrets and configuration separately; the repository does not prove the current production values.

### Alert fatigue

AHRQ's PSNet primer describes how excessive warnings desensitize users and discusses severity tiering and reserving interruption for high-level alerts [S3]. That supports a restrained queue-first design, not an always-blinking command center. The primer was last reviewed in 2024, so it is older guidance and should not be treated as a current implementation standard.

Deduplicate related alerts, explain their cause, identify an owner and make acknowledgment distinct from resolution. Do not automatically suppress regulated obligations merely to make a dashboard greener; escalation/suppression policies need clinical governance.

### Accessibility and device use

Adopt WCAG 2.2 AA as a proposed evaluation target, with reduced-motion behavior as an additional explicit design requirement; do not claim conformance before testing [S2, S4, S5].

Address skip links, active-navigation semantics, keyboard interaction, focus restoration, field-level errors plus error summaries, accessible status announcements, non-color status cues, reflow/zoom and touch targets. Test muted text on actual surfaces. The source review identifies risk areas but does not establish measured contrast failures.

Desktop: queue + inspector. Tablet: collapsible navigation, fewer visible secondary columns. Phone: focused list and full record detail rather than squeezing a desktop graph sideways. Critical record identity, status and next action remain available. Complex comparison can favor larger screens without making essential review inaccessible on smaller ones.

### Resilience

A disconnected application must not imply that a clinical write was submitted. Use explicit retry paths and preserve entered data only through an approved storage model. Distinguish stale cached reads from current data. Do not offer offline clinical writes until synchronization, conflict handling and audit integrity are designed.

## 12. Technical strategy — no rewrite by reflex

### Recommended first path

Keep FastAPI, existing calculations, domain logic and audit behavior. Redesign the information architecture and Jinja composition, establish locally built/static assets, and add a deliberately small interaction layer.

The existing HTML-first architecture can support a much stronger experience. An HTML-over-the-wire approach such as htmx can update page regions while retaining server rendering; its documentation explicitly distinguishes HTML responses from JSON APIs [S6]. If chosen, add suitable fragment endpoints or adapters—do not assume existing JSON endpoints are drop-in fragment responses. Ordinary links/forms should retain sensible behavior, and CSRF/session protections must be preserved.

For more stateful evidence exploration, a dedicated client-side component can be introduced at that boundary. If later requirements demand complex synchronized editing, collaboration or offline workflows, revisit a richer client application with a clear state and API contract. A framework migration does not itself solve role design, scope enforcement or clinical correctness.

### Capability ledger

| Proposed change | Reuse now | Additional work |
|---|---|---|
| Public home and coherent login | Existing brand, login/session handling | Public route policy, shared identity, safe role-aware redirects, error pages |
| Role-specific home layouts | Role definitions and KPI functions | Dedicated composition; task/assignment data where claimed |
| Responsive filtering and evidence retrieval | Existing queries/JSON endpoints | Client state, secure input handling, loading/errors, appropriate fragments or adapters |
| Study timeline | Existing timeline calculations and milestones | Validate geometry/data, render, interaction and accessible alternative |
| Safe coding preview | Current vocabulary and coding function | Request-body API, privacy/logging, stale-result handling and review UI |
| Alert/task lifecycle | Existing alert evaluation and some schema fields | Durable task identity, ownership, acknowledgments, escalation, resolution and audit writes |
| Reporting evidence | Stored reporting clocks | Evidence records, recipient/submission states, authorized updates and audit |
| Multiple investigations | Existing investigation computation | General case model, index/create flow, study scope, source selection and authorization |
| Trend charts | Available dated observations, if sufficient | Additional historical data where absent; no synthetic interpolation disguised as observed trend |
| Regulator exports | Existing shape exports | Scope enforcement, export audit, reproducible manifest and clear failure/success states |

The schema needs to separate clinical facts from workflow metadata. Role configuration may select navigation and capabilities; it must not conceal missing domain models behind configuration strings.

## 13. Execution sequence and acceptance gates

This is a proposed order, not a schedule estimate. Effort depends on whether the target is an isolated showcase or actual institutional use.

### Stage 1 — Product truth and workflow definition

Reconcile stale UI/docs claims; define the read/write scope matrix; distinguish demo mode from intended operational mode; choose a deterministic demo clock or explicitly dated snapshot; map role jobs to existing versus missing capabilities.

**Exit gate:** every visible action and promise is classified as implemented, planned or demonstration-only. No universal home link points users into a forbidden lens.

### Stage 2 — Design the experience before implementing it

Create low-detail flows for public entrance/login, safety queue → event → reporting evidence, PI study → issue → decision, and regulator dossier → audit/export. Review with people who actually perform these roles. Use realistic synthetic scenarios and include error/empty/stale/forbidden states.

Then refine the design system and representative high-detail screens. Do not approve seven glossy dashboard images without testing the transitions between them.

**Exit gate:** users can explain their next action and distinguish clinical status from workflow/reporting status without a narrated demo.

### Stage 3 — Build one complete vertical slice

Prioritize **login → safety workspace → event review → authorized evidence/action → confirmation → audit trace**. This tests the shell, scope, list/detail relationship, interaction states and clinical write safeguards together.

In parallel, the public home can receive its expressive design; it must not be treated as proof that the application is finished.

**Exit gate:** the slice works end-to-end without fake buttons, success before server confirmation, or loss of work on validation errors.

### Stage 4 — Extend role coverage and shared records

Build PI, coordinator and monitor workflows using validated shared components, then dedicated ethics, administration and regulator starting points. Expand studies, signals and investigations through real record lifecycles. Add the justified assignment/reporting/case models rather than layering decorative controls over missing state.

**Exit gate:** each existing role has a meaningful first screen, coherent deep links and tested permissions; privileged shared components do not leak write actions.

### Stage 5 — Polish, resilience and evaluation

Add evidence highlighting, useful refresh behavior, navigation shortcuts and purposeful motion. Audit accessibility, keyboard use, zoom/reflow, small-screen behavior, failure recovery and performance on representative devices and networks. Validate privacy-sensitive inputs and export behavior.

**Exit gate:** the experience remains understandable with motion disabled, slow responses, no results, stale data and expired sessions.

### Suggested evaluation tasks

- Can each role reach its first meaningful task without first interpreting a portfolio KPI wall?
- Can a safety officer distinguish “needs review,” “acknowledged,” “reporting evidence recorded,” and “recipient confirmed”?
- Can an investigator inspect the original source behind a suggestion and record a rationale without losing context?
- Can a monitor find the difference between a visit not conducted and a report not filed?
- Can a regulator inspect history and export only permitted records without seeing mutation controls?
- Do direct URLs, APIs, search, counts and exports enforce the same scope?
- Can users identify stale data, unknown values and failed writes instead of mistaking them for current/empty/successful states?
- Can essential flows be completed by keyboard and with reduced motion?

Measure observed task completion, errors, backtracking, assistance required and understanding of state. Establish baselines before setting numeric targets; do not invent usability improvement percentages.

## 14. Priority decisions

**First:** correct product contradictions, define scope and workflow semantics, design the public-to-workspace journey, and build one complete safety flow.

**Next:** distinct role homes, navigable records, study timeline, useful search/filtering, evidence review and auditable reporting/correction workflows.

**Then:** controlled live updates, richer analytical views, inspection packaging, appropriate personalization and motion polish.

**Not now:** patient portal, wearable/vitals graphics, a generic chatbot, wholesale backend rewrite, ornamental 3D scenes, dashboards filled with invented charts, or a claim of regulatory readiness based on visual polish.

**The central design principle:** every important screen should make clear **what is happening, why it matters, what the user can do, and how that action will be recorded**. That is what will make VITalWatch feel like a serious healthcare product rather than a presentation with tabs.

## 15. Reference basis

These references inform the proposal; they do not certify VITalWatch. External pages were consulted during this review. Undated living documentation is not evidence of a recent publication date.

- **[S1] NHS digital service manual — Design system and styles.** A relevant source for consistent, accessible public/staff healthcare services, not a visual identity to copy wholesale. [Design system](https://service-manual.nhs.uk/design-system) · [Styles](https://service-manual.nhs.uk/design-system/styles).
- **[S2] W3C — WCAG 2.2.** Proposed accessibility evaluation target. Search surfaced the standard; direct retrieval encountered a security check, so this review does not purport to reproduce the full standard. [WCAG 2.2](https://www.w3.org/TR/WCAG22/).
- **[S3] AHRQ PSNet — Alert Fatigue.** Full primer retrieved; page states last reviewed in 2024. Older human-factors guidance, potentially outdated in particulars; used here for the general warning against indiscriminate alerts. [Alert Fatigue](https://psnet.ahrq.gov/primer/alert-fatigue).
- **[S4] W3C — Understanding Animation from Interactions.** Supporting guidance for a reduced-motion requirement, not a claim that this criterion is an AA requirement. [Animation from Interactions](https://www.w3.org/WAI/WCAG22/Understanding/animation-from-interactions.html).
- **[S5] W3C — Understanding Accessible Authentication (Minimum).** Relevant to a usable login flow. [Accessible Authentication](https://www.w3.org/WAI/WCAG22/Understanding/accessible-authentication-minimum.html).
- **[S6] htmx — Documentation.** Technical basis for the incremental HTML-over-the-wire option; not a mandatory dependency or a version recommendation. [Documentation](https://htmx.org/docs/).

The strongest design source remains the repository's own domain: auditable trials, traceable sources and accountable human decisions.
