"""Phase 2 exit-gate smoke test (prompt.md §16, Phase 2 gate).

Verifies the public landing page against its gate: a first-time visitor can
learn why VITalWatch exists, what it does, who it is for, and what is and is
not real — with JavaScript disabled and reduced motion enabled, and with no
invented proof points, logos or claims anywhere.

Runs against a throwaway sandbox database (the real data/ctms.db is never
touched — DB_PATH is redirected before app import). Sections:

  1. Routing contract (prompt.md §4): anonymous gets the landing page, a
     signed-in user is routed to /portal/{role} (the post-merge front door),
     /about resolves, login?next=/ lands on the role portal, and the API
     gate is untouched.
  2. No CDN, self-hosted assets only (acceptance criterion 26).
  3. Landing structure (§8.3-§8.4, §8.8): every required section, CTA and the
     restrained navigation, in the DOM.
  4. Text art (§6.1.2, §6.1.3, §8.4.4): the five-stage path is a real ordered
     list in DOM order with deep links; the evidence chain is real mono text.
  5. Role selector (§8.4.5): radio-driven (works without JS), exactly the
     five personas of app/models.py::UserRole, and the no-permission-change
     disclaimer.
  6. Honesty (§8.4.7, §15) + the post-merge reconciliation (§1.1.1): no
     FHIR/SDTM export claims, no BM25/RRF retrieval claims, no
     investigation-board references, no seven-role vocabulary anywhere.
  7. No-JS / reduced-motion / accessibility mechanics.

Run:  python scripts/smoke_phase2.py
Exit: 0 when every check passes, 1 otherwise.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_SANDBOX = tempfile.mkdtemp(prefix="vw-phase2-smoke-")
os.environ["DB_PATH"] = str(Path(_SANDBOX) / "smoke.db")
os.environ["DEMO_ALLOW_HTTP"] = "1"  # TestClient is http://; writes demand HTTPS otherwise

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(cond), str(detail)))


def main() -> int:
    with TestClient(app, base_url="http://testserver") as client:
        # --- 1. routing contract -------------------------------------------
        r = client.get("/", follow_redirects=False)
        check("unauth GET / → 200", r.status_code == 200, r.status_code)
        html = r.text
        check("landing: hero thesis present", "See the risk. Follow the evidence. Act with confidence." in html)
        r = client.get("/about", follow_redirects=False)
        check("GET /about → 303 /#about", r.status_code == 303 and r.headers["location"] == "/#about", r.status_code)
        r = client.get("/api/search?q=AE", follow_redirects=False)
        check("unauth GET /api/search still 401 (gate untouched)", r.status_code == 401, r.status_code)

        # Sign in; next=/ must resolve through the front door to the role
        # portal, never the public page (§4).
        login_page = client.get("/login").text
        token = re.search(r'name="csrf_token" value="([^"]+)"', login_page).group(1)
        r = client.post("/login", data={"username": "safety.demo", "password": "AiiaSafety#01",
                                        "next": "/", "csrf_token": token},
                        follow_redirects=False)
        check("login with next=/ → 303 /", r.status_code == 303 and r.headers["location"] == "/", r.headers.get("location"))
        r = client.get("/", follow_redirects=False)
        check("authed GET / → 303 /portal/safety_officer",
              r.status_code == 303 and r.headers["location"] == "/portal/safety_officer", r.headers.get("location"))
        client.post("/logout", data={"csrf_token": token}, follow_redirects=False)

        # --- 2. no CDN, self-hosted assets ----------------------------------
        r = client.get("/")
        html = r.text
        check("landing: no Tailwind CDN", "cdn.tailwindcss.com" not in html)
        check("landing: no Google Fonts", "fonts.googleapis.com" not in html and "fonts.gstatic.com" not in html)
        check("landing: local asset stack linked", all(s in html for s in (
            "/static/fonts.css", "/static/tokens.css", "/static/vendor/tailwind.css",
            "/static/app.css", "/static/landing.css")))
        check("landing: js is deferred enhancement", '<script src="/static/landing.js" defer>' in html)
        for asset in ("/static/landing.css", "/static/landing.js"):
            r = client.get(asset)
            check(f"GET {asset} → 200", r.status_code == 200, r.status_code)
        css = client.get("/static/landing.css").text
        js = client.get("/static/landing.js").text

        # --- 3. landing structure -------------------------------------------
        for anchor in ("why", "product", "how", "roles", "trust", "proof", "about", "faq"):
            check(f"landing: section #{anchor} present", f'id="{anchor}"' in html)
        check("landing: primary CTA → /login?next=/", 'href="/login?next=/"' in html)
        check("landing: secondary CTA → #how", 'href="#how"' in html)
        check("landing: sign-in action present", 'href="/login"' in html)
        check("landing: restrained nav (6 items)", all(s in html for s in (
            ">Product</a>", ">How it works</a>", ">Roles</a>", ">Trust &amp; safety</a>",
            ">About</a>", ">Docs</a>")))
        check("landing: mobile drawer is a real <details> menu", '<details class="l-drawer"' in html)
        check("landing: docs link points at /docs", 'href="/docs"' in html)
        check("landing: final CTA section present", "Explore the demonstration." in html)
        # The footer must carry the SHARED §13.1 notice — the exact lines the
        # `notice_synthetic("footer")` macro emits, so a drift between the
        # footer copy and the macro's single copy source fails here.
        check("landing: footer carries shared synthetic notice",
              "Synthetic demonstration data — not for patient care or clinical decision-making." in html
              and "AE terms coded against a curated vocabulary, not MedDRA or WHODrug." in html)

        # --- 4. text art -----------------------------------------------------
        check("path: five stages in one ordered list", html.count('class="l-stage"') == 5 and '<ol class="l-path">' in html)
        order = [html.find(f'id="stage-{s}"') for s in ("detect", "understand", "investigate", "decide", "prove")]
        check("path: stages in DOM reading order", all(a != -1 for a in order) and order == sorted(order), order)
        check("path: deep-link nav to every stage", all(f'href="#stage-{s}"' in html for s in ("detect", "understand", "investigate", "decide", "prove")))
        check("path: every stage states the five facts", html.count("<dt>Input</dt>") == 5
              and html.count("<dt>System derives</dt>") == 5 and html.count("<dt>Human decides</dt>") == 5
              and html.count("<dt>Evidence kept</dt>") == 5 and html.count("<dt>Not claimed</dt>") == 5)
        check("path: Investigate stage is the escalation package (§11.4)",
              "escalation package" in html and "statutory response clock" in html)
        check("chain: monospace evidence chain present", "l-chain-track" in html and "prev" in html and "9f3e…c21a" in html)
        check("chain: current vocabulary (trial / participant, role on the row)",
              "participant" in html and "safety_officer" in html)
        check("motif: reference line rendered large (aria-hidden)", 'class="l-refmotif" aria-hidden="true"' in html)

        # --- 5. role selector ------------------------------------------------
        check("roles: five radio inputs (no-JS selector)", html.count('class="l-role-input"') == 5)
        check("roles: five persona panels", html.count("l-role-panel l-role-panel-") == 5)
        check("roles: selector-cannot-grant disclaimer", "changes this page's content only" in html)
        check("roles: exactly the five real roles", all(s in html for s in (
            "Volunteer / participant", ">Company</label>", ">Investigator</label>",
            ">Safety Officer</label>", ">Leadership</label>")))
        check("roles: each persona asks its §5.1 first-screen question", all(s in html for s in (
            "What is the state of my participation?",
            "What does my trial need from me right now?",
            "Which submissions and escalations need my decision today?",
            "Which event or reporting obligation requires attention next?",
            "Is the institution safe, compliant, and inspection-ready?")))

        # --- 6. honesty + post-merge reconciliation ---------------------------
        check("preview: labelled Synthetic demonstration", "Synthetic demonstration" in html and "not live telemetry" in html)
        check("preview: fixture values are static (snapshot label)", "2026-08-22" in html)
        check("preview: signal escalates (no investigation board)", "Safety-concern escalation" in html
              and "ESC-" in html and "INV-001" not in html)
        check("honesty: MedDRA/WHODrug negation present", "not MedDRA and not WHODrug" in html)
        check("honesty: audit guarantee is bounded", "cannot guarantee" in html and "first altered row" in html)
        # Retired capabilities must not be claimed anywhere (§1.1.1): the
        # investigation board, BM25/RRF retrieval and FHIR/SDTM exports were
        # deleted from the backend; the page may name them only as negations
        # ("no FHIR/SDTM export surface"). Assert no affirmative claim form.
        lowered = html.lower()
        check("reconciliation: no BM25/RRF/embedding retrieval claims",
              all(s not in lowered for s in ("bm25", "rrf", "concept expansion", "concept-expansion", "retrieval corpus")))
        check("reconciliation: FHIR/SDTM named only as an absent boundary",
              "fhir r4 resource shapes" not in lowered and "sdtm dm-domain mapping" not in lowered
              and "no fhir/sdtm export" in lowered)
        check("reconciliation: no seven-role vocabulary", all(s not in html for s in (
            "Principal investigator</label>", "Study coordinator", ">Monitor</label>",
            "Pharmacovigilance officer</label>", "Safety / medical reviewer</label>",
            "Regulator / quality reviewer", "Seven roles", "seven demo accounts")))
        check("reconciliation: no deleted-schema field names", "subject code" not in lowered
              and "subject" not in lowered)
        # Phrases that appear only in invented marketing. "Customer logos" and
        # "testimonials" are deliberately absent from this list: the proof
        # section's *negation* names them ("no customer logos… no testimonials"),
        # which is honest boundary copy, not a claim.
        slop = ["FDA approved", "HIPAA", "21 CFR Part 11", "ISO 13485", "trusted by",
                "our customers", "case study", "patients love", "SOC 2", "award-winning"]
        check("honesty: no invented proof-point language", not any(s.lower() in lowered for s in slop),
              [s for s in slop if s.lower() in lowered])
        check("honesty: concept renders not shipped as assets", "media-output" not in html and "img-mu2" not in html)
        imgs = re.findall(r"<img[^>]+>", html)
        check("imagery: only the product mark, always decorative", bool(imgs) and all(
            'src="/static/mark.svg"' in i and 'alt=""' in i for i in imgs), len(imgs))

        # --- 7. no-JS, reduced motion, a11y mechanics -------------------------
        check("css: scroll emphasis gated behind @supports", "@supports (animation-timeline: view())" in css)
        check("css: reduced-motion gate wraps the animation", "prefers-reduced-motion: no-preference" in css)
        check("css: smooth scroll only when motion allowed", "prefers-reduced-motion: no-preference" in css and "scroll-behavior: smooth" in css)
        check("css: stages readable without animation (no display:none on path)",
              not re.search(r"\.l-stage\s*\{[^}]*display\s*:\s*none", css))
        check("js: enhancement comment honours no-JS", "Nothing on this page depends on this file" in js)
        check("a11y: skip link present", "Skip to content" in html)
        check("a11y: single h1, main landmark", html.count("<h1") == 1 and '<main id="main">' in html)
        check("a11y: FAQ is progressive disclosure (≥8 details)", html.count("<details>\n        <summary>") >= 8 or len(re.findall(r"<details>\s*<summary>", html)) >= 8)
        check("a11y: roles are a labelled fieldset", "<fieldset" in html and "<legend" in html)
        check("a11y: nav landmarks labelled", 'aria-label="Primary"' in html)

    failures = [r for r in RESULTS if not r[1]]
    for name, ok, detail in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  -> {detail}"))
    print(f"\n{len(RESULTS) - len(failures)}/{len(RESULTS)} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
