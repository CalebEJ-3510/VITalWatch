"""Phase 1 exit-gate smoke test (prompt.md §16, Phase 1 gate).

Post-merge revision (2026-09-16): the backend was reconciled to the five-role
CTMS model (`volunteer` / `company` / `investigator` / `safety_officer` /
`leadership`, one dashboard per role at /portal/{role}). The old seven-role
lens routes (/role/*), /home, /portfolio, /investigation, /study/* and
/api/alerts no longer exist; this gate now verifies the current truth:

  1. Unauthenticated requests are gated: `/` is the public landing page by
     design (§4), every other page redirects to /login, every /api/* returns
     401 JSON.
  2. No CDN request renders any page (Tailwind/Google Fonts gone; local asset
     links present) — acceptance criterion 26.
  3. Every one of the five demo accounts signs in and is routed to its own
     portal dashboard — never to a dashboard of another role.
  4. Server-side role enforcement: forbidden routes 403 (the nav reflects the
     gate; it never substitutes for it) — and the rendered dashboards contain
     no link a role cannot open (§18.8: no promotion).
  5. Every primary page route renders for a role permitted to see it.
  6. Self-hosted static assets actually serve.
  7. The request-body coding endpoint: 403 without a CSRF header, 200 with
     one; the deprecated GET twin still answers for /docs compatibility, and
     no page wires it.
  8. The orphaned pre-merge module (app/workspace.py + ops_home.html,
     prompt.md §1.1.2) is gone and unreferenced — it must not drift back.

Run:  python scripts/smoke_phase1.py
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

_SANDBOX = tempfile.mkdtemp(prefix="vw-phase1-smoke-")
os.environ["DB_PATH"] = str(Path(_SANDBOX) / "smoke.db")
os.environ["DEMO_ALLOW_HTTP"] = "1"  # TestClient is http://; writes demand HTTPS otherwise

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []

ROOT = Path(__file__).resolve().parent.parent

DEMO = {
    "volunteer.demo": ("CtmsVolunteer#01", "volunteer"),
    "company.demo": ("AiiaCompany#01", "company"),
    "investigator.demo": ("AiiaTrialLead#01", "investigator"),
    "safety.demo": ("AiiaSafety#01", "safety_officer"),
    "leadership.demo": ("AiiaLeadership#01", "leadership"),
}


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(cond), str(detail)))


def sign_in(client: TestClient, username: str, password: str) -> None:
    page = client.get("/login")
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)
    r = client.post("/login", data={"username": username, "password": password,
                                    "next": "/", "csrf_token": token},
                    follow_redirects=False)
    assert r.status_code == 303, f"login failed for {username}: {r.status_code}"


def main() -> int:
    with TestClient(app, base_url="http://testserver") as client:
        # --- 1. unauthenticated gating -------------------------------------
        r = client.get("/", follow_redirects=False)
        check("unauth GET / → 200 (public landing, §4)",
              r.status_code == 200 and "See the risk" in r.text, r.status_code)
        for path in ("/portal/safety_officer", "/escalations", "/ae", "/signals", "/audit"):
            r = client.get(path, follow_redirects=False)
            check(f"unauth GET {path} → 303 /login",
                  r.status_code == 303 and r.headers["location"].startswith("/login"), r.status_code)
        r = client.get("/api/search?q=AE", follow_redirects=False)
        check("unauth GET /api/search is 401 JSON", r.status_code == 401 and "detail" in r.json(), r.status_code)
        r = client.post("/api/pv/code", json={"narrative": "fever"}, follow_redirects=False)
        check("unauth POST /api/pv/code is 401 JSON", r.status_code == 401, r.status_code)

        # --- 2. login page renders without any CDN -------------------------
        r = client.get("/login")
        html = r.text
        check("GET /login 200", r.status_code == 200, r.status_code)
        check("login: no Tailwind CDN", "cdn.tailwindcss.com" not in html)
        check("login: no Google Fonts", "fonts.googleapis.com" not in html and "fonts.gstatic.com" not in html)
        check("login: local assets linked", all(s in html for s in ("/static/fonts.css", "/static/tokens.css", "/static/vendor/tailwind.css")))
        check("login: CSRF token present", 'name="csrf_token"' in html)

        # --- 3. every demo account lands on its own portal ------------------
        # (Signing in again simply replaces the session cookie — no logout
        # needed between identities.)
        dashboards: dict[str, str] = {}
        for username, (password, role) in DEMO.items():
            sign_in(client, username, password)
            r = client.get("/", follow_redirects=False)
            check(f"{username}: GET / → 303 /portal/{role}",
                  r.status_code == 303 and r.headers["location"] == f"/portal/{role}", r.headers.get("location"))
            r = client.get(f"/portal/{role}")
            check(f"{username}: /portal/{role} → 200", r.status_code == 200, r.status_code)
            dashboards[role] = r.text
            check(f"{username}: no CDN anywhere",
                  "cdn.tailwindcss.com" not in r.text and "fonts.googleapis.com" not in r.text)
            check(f"{username}: csrf meta published for fetch()", 'name="csrf-token"' in r.text)

        # --- 4. server-side enforcement + no promotion -----------------------
        forbidden = {
            "volunteer.demo": ["/ae", "/signals", "/escalations", "/audit", "/portal/company"],
            "company.demo": ["/audit", "/search", "/portal/safety_officer", "/portal/leadership"],
            # Note: "/ae" is deliberately NOT forbidden for the investigator —
            # the route grants SAFETY_OFFICER + INVESTIGATOR (main.py) because
            # both hold FILE_ADVERSE_EVENT (auth.py), and the Phase 4 gate has
            # the investigator file an AE end-to-end. Asserting a 403 here was
            # a stale seven-role leftover and contradicted the shipped design.
            "investigator.demo": ["/audit", "/search", "/portal/safety_officer"],
            "safety.demo": ["/audit", "/search", "/portal/leadership", "/portal/company"],
            "leadership.demo": ["/portal/volunteer", "/portal/company", "/portal/investigator", "/portal/safety_officer"],
        }
        for username, paths in forbidden.items():
            password, role = DEMO[username]
            sign_in(client, username, password)
            for path in paths:
                check(f"{username}: GET {path} → 403", client.get(path).status_code == 403, path)

        # No promotion: a dashboard must never link a role into a screen it
        # cannot open (§18.8). /audit and /search are leadership-only;
        # /escalations is closed to volunteers; /portal/{other} to everyone.
        check("investigator dashboard: no /audit link", 'href="/audit"' not in dashboards["investigator"])
        check("investigator dashboard: no leadership portal link", "/portal/leadership" not in dashboards["investigator"])
        check("safety dashboard: no /audit link", 'href="/audit"' not in dashboards["safety_officer"])
        check("company dashboard: no /audit link", 'href="/audit"' not in dashboards["company"])
        check("company dashboard: no /search link", 'href="/search"' not in dashboards["company"])
        check("volunteer dashboard: no /escalations link", 'href="/escalations"' not in dashboards["volunteer"])
        check("volunteer dashboard: no staff-only links",
              all(s not in dashboards["volunteer"] for s in (
                  'href="/ae"', 'href="/signals"', 'href="/audit"',
                  'href="/search"', 'action="/search"')))
        # The portal-shell search form targets /search, which is leadership-only —
        # it must not render for the four other roles (§18.8).
        for role in ("volunteer", "company", "investigator", "safety_officer"):
            check(f"{role} dashboard: no /search form (leadership-only route)",
                  'action="/search"' not in dashboards[role])
        check("leadership dashboard keeps the /search form",
              'action="/search"' in dashboards["leadership"])

        # --- 5. every primary page renders for a permitted role --------------
        sign_in(client, "safety.demo", DEMO["safety.demo"][0])
        for path in ("/ae", "/signals", "/escalations", "/escalations/new"):
            check(f"safety: GET {path} → 200", client.get(path).status_code == 200, path)
        sign_in(client, "leadership.demo", DEMO["leadership.demo"][0])
        for path in ("/search", "/audit", "/escalations"):
            check(f"leadership: GET {path} → 200", client.get(path).status_code == 200, path)
        sign_in(client, "company.demo", DEMO["company.demo"][0])
        check("company: GET /portal/company/operations → 200",
              client.get("/portal/company/operations").status_code == 200)

        # A trial workspace renders (id discovered from the seeded sandbox).
        db = sqlite3.connect(os.environ["DB_PATH"]); db.row_factory = sqlite3.Row
        trial = db.execute("SELECT id FROM trials ORDER BY id LIMIT 1").fetchone()
        sign_in(client, "investigator.demo", DEMO["investigator.demo"][0])
        if trial:
            check("investigator: GET /trial/{id} → 200",
                  client.get(f"/trial/{trial['id']}").status_code == 200, trial["id"])

        # --- 6. self-hosted assets serve ------------------------------------
        for asset in ("/static/vendor/tailwind.css", "/static/fonts.css",
                      "/static/tokens.css", "/static/fonts/manrope-latin-var.woff2",
                      "/static/fonts/fraunces-latin-var.woff2"):
            r = client.get(asset)
            check(f"GET {asset} → 200", r.status_code == 200, r.status_code)
        check("GET /static/mark.svg without session → 200", client.get("/static/mark.svg").status_code == 200)

        # --- 7. request-body coding endpoint ---------------------------------
        sign_in(client, "safety.demo", DEMO["safety.demo"][0])
        r = client.post("/api/pv/code", json={"narrative": "loose motion since yesterday"})
        check("POST /api/pv/code without CSRF → 403", r.status_code == 403, r.status_code)
        meta = re.search(r'name="csrf-token" content="([^"]+)"', client.get("/portal/safety_officer").text).group(1)
        r = client.post("/api/pv/code", json={"narrative": "loose motion since yesterday"},
                        headers={"X-CSRF-Token": meta})
        check("POST /api/pv/code with CSRF → 200", r.status_code == 200, r.status_code)
        if r.status_code == 200:
            body = r.json()
            check("POST code returns a suggestion", len(body["suggestions"]) >= 1, body["suggestions"][:1])
            check("POST code names the curated vocabulary", "not MedDRA" in body["vocabulary"])
        r = client.get("/api/pv/code", params={"narrative": "headache"})
        check("GET /api/pv/code (deprecated twin) still answers", r.status_code == 200, r.status_code)
        # …but no page may wire the narrative-in-URL form (§0.1, criterion 25).
        check("no template wires the deprecated GET coding route",
              not any("api/pv/code?narrative" in p.read_text(encoding="utf-8", errors="ignore")
                      for p in (ROOT / "app" / "templates").rglob("*.html")))

        # --- 8. orphaned pre-merge module stays gone (§1.1.2) -----------------
        check("app/workspace.py removed", not (ROOT / "app" / "workspace.py").exists())
        check("ops_home.html removed", not (ROOT / "app" / "templates" / "ops_home.html").exists())
        main_src = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
        check("main.py does not import the orphan module",
              "from .workspace" not in main_src and "import workspace" not in main_src)
        check("no template extends or includes ops_home",
              not any("ops_home" in p.read_text(encoding="utf-8", errors="ignore")
                      for p in (ROOT / "app" / "templates").rglob("*.html")))

    failures = [r for r in RESULTS if not r[1]]
    for name, ok, detail in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  -> {detail}"))
    print(f"\n{len(RESULTS) - len(failures)}/{len(RESULTS)} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
