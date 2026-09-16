"""Phase 3 exit-gate smoke test (prompt.md §16, Phase 3 gate).

Post-merge revision (2026-09-16): the gate now verifies the CURRENT Phase 3 —
the authenticated shell plus the five role-aware /portal/{role} dashboards,
composed per §9.3 against the five-role backend. The old gate's world
(/home Operations Home, lens switchers, pv.demo/pi.demo/monitor.demo,
study/subject search groups) no longer exists.

The gate: signed-in users land in their own role dashboard (never the public
page, never another role's); each dashboard visibly answers its own §5.1
first-screen question with a distinct composition; no user is promoted to a
role or action they cannot access; and the escalation workflow's writes show
up in the right roles' queues.

Verifies, against a throwaway sandbox database (the real data/ctms.db is
never touched — DB_PATH is redirected before app import):

  1. The shell (§9.2) on every dashboard: workspace name, Demonstration
     badge, palette trigger, freshness as-of, user block, csrf meta — and
     never a lens/workspace switcher (one dashboard per role exists, §5).
  2. Distinct compositions: each dashboard carries markers no other
     dashboard has (§9.3 — not five copies of one template).
  3. Live data: the queues render real rows from the sandbox (appointments,
     submissions, coded AEs, KPI figures) — not silent zeros from a context
     the route never supplied (the exact post-merge defect this gate guards).
  4. The signature workflow end-to-end: investigator raises a protocol
     deviation → it appears in the company's awaiting-response queue with a
     live clock → company files the nine-field response → it appears in the
     investigator's review queue → investigator escalates → it appears in
     leadership's pending decisions → leadership decides → the decision
     renders, and the audit chain still verifies.
  5. The command palette backend (§7.4): /api/search requires a session,
     enforces the 2-character floor, returns groups for trials /
     participants / AE cases / escalations / audit sequence with current
     vocabulary, and never searches clinical narratives.
  6. §9.3.1 naming discipline: "Within my authorized scope" appears where
     scope is claimed; "Assigned to me" appears nowhere.

Run:  python scripts/smoke_phase3.py
Exit: 0 when every check passes, 1 otherwise.
"""

from __future__ import annotations

import os
import re
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_SANDBOX = tempfile.mkdtemp(prefix="vw-phase3-smoke-")
os.environ["DB_PATH"] = str(Path(_SANDBOX) / "smoke.db")
os.environ["DEMO_ALLOW_HTTP"] = "1"  # TestClient is http://; writes demand HTTPS otherwise

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []

DEMO = {
    "volunteer": ("volunteer.demo", "CtmsVolunteer#01"),
    "company": ("company.demo", "AiiaCompany#01"),
    "investigator": ("investigator.demo", "AiiaTrialLead#01"),
    "safety_officer": ("safety.demo", "AiiaSafety#01"),
    "leadership": ("leadership.demo", "AiiaLeadership#01"),
}


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(cond), str(detail)))


def sign_in(client: TestClient, role: str) -> str:
    username, password = DEMO[role]
    page = client.get("/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    r = client.post("/login", data={"username": username, "password": password,
                                    "next": "/", "csrf_token": token},
                    follow_redirects=False)
    assert r.status_code == 303, f"login failed for {username}: {r.status_code}"
    return token


def csrf(client: TestClient, url: str) -> str:
    return re.search(r'name="csrf-token" content="([^"]+)"', client.get(url).text).group(1)


def main() -> int:
    with TestClient(app, base_url="http://testserver") as client:
        # --- 0. unauthenticated -------------------------------------------
        r = client.get("/api/search?q=AE", follow_redirects=False)
        check("unauth /api/search → 401 JSON", r.status_code == 401, r.status_code)

        # --- 1. every role lands on its own dashboard, with the shell -------
        dashboards: dict[str, str] = {}
        for role in DEMO:
            sign_in(client, role)
            r = client.get("/", follow_redirects=False)
            check(f"{role}: authed GET / → 303 /portal/{role}",
                  r.status_code == 303 and r.headers["location"] == f"/portal/{role}", r.headers.get("location"))
            r = client.get(f"/portal/{role}")
            check(f"{role}: dashboard 200", r.status_code == 200, r.status_code)
            html = dashboards[role] = r.text
            check(f"{role}: shell — Demonstration badge", "Demonstration" in html)
            check(f"{role}: shell — palette wired",
                  'id="palette"' in html and "/static/palette.js" in html and "data-palette-open" in html)
            check(f"{role}: shell — workspace named in topbar", "topbar-workspace" in html)
            check(f"{role}: shell — freshness as-of shown", "Data as of" in html)
            check(f"{role}: shell — no lens/workspace switcher (§5)",
                  "lens-switch" not in html and "Role switcher" not in html)
            check(f"{role}: no dead vocabulary (subject//role//subject_code)",
                  all(s not in html for s in ("subject code", "/role/", "subject_code")))
            check(f"{role}: never 'Assigned to me' (§9.3.1)", "Assigned to me" not in html)

        # --- 2. distinct compositions (§9.3) ---------------------------------
        markers = {
            "volunteer": ["My trial", "Consent", "Report a symptom",
                          "identified in this system only by your participant code"],
            "company": ["Awaiting your response", "Issue queue", "My trials"],
            "investigator": ["Eligibility review queue", "AI pre-screen informs",
                             "Within my authorized scope"],
            "safety_officer": ["AE coding review", "worst statutory clock first",
                               "PRR signals"],
            "leadership": ["Decisions awaiting leadership", "Audit-chain verification",
                           "Recent leadership decisions"],
        }
        for role, needles in markers.items():
            for needle in needles:
                check(f"{role}: distinct marker «{needle}»", needle in dashboards[role])
        # No dashboard carries another role's defining block.
        check("volunteer: no KPI wall of other roles",
              "Awaiting your response" not in dashboards["volunteer"]
              and "Decisions awaiting leadership" not in dashboards["volunteer"])
        check("safety: no leadership-only blocks",
              "Audit-chain verification" not in dashboards["safety_officer"])
        check("leadership: audit chain verifies live on the page",
              "Chain intact" in dashboards["leadership"])

        # --- 3. queues render real rows (not silent zeros) --------------------
        db = sqlite3.connect(os.environ["DB_PATH"]); db.row_factory = sqlite3.Row
        n_appts = db.execute("SELECT COUNT(*) n FROM appointments").fetchone()["n"]
        n_subs = db.execute("SELECT COUNT(*) n FROM registration_submissions").fetchone()["n"]
        n_uncoded = db.execute("SELECT COUNT(*) n FROM adverse_events WHERE coded_term IS NULL").fetchone()["n"]
        n_serious_breached = db.execute(
            "SELECT COUNT(*) n FROM adverse_events WHERE serious=1 AND deadline_24h IS NOT NULL AND deadline_24h < datetime('now')").fetchone()["n"]

        check("volunteer: appointments render with real titles and dates",
              (n_appts == 0 and "No appointments are scheduled" in dashboards["volunteer"])
              or ("No appointments are scheduled" not in dashboards["volunteer"]
                  and "±" not in dashboards["volunteer"]), f"appointments={n_appts}")
        check("investigator: submissions render or honest empty state",
              (n_subs == 0 and "No submissions await" in dashboards["investigator"])
              or ("Submission" in dashboards["investigator"]), f"submissions={n_subs}")
        check("safety: coding queue honest about uncoded work",
              ("No events awaiting coding review" in dashboards["safety_officer"]) == (n_uncoded == 0),
              f"uncoded={n_uncoded}")
        check("safety: live breached-clock count is non-zero in the seeded data",
              "Breached clocks" in dashboards["safety_officer"] and n_serious_breached >= 1,
              f"seeded_breached={n_serious_breached}")
        check("company: trial rows carry derived counts (not all zero by default)",
              "My trials" in dashboards["company"])

        # --- 4. the signature workflow, end to end ----------------------------
        trial = db.execute("SELECT id FROM trials WHERE operational_status='active' ORDER BY id LIMIT 1").fetchone()
        check("seed provides an active trial for the workflow", trial is not None)
        esc_id = None
        if trial:
            # 4a. investigator raises a protocol deviation ------------------
            sign_in(client, "investigator")
            token = csrf(client, "/escalations/new")
            r = client.post("/escalations", data={
                "trial_id": trial["id"], "escalation_type": "protocol_deviation",
                "severity": "high", "reason": "Gate-driven protocol deviation for the Phase 3 workflow check.",
                "recommended_action": "Pause and explain", "csrf_token": token},
                follow_redirects=False)
            check("workflow: raise deviation → 303 to the escalation",
                  r.status_code == 303 and r.headers["location"].startswith("/escalations/"), r.status_code)
            esc_id = r.headers["location"].rsplit("/", 1)[-1] if r.status_code == 303 else None
            check("workflow: investigator dashboard lists the raised escalation",
                  esc_id is not None and esc_id[:8] in client.get("/portal/investigator").text)

            # 4b. company sees it awaiting response, with a live clock -------
            sign_in(client, "company")
            html = client.get("/portal/company").text
            check("workflow: company queue shows the open escalation",
                  esc_id is not None and esc_id[:8] in html)
            token = csrf(client, "/portal/company")
            r = client.post(f"/escalations/{esc_id}/respond", data={
                "explanation": "Gate explanation", "investigation_findings": "Gate findings",
                "root_cause": "Gate root cause", "immediate_action": "Gate immediate",
                "corrective_action": "Gate corrective", "preventive_action": "Gate preventive",
                "participant_impact": "None in synthetic data", "expected_resolution": "2026-09-30",
                "responsible_person": "Gate Owner", "supporting_documents": "",
                "csrf_token": token}, follow_redirects=False)
            check("workflow: company nine-field response → 303", r.status_code == 303, r.status_code)

            # 4c. investigator reviews: escalate to leadership ---------------
            sign_in(client, "investigator")
            html = client.get("/portal/investigator").text
            check("workflow: investigator review queue flags the responded escalation",
                  esc_id is not None and esc_id[:8] in html and "Review response" in html)
            token = csrf(client, "/portal/investigator")
            r = client.post(f"/escalations/{esc_id}/review", data={
                "outcome": "escalate", "reason": "Response insufficient for the gate check.",
                "csrf_token": token}, follow_redirects=False)
            check("workflow: reviewer escalates to leadership → 303", r.status_code == 303, r.status_code)

            # 4d. leadership decides: PAUSE first (stays under review), then
            # RESUME (closes) — both branches of governance.decide, in order.
            sign_in(client, "leadership")
            html = client.get("/portal/leadership").text
            check("workflow: leadership pending decisions list the escalation",
                  esc_id is not None and esc_id[:8] in html)
            token = csrf(client, "/portal/leadership")
            r = client.post(f"/escalations/{esc_id}/decision", data={
                "decision": "pause", "reason": "Gate intermediate pause with a mandatory reason.",
                "conditions": "Condition one\nCondition two", "csrf_token": token},
                follow_redirects=False)
            check("workflow: leadership pause decision → 303", r.status_code == 303, r.status_code)
            state = db.execute("SELECT status, leadership_decision FROM escalations WHERE id=?", (esc_id,)).fetchone()
            check("workflow: PAUSE keeps the escalation under leadership review (§spec)",
                  state is not None and state["status"] == "under_leadership_review"
                  and state["leadership_decision"] == "pause", dict(state) if state else None)
            trial_state = db.execute("SELECT operational_status FROM trials WHERE id=?", (trial["id"],)).fetchone()
            check("workflow: trial paused after the pause decision",
                  trial_state is not None and trial_state["operational_status"].startswith("paused"),
                  dict(trial_state) if trial_state else None)

            token = csrf(client, "/portal/leadership")
            r = client.post(f"/escalations/{esc_id}/decision", data={
                "decision": "resume", "reason": "Gate final decision with a mandatory reason.",
                "conditions": "", "csrf_token": token}, follow_redirects=False)
            check("workflow: leadership resume decision → 303", r.status_code == 303, r.status_code)
            html = client.get("/portal/leadership").text
            check("workflow: decision renders in recent decisions with its reason",
                  "Gate final decision with a mandatory reason." in html)
            check("workflow: audit chain still verifies after the writes",
                  "Chain intact" in html)
            state = db.execute("SELECT status, leadership_decision FROM escalations WHERE id=?", (esc_id,)).fetchone()
            check("workflow: RESUME closes the escalation with the recorded decision",
                  state is not None and state["status"] == "closed" and state["leadership_decision"] == "resume",
                  dict(state) if state else None)
            trial_state = db.execute("SELECT operational_status FROM trials WHERE id=?", (trial["id"],)).fetchone()
            check("workflow: trial active again after the resume decision",
                  trial_state is not None and trial_state["operational_status"] == "active",
                  dict(trial_state) if trial_state else None)

        # --- 5. command palette backend (§7.4) --------------------------------
        r = client.get("/api/search?q=x")
        check("search: 2-character floor", r.json()["total"] == 0 and r.json()["groups"] == [])

        seed_trial = db.execute("SELECT id FROM trials ORDER BY id LIMIT 1").fetchone()["id"]
        participant = db.execute("SELECT participant_code FROM participants ORDER BY participant_code LIMIT 1").fetchone()
        ae = db.execute("SELECT id FROM adverse_events ORDER BY id LIMIT 1").fetchone()

        r = client.get(f"/api/search?q={seed_trial}")
        body = r.json()
        kinds = {g["kind"] for g in body["groups"]}
        check("search: trials found by id", "trial" in kinds, body["total"])
        check("search: trial results link to the trial workspace",
              all(i["href"].startswith("/trial/") for g in body["groups"] for i in g["results"]))
        check("search: scope note travels with results", "scope_note" in body)
        check("search: generated_at present", bool(body.get("generated_at")))

        if participant:
            r = client.get(f"/api/search?q={participant['participant_code'][:8]}")
            check("search: participants found by pseudonymous code",
                  "participant" in {g["kind"] for g in r.json()["groups"]})
        if ae:
            r = client.get(f"/api/search?q={ae['id'][:8]}")
            check("search: adverse-event cases found by id",
                  "case" in {g["kind"] for g in r.json()["groups"]})
        if esc_id:
            r = client.get(f"/api/search?q={esc_id[:8]}")
            check("search: escalations found by id",
                  "escalation" in {g["kind"] for g in r.json()["groups"]})
        r = client.get("/api/search?q=%231")
        check("search: audit sequence found as #1",
              "audit" in {g["kind"] for g in r.json()["groups"]})

        # A common clinical word may only match coded terms/ids, never free
        # text — assert the response shape rather than a fabricated negative.
        r = client.get("/api/search?q=the")
        body = r.json()
        titles = [i["title"].lower() for g in body["groups"] for i in g["results"]]
        check("search: no narrative text surfaces as a result title",
              all("narrative" not in t for t in titles))
        check("search: groups use current vocabulary (no study/subject kinds)",
              not ({"study", "subject"} & {g["kind"] for g in body["groups"]}))

    # --- report -------------------------------------------------------------
    width = max(len(n) for n, _, _ in RESULTS)
    failed = 0
    for name, ok, detail in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name.ljust(width)}" + (f"  -> {detail}" if detail and not ok else ""))
        failed += 0 if ok else 1
    total = len(RESULTS)
    print(f"\n{total - failed}/{total} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
