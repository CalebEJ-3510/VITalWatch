"""Phase 4+5 exit-gate smoke test (prompt.md §16, Phase 4 and Phase 5 gates).

Phase 4 — work queues, study workspace, scalable interaction (§10, §7.2):

  1. Role gates hold at the ROUTE (not the nav): volunteer/company are refused
     the AE register, signals, and audit; leadership alone reads /audit.
  2. Every queue renders the shared contract: toolbar, honest summary with
     active-filter chips, URL-preserved state in pagination links, allowlisted
     sorts — and an honest empty state when nothing matches (the seeded
     portfolio starts with zero escalations; the test says so rather than
     pretending a list).
  3. The trial workspace has the persistent context header, eight real
     subviews as shareable URLs, and an unknown subview falls back to
     overview instead of 500ing.
  4. The worklist+inspector pattern is wired end-to-end on the AE queue:
     rows carry data-inspect-*, ?inspect=<id> deep-links, and /ae/{id}
     answers the inspector's X-Requested-With header with a bare fragment
     (no <html> shell) vs a full page without it.
  5. Container queries, not viewport hacks: queue.css carries
     container-type + @container rules.

Phase 5 — case, signal, investigation, evidence, audit (§11):

  6. Staff intake POST /ae files an event for a REAL participant/trial pair
     (investigator + safety_officer hold FILE_ADVERSE_EVENT; company and
     volunteer are refused), a mismatched pair is rejected, and the case
     page explains what is still incomplete rather than finalizing.
  7. The case record keeps the four concerns visibly separate and in
     order: clinical fact → reporting obligation → coding review → audit.
  8. Coding assist travels in a JSON request body under an X-CSRF-Token
     header — never a URL query string — and refuses headerless posts.
     The GET variant stays explicitly deprecated in the schema.
  9. The coding review round-trips on the newly filed (uncoded) case:
     the Safety Officer's decision redirects to the case page via a
     safe-internal `next`, and the case then shows who reviewed.
 10. The signal workspace shows the observation, the 2×2, the caveats,
     and an honest disposition (no faked stored review state); a pair
     that doesn't exist 404s.
 11. The escalation review package — the signature experience — renders
     the real state machine as a stepper and walks it end-to-end:
     raise → response → review → leadership decision → closed, with the
     audit record listed on the page; afterwards the escalation queue
     lists the walked package.
 12. The audit center states the bounded guarantee verbatim: chain
     verification "does not by itself certify" anything further.

Run:  python scripts/smoke_phase4.py
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

_SANDBOX = tempfile.mkdtemp(prefix="vw-phase4-smoke-")
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


def sign_in(client: TestClient, role: str) -> None:
    username, password = DEMO[role]
    page = client.get("/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    r = client.post("/login", data={"username": username, "password": password,
                                    "next": "/", "csrf_token": token},
                    follow_redirects=False)
    assert r.status_code == 303, f"login failed for {username}: {r.status_code}"


def csrf_meta(html: str) -> str:
    return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)


def csrf_form(html: str) -> str:
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def main() -> int:
    with TestClient(app, base_url="http://testserver") as client:
        db = sqlite3.connect(os.environ["DB_PATH"]); db.row_factory = sqlite3.Row
        pair = db.execute(
            "SELECT participant_code, trial_id FROM participants ORDER BY participant_code LIMIT 1"
        ).fetchone()
        trial_id = pair["trial_id"]
        ae_id = db.execute(
            "SELECT id FROM adverse_events WHERE serious=1 ORDER BY reported_at DESC LIMIT 1"
        ).fetchone()["id"]
        n_seeded_esc = db.execute("SELECT COUNT(*) n FROM escalations").fetchone()["n"]

        # ------------------------------------------------ 1. role gates (route-level)
        sign_in(client, "volunteer")
        for url in ("/ae", "/alerts", "/escalations", "/audit", "/signals"):
            r = client.get(url, follow_redirects=False)
            check(f"volunteer: GET {url} refused", r.status_code in (403, 303), r.status_code)
        sign_in(client, "company")
        check("company: GET /ae refused", client.get("/ae").status_code == 403)
        check("company: GET /signals refused", client.get("/signals").status_code == 403)
        check("company: GET /audit refused", client.get("/audit").status_code == 403)
        check("company: GET /alerts 200", client.get("/alerts").status_code == 200)
        sign_in(client, "safety_officer")
        check("safety: GET /audit refused", client.get("/audit").status_code == 403)
        check("safety: GET /signals 200", client.get("/signals").status_code == 200)

        # ------------------------------------------------ 2. queue contract on /ae
        r = client.get("/ae")
        ae_html = r.text
        check("ae queue: 200 + toolbar + list",
              r.status_code == 200 and "q-toolbar" in ae_html and "q-list" in ae_html)
        check("ae queue: rows inspectable (worklist+inspector §7.2)",
              "data-inspectable" in ae_html and "data-inspect-url=\"/ae/" in ae_html
              and "inspector-root" in ae_html)
        r = client.get("/ae", params={"clock": "breached", "serious": "1"})
        filtered = r.text
        check("ae queue: active-filter chips echo state",
              "q-chip" in filtered and "Breached" in filtered)
        check("ae queue: pagination/links preserve filters in URL",
              "clock=breached" in filtered and "serious=1" in filtered)
        check("ae queue: no clinical narrative ever in a link href",
              "narrative=" not in filtered)
        r = client.get("/ae", params={"sort": "reported_at", "dir": "asc"})
        check("ae queue: allowlisted sort accepted", r.status_code == 200)
        r = client.get("/ae", params={"sort": "narrative", "dir": "sideways"})
        check("ae queue: non-allowlisted sort rejected harmlessly (200, default sort)",
              r.status_code == 200)
        r = client.get("/ae", params={"q": ae_id})
        check("ae queue: search scoped to identifiers finds the case", ae_id in r.text)

        # /alerts queue
        sign_in(client, "company")
        r = client.get("/alerts")
        check("alerts queue: 200 + honest computed-on-read copy",
              r.status_code == 200 and "q-list" in r.text and "computed" in r.text.lower())
        r = client.get("/alerts", params={"severity": "critical"})
        check("alerts queue: severity filter echoes", "q-chip" in r.text)

        # /escalations queue — the seeded portfolio starts EMPTY; the queue must
        # say so honestly rather than fabricate rows. Rows are asserted after
        # the package walk below (block 11).
        r = client.get("/escalations", params={"status": "open"})
        check("escalations queue: honest empty state when nothing matches",
              r.status_code == 200 and "state-empty" in r.text and "q-list" not in r.text)
        check("escalations queue: filter chip echoes even when empty",
              "q-chip" in r.text, f"seeded={n_seeded_esc}")

        # /audit center
        sign_in(client, "leadership")
        r = client.get("/audit")
        audit_html = r.text
        check("audit center: 200 + chain status + verified-at",
              r.status_code == 200 and "verified" in audit_html.lower())
        check("audit center: bounded guarantee verbatim (§13.1)",
              "does not by itself certify" in audit_html)
        check("audit center: sortable headers + filter toolbar",
              "q-sortlink" in audit_html and "actor" in audit_html)
        r = client.get("/audit", params={"resource_type": "escalation"})
        check("audit center: resource filter narrows", r.status_code == 200 and "q-chip" in r.text)

        # ------------------------------------------------ 3. trial workspace
        sign_in(client, "investigator")
        r = client.get(f"/trial/{trial_id}")
        t_html = r.text
        check("trial: 200 + persistent context header",
              r.status_code == 200 and "ctx-head" in t_html and "Data as of" in t_html)
        check("trial: eight real subviews in subnav",
              all(f"view={v}" in t_html for v in
                  ("overview", "enrolment", "sites", "safety", "deviations",
                   "queries", "milestones", "activity")))
        check("trial: four status dimensions shown separately",
              all(s in t_html for s in ("Lifecycle:", "Operational:", "Safety:", "Leadership:")))
        r = client.get(f"/trial/{trial_id}", params={"view": "milestones"})
        check("trial: milestones subview renders server-computed timeline",
              r.status_code == 200 and "tl-track" in r.text)
        r = client.get(f"/trial/{trial_id}", params={"view": "not-a-view"})
        check("trial: unknown subview falls back to overview (no 500)",
              r.status_code == 200)
        r = client.get("/trial/NO-SUCH-TRIAL")
        check("trial: unknown trial 404s", r.status_code == 404)

        # ------------------------------------------------ 4. inspector end-to-end
        sign_in(client, "safety_officer")
        r = client.get("/ae", params={"inspect": ae_id})
        check("ae queue: ?inspect= deep link renders selected state",
              r.status_code == 200 and f'data-inspect-id="{ae_id}"' in r.text)
        r = client.get(f"/ae/{ae_id}", headers={"X-Requested-With": "inspector"})
        check("inspector fragment: bare partial, no <html> shell",
              r.status_code == 200 and "<html" not in r.text and "case-section" in r.text)
        check("inspector fragment: links deeper to the full record URL",
              f'href="/ae/{ae_id}"' in r.text)
        r = client.get(f"/ae/{ae_id}")
        check("full case page: has the <html> shell the fragment omits",
              r.status_code == 200 and "<html" in r.text)
        r = client.get("/ae/NO-SUCH-CASE", headers={"X-Requested-With": "inspector"})
        check("inspector: missing record 404s honestly", r.status_code == 404)

        # ------------------------------------------------ 5. container queries + assets
        queue_css = Path("app/static/queue.css").read_text(encoding="utf-8")
        check("queue.css: component container queries present (§6.2)",
              "container-type: inline-size" in queue_css and "@container" in queue_css)
        check("queue.css: stepper + case + assist + workspace styles present",
              all(s in queue_css for s in (".steps", ".case-section", ".assist-apply", ".ws-layout")))
        js = Path("app/static/coding-assist.js").read_text(encoding="utf-8")
        check("coding-assist.js: POST body only + X-CSRF-Token header (§7.3)",
              '"/api/pv/code"' in js and "X-CSRF-Token" in js and "JSON.stringify" in js)
        check("shell: coding-assist.js + inspector.js deferred on queue pages",
              "coding-assist.js" in ae_html and "inspector.js" in ae_html)

        # ------------------------------------------------ 6. staff intake POST /ae
        sign_in(client, "company")
        token = csrf_form(client.get("/escalations").text)
        r = client.post("/ae", data={
            "trial_id": trial_id, "participant_code": pair["participant_code"],
            "onset_date": "2026-09-10", "narrative": "company should not file this",
            "csrf_token": token}, follow_redirects=False)
        check("intake: company refused POST /ae (no FILE_ADVERSE_EVENT)", r.status_code == 403)

        sign_in(client, "investigator")
        token = csrf_form(client.get(f"/trial/{trial_id}").text)
        r = client.post("/ae", data={
            "trial_id": trial_id, "participant_code": "WRONG-PARTICIPANT-000",
            "onset_date": "2026-09-12", "narrative": "mismatched pair must be rejected",
            "csrf_token": token}, follow_redirects=False)
        check("intake: participant not on this trial → 400, nothing filed",
              r.status_code == 400, r.status_code)

        r = client.post("/ae", data={
            "trial_id": trial_id, "participant_code": pair["participant_code"],
            "onset_date": "2026-09-12", "narrative": "severe headache, resolved with rest",
            "severity": "severe", "causality": "possible", "outcome": "recovered",
            "csrf_token": token}, follow_redirects=False)
        loc = r.headers.get("location", "")
        check("intake: investigator files → 303 to the new case",
              r.status_code == 303 and re.match(r"^/ae/AE-.+\?filed=1$", loc), loc)
        new_case_url = loc.split("?")[0] if loc else ""
        r = client.get(loc)
        check("intake: case explains what is created and still incomplete",
              "written to the audit trail" in r.text and "not final" in r.text)

        # ------------------------------------------------ 7. four concerns, in order
        r = client.get(f"/ae/{ae_id}")
        case_html = r.text
        order = [case_html.find(s) for s in
                 ("Clinical fact", "Reporting obligation", "Coding review", "Audit history")]
        check("case: four concerns present, in order (§2)",
              all(i >= 0 for i in order) and order == sorted(order), order)

        # ------------------------------------------------ 8. coding-assist endpoint
        meta = csrf_meta(case_html)
        r = client.post("/api/pv/code", json={"narrative": "severe headache"},
                        headers={"X-CSRF-Token": meta})
        check("coding assist: JSON body + header → suggestions with match basis",
              r.status_code == 200 and r.json()["suggestions"]
              and "method" in r.json()["suggestions"][0], r.status_code)
        r = client.post("/api/pv/code", json={"narrative": "severe headache"})
        check("coding assist: missing X-CSRF-Token → 403", r.status_code == 403)
        spec = client.get("/openapi.json").json()
        check("coding assist: GET variant explicitly deprecated",
              spec["paths"]["/api/pv/code"]["get"].get("deprecated") is True)

        # ------------------------------------------------ 9. coding review round-trip
        # The newly filed case is guaranteed uncoded — review it there.
        sign_in(client, "safety_officer")
        page_html = client.get(new_case_url).text
        check("new case: uncoded, review form offered to Safety Officer",
              'action="/portal/safety_officer/ae/' in page_html
              and "data-coding-assist" in page_html)
        token = csrf_form(page_html)
        r = client.post(new_case_url.replace("/ae/", "/portal/safety_officer/ae/") + "/code",
                        data={"decision": "uncoded", "final_term": "", "final_code": "",
                              "next": new_case_url, "csrf_token": token},
                        follow_redirects=False)
        check("coding review: decision redirects to safe internal next",
              r.status_code == 303 and r.headers.get("location") == new_case_url,
              r.headers.get("location"))
        r = client.get(new_case_url)
        check("coding review: case shows who reviewed",
              "Reviewed by" in r.text and "safety.demo" in r.text)
        r = client.post(new_case_url.replace("/ae/", "/portal/safety_officer/ae/") + "/code",
                        data={"decision": "uncoded", "final_term": "", "final_code": "",
                              "next": "https://evil.example/phish", "csrf_token": token},
                        follow_redirects=False)
        check("coding review: external next refused (falls back to portal)",
              r.headers.get("location", "").startswith("/"), r.headers.get("location"))

        # ------------------------------------------------ 10. signal workspace
        r = client.get("/signals")
        sig_html = r.text
        check("signals queue: 200 + PRR tracks against the threshold line",
              r.status_code == 200 and "q-row-ref" in sig_html and "ref-mark" in sig_html)
        m = re.search(r'href="(/signals/[^"]+)"', sig_html)
        check("signals queue: rows link to a real detail URL", m is not None)
        if m:
            r = client.get(m.group(1))
            check("signal workspace: observation + 2×2 + caveats",
                  r.status_code == 200 and "sig-2x2" in r.text
                  and "Data-quality caveats" in r.text)
            check("signal workspace: honest disposition (no faked review state)",
                  "no stored review state" in r.text)
            check("signal workspace: non-causality stated",
                  "not causation" in r.text or "not an incidence rate" in r.text)
        r = client.get("/signals/NOPE/definitely-not-a-term")
        check("signal workspace: nonsense pair 404s honestly", r.status_code == 404)

        # ------------------------------------------------ 11. review package, end-to-end
        token = csrf_form(client.get("/escalations/new").text)
        r = client.post("/escalations", data={
            "trial_id": trial_id, "escalation_type": "safety_concern", "severity": "critical",
            "reason": "Smoke-test safety concern: two SAEs share a coded term.",
            "recommended_action": "Pause enrolment pending review.",
            "csrf_token": token}, follow_redirects=False)
        esc_url = r.headers.get("location", "")
        check("package: safety concern raised → 303 to its package",
              r.status_code == 303 and esc_url.startswith("/escalations/ESC-"), esc_url)
        r = client.get(esc_url)
        pkg = r.text
        check("package: stepper renders all five stages",
              pkg.count("step-head") == 5, pkg.count("step-head"))
        check("package: open state — response step current, clock running",
              "step-current" in pkg and "Statutory clock" in pkg and "Running" in pkg)
        check("package: audit record section lists the raise",
              "Audit record" in pkg and "safety.demo" in pkg)

        # Company responds (all nine fields — one missing must 400).
        sign_in(client, "company")
        token = csrf_form(client.get(esc_url).text)
        fields = {f: f"{f} text" for f in (
            "explanation", "investigation_findings", "root_cause", "immediate_action",
            "corrective_action", "preventive_action", "participant_impact",
            "expected_resolution", "responsible_person")}
        bad = dict(fields); del bad["root_cause"]; bad["csrf_token"] = token
        r = client.post(f"{esc_url}/respond", data=bad, follow_redirects=False)
        check("package: response with a field absent → 422 framework rejection",
              r.status_code == 422, r.status_code)
        blank = dict(fields); blank["root_cause"] = "   "; blank["csrf_token"] = token
        r = client.post(f"{esc_url}/respond", data=blank, follow_redirects=False)
        check("package: response with a field blank → 400 governance rejection",
              r.status_code == 400, r.status_code)
        r = client.post(f"{esc_url}/respond", data={**fields, "csrf_token": token},
                        follow_redirects=False)
        check("package: full nine-field response → 303", r.status_code == 303)
        r = client.get(esc_url)
        check("package: response step done, review current, clock stopped in time",
              "submitted" in r.text and "Responded in time" in r.text)

        # Officer review — escalate to leadership.
        sign_in(client, "safety_officer")
        token = csrf_form(client.get(esc_url).text)
        r = client.post(f"{esc_url}/review", data={
            "outcome": "escalate", "reason": "Root cause unproven; Leadership must weigh it.",
            "ai_finding_decision": "", "csrf_token": token}, follow_redirects=False)
        check("package: officer review escalate → 303", r.status_code == 303)
        sign_in(client, "leadership")
        r = client.get(esc_url)
        check("package: leadership step current, review recorded with reason",
              "with Leadership now" in r.text and "Root cause unproven" in r.text)

        # Leadership decides with conditions.
        token = csrf_form(r.text)
        r = client.post(f"{esc_url}/decision", data={
            "decision": "resume", "reason": "Corrective plan is adequate; resume with conditions.",
            "conditions": "Safety concern resolved\nUpdated report submitted",
            "csrf_token": token}, follow_redirects=False)
        check("package: leadership decision → 303", r.status_code == 303)
        r = client.get(esc_url)
        check("package: closed — decision, rationale and conditions on the page",
              "Resume" in r.text and "Corrective plan is adequate" in r.text
              and "Safety concern resolved" in r.text)
        check("package: full arc present in one page (raise→decision→audit)",
              all(s in r.text for s in
                  ("Why it was raised", "Company response", "Officer review",
                   "Leadership decision", "Audit record")))

        # The queue now lists the walked package (no longer the seeded empty state).
        r = client.get("/escalations")
        check("escalations queue: lists the walked package after the arc",
              "q-list" in r.text and esc_url.rsplit("/", 1)[-1] in r.text)

        # ------------------------------------------------ 12. audit integrity after the arc
        r = client.get("/audit", params={"q": esc_url.rsplit("/", 1)[-1]})
        check("audit center: the package's arc is findable by id",
              r.status_code == 200 and "escalation" in r.text)

    # ---- report -------------------------------------------------------------
    width = max(len(n) for n, _, _ in RESULTS)
    failed = 0
    for name, ok, detail in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {detail if not ok else ''}")
        failed += 0 if ok else 1
    print(f"\n{len(RESULTS) - failed}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
