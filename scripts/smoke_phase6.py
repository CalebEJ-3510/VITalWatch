"""Phase 6 exit-gate smoke test (prompt.md §16, Phase 6 gate).

Quality, accessibility, performance and verification — "the experience remains
understandable with motion disabled, slow responses, no results, stale data,
and expired sessions." This suite pins the contracts that make the Phase 6
work (rebuilt sign-in gateway with quick-fill demo chips; the landing motion
layer) safe, plus regression guards for every defect fixed in this phase.

Runs against a throwaway sandbox database (DB_PATH is redirected before app
import — the real data/ctms.db is never touched). Sections:

  1. Sign-in gateway: renders, self-hosted assets, CSRF, error surfacing
     (regression guard — the GET handler used to swallow ?error=).
  2. Quick-fill demo chips: exactly the five accounts app/datagen.py seeds,
     each a non-submitting button with its credentials printed on it (the
     no-JS fallback), an aria label, and a noscript note. Chips never grant:
     the volunteer demo account is still refused /audit after sign-in.
  3. Landing motion layer: hero line spans, [data-reveal] coverage, the
     fixture clock's static fallback text, the evidence-chain hashes, the
     scroll hairline — and every hiding/animating rule fenced behind both
     html.ljs (JS-gated) and prefers-reduced-motion: no-preference.
  4. No-JS completeness: drawer is a <details>, the persona selector is radio
     inputs, no inline event handlers anywhere on the public pages.
  5. State contracts (§10.1) and display rules (§13.2): the six state macros
     in _components.html; unknown/stale tokens with their dotted/dashed rules.
  6. Accessibility (§13.3): skip links, focus-visible, labelled icon-only
     controls, role=alert on the sign-in error, labelled landmarks.
  7. Trust-copy consolidation (§13.1): the shared notice macro is the single
     copy source and both public footers render its mandated lines.
  8. Session/expiry behavior: a bogus session cookie redirects to /login
     instead of 500ing; writes without a session fail, never silently succeed.
  9. Regression guards for Phase 6 debug: the investigator can read /ae (the
     shipped design — main.py grants it, FILE_ADVERSE_EVENT is held) while the
     volunteer is refused; .env.example names the five current accounts and
     none of the retired seven-role-era ones.

Run:  python scripts/smoke_phase6.py
Exit: 0 when every check passes, 1 otherwise.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_SANDBOX = tempfile.mkdtemp(prefix="vw-phase6-smoke-")
os.environ["DB_PATH"] = str(Path(_SANDBOX) / "smoke.db")
os.environ["DEMO_ALLOW_HTTP"] = "1"  # TestClient is http://; writes demand HTTPS otherwise

from fastapi.testclient import TestClient  # noqa: E402

from app.datagen import DEMO_USERS  # noqa: E402 — the one credential source of truth
from app.main import app  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []
ROOT = Path(__file__).resolve().parent.parent


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(cond), str(detail)))


def csrf(html: str) -> str:
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def sign_in(client: TestClient, username: str, password: str) -> None:
    token = csrf(client.get("/login").text)
    r = client.post("/login", data={"username": username, "password": password,
                                    "next": "/", "csrf_token": token},
                    follow_redirects=False)
    assert r.status_code == 303, f"login failed for {username}: {r.status_code}"


def main() -> int:
    with TestClient(app, base_url="http://testserver") as client:

        # --- 1. sign-in gateway ---------------------------------------------
        r = client.get("/login?next=/")
        html = r.text
        check("login: GET 200", r.status_code == 200, r.status_code)
        check("login: no CDN anywhere",
              "cdn.tailwindcss.com" not in html
              and "fonts.googleapis.com" not in html and "fonts.gstatic.com" not in html)
        check("login: self-hosted asset stack incl. login.css",
              all(s in html for s in ("/static/fonts.css", "/static/tokens.css",
                                      "/static/vendor/tailwind.css", "/static/app.css",
                                      "/static/login.css")))
        check("login: js deferred enhancement", '<script src="/static/login.js" defer></script>' in html)
        check("login: CSRF + next hidden fields",
              'name="csrf_token"' in html and 'name="next" value="/"' in html)
        check("login: password manager support (autocomplete)",
              'autocomplete="username"' in html and 'autocomplete="current-password"' in html)
        check("login: fields labelled", '<label for="username">' in html and '<label for="password">' in html)
        for asset in ("/static/login.css", "/static/login.js"):
            check(f"GET {asset} → 200", client.get(asset).status_code == 200)
        login_css = client.get("/static/login.css").text
        login_js = client.get("/static/login.js").text

        # Regression guard: the GET handler used to drop ?error=, so a failed
        # sign-in redirected to a page that never showed why.
        r = client.get("/login?error=Invalid+username+or+password")
        check("login: ?error= surfaces a role=alert message",
              'role="alert"' in r.text and "Invalid username or password" in r.text)
        r = client.get("/login")
        check("login: no error block without ?error=", "Sign-in failed" not in r.text)

        # --- 2. quick-fill demo chips -----------------------------------------
        check("login: exactly five chips", html.count('class="auth-chip"') == 5,
              html.count('class="auth-chip"'))
        for username, password, role, _display, _pi in DEMO_USERS:
            check(f"login: chip for {username} carries the seeded credentials",
                  f'data-username="{username}"' in html and f'data-password="{password}"' in html)
            check(f"login: chip credentials printed for no-JS entry ({username})",
                  f'<span class="code">{username}</span>' in html
                  and f'<span class="code">{password}</span>' in html)
        check("login: chips never submit the form",
              html.count('type="button" class="auth-chip"') == 5)
        check("login: every chip has an aria-label", html.count('class="auth-chip" aria-label') == 0
              and html.count("auth-chip") >= 5 and html.count('aria-label="Fill the form with the') == 5)
        check("login: noscript fallback note present", "<noscript>" in html)
        check("login: chips are enhancement, not authority (boundary stated)",
              "The account, never this page, determines what you can see and do." in html)
        check("login.js: chips fill only (no fetch, no submit)",
              "fetch(" not in login_js and ".submit(" not in login_js)
        check("login.js: filled state synced from the form's contents", "syncChips" in login_js)
        check("login.js: pending state on submit", "Signing in…" in login_js)

        # A chip fills the VOLUNTEER account — which must still be refused the
        # leadership-only audit trail after signing in. The page grants nothing.
        sign_in(client, "volunteer.demo", "CtmsVolunteer#01")
        check("login: volunteer from a chip is still refused /audit (403)",
              client.get("/audit").status_code == 403)
        sign_in(client, "leadership.demo", "AiiaLeadership#01")
        check("login: leadership from a chip reads /audit (200)",
              client.get("/audit").status_code == 200)
        token = csrf(client.get("/login").text)
        client.post("/logout", data={"csrf_token": token}, follow_redirects=False)

        # --- 3. landing motion layer ------------------------------------------
        html = client.get("/").text
        check("landing: hero splits into three animated lines",
              html.count('class="l-hero-line"') == 3)
        check("landing: [data-reveal] covers the major sections",
              html.count("data-reveal") >= 25, html.count("data-reveal"))
        check("landing: fixture clock ticks from a static printed value",
              'data-tick="26:14">26:14<' in html)
        check("landing: chain hashes carry their settled text statically",
              'data-hash="9f3e…c21a">9f3e…c21a<' in html and 'data-hash="7bd1…e88f">7bd1…e88f<' in html)
        check("landing: scroll hairline element present (aria-hidden)",
              '<div class="l-progress" aria-hidden="true"></div>' in html)
        landing_css = client.get("/static/landing.css").text
        landing_js = client.get("/static/landing.js").text

        # The hiding rule must be gated BOTH ways: behind html.ljs (so a no-JS
        # browser never hides) and inside a no-preference media block (so
        # reduced motion never hides). A rule that hid on either condition
        # alone would strand content for one of those audiences.
        hide = re.search(r"html\.ljs \[data-reveal\]\s*\{[^}]*opacity:\s*0", landing_css)
        check("landing.css: pre-reveal hidden state is JS-gated (html.ljs)", bool(hide))
        # Extract every `@media (prefers-reduced-motion: no-preference) {…}`
        # block with a brace matcher (regex cannot balance the nested
        # @keyframes braces), then: (a) the guarded content covers the hero,
        # the reveal layer and the preview pulse; (b) OUTSIDE the guarded
        # blocks there is no `animation:` usage at all — @keyframes
        # *definitions* are inert and may live anywhere, only their use moves.
        def media_blocks(css: str, query: str) -> tuple[list[str], str]:
            blocks, spans = [], []
            for m in re.finditer(re.escape(query) + r"\s*\{", css):
                depth, i = 1, m.end()
                while i < len(css) and depth:
                    if css[i] == "{":
                        depth += 1
                    elif css[i] == "}":
                        depth -= 1
                    i += 1
                blocks.append(css[m.end():i - 1])
                spans.append((m.start(), i))
            rest = "".join(css[s:e] for s, e in zip([0] + [e for _s, e in spans],
                                                    [s for s, _e in spans] + [len(css)]))
            return blocks, rest

        no_pref, outside = media_blocks(landing_css, "@media (prefers-reduced-motion: no-preference)")
        guarded = "\n".join(no_pref)
        check("landing.css: guarded motion covers hero, reveal layer and preview pulse",
              bool(no_pref)
              and "l-hero-line" in guarded and "l-line-up" in guarded
              and "[data-reveal]" in guarded and "l-breach-pulse" in guarded)
        outside_uses = re.findall(r"[^-]animation:\s*l-[a-z-]+", outside)
        check("landing.css: no animation usage outside the no-preference guard",
              not outside_uses, outside_uses[:2])
        tokens = client.get("/static/tokens.css").text
        check("tokens.css: reduced motion zeroes the motion token system",
              "prefers-reduced-motion: reduce" in tokens
              and "--motion-instant: 0s" in tokens)

        check("landing.js: reduced-motion check before any autonomous motion",
              "prefers-reduced-motion: reduce" in landing_js)
        check("landing.js: reveal layer is JS-gated (adds html.ljs)",
              'classList.add("ljs")' in landing_js)
        check("landing.js: no-IO fallback reveals everything",
              re.search(r"else \{\s*revealed\.forEach", landing_js) is not None)
        check("landing.js: hash flicker settles back to the printed text",
              "el.textContent = finalText" in landing_js)
        check("landing.js: scroll handler is passive + rAF-throttled",
              "{ passive: true }" in landing_js and "requestAnimationFrame" in landing_js)

        # --- 4. no-JS completeness ---------------------------------------------
        check("landing: drawer is a real <details> menu", '<details class="l-drawer"' in html)
        check("landing: persona selector is radio inputs (no JS needed)",
              html.count('class="l-role-input" type="radio"') == 5)
        check("landing: no inline event handlers", " onclick=" not in html and " onchange=" not in html)
        check("landing: no <noscript> dependency (nothing requires JS)", "<noscript>" not in html)
        login_html = client.get("/login").text
        check("login: no inline event handlers", " onclick=" not in login_html and " onchange=" not in login_html)

        # --- 5. state contracts (§10.1) + display rules (§13.2) -----------------
        components = (ROOT / "app" / "templates" / "_components.html").read_text(encoding="utf-8")
        for macro in ("state_empty", "state_loading", "state_error",
                      "state_stale", "state_permission", "state_success"):
            check(f"§10.1: {macro} macro exists", f"macro {macro}(" in components)
        check("§13.2: unknown state is dotted, stale is dashed",
              "--unknown" in tokens and "--stale" in tokens)
        app_css = client.get("/static/app.css").text
        check("§13.2: dotted/dashed conventions implemented in app.css",
              "dotted" in app_css and "dashed" in app_css)
        check("§10.1: queue summary announces itself (role=status)",
              'class="queue-toolbar-summary" role="status"' in components
              or "queue-toolbar-summary" in components and 'role="status"' in components)

        # --- 6. accessibility (§13.3) ------------------------------------------
        check("a11y: landing skip link", 'href="#main"' in html and "Skip to content" in html)
        check("a11y: login skip link", 'href="#signin-form"' in login_html)
        check("a11y: visible keyboard focus rule", ":focus-visible" in app_css)
        check("a11y: icon-only drawer trigger labelled", '<summary aria-label="Open menu">' in html)
        check("a11y: login error uses role=alert", 'class="auth-error" role="alert"'
              in client.get("/login?error=x").text)
        check("a11y: landing landmarks labelled",
              'aria-label="Primary"' in html and 'aria-labelledby="hero-title"' in html)
        check("a11y: pages declare lang", '<html lang="en"' in html and '<html lang="en"' in login_html)

        # --- 7. trust-copy consolidation (§13.1) --------------------------------
        mandated = ("Synthetic demonstration data — not for patient care or clinical decision-making.",
                    "AE terms coded against a curated vocabulary, not MedDRA or WHODrug.")
        check("§13.1: macro holds the mandated lines",
              all(line in components for line in mandated))
        check("§13.1: landing footer renders the shared notice",
              all(line in html for line in mandated))
        check("§13.1: login footer renders the shared notice",
              all(line in login_html for line in mandated))

        # --- 8. session/expiry behavior ------------------------------------------
        client.cookies.clear()
        client.cookies.set("vitalwatch_session", "bogus-token-that-names-nothing")
        r = client.get("/portal/leadership", follow_redirects=False)
        check("expired/bogus session → 303 /login, never a 500",
              r.status_code == 303 and r.headers["location"].startswith("/login"),
              r.status_code)
        r = client.get("/", follow_redirects=False)
        check("bogus session on the public page still renders 200 (no leak)",
              r.status_code == 200, r.status_code)
        client.cookies.clear()
        r = client.post("/ae", data={"trial_id": "x", "participant_code": "y",
                                     "onset_date": "2026-08-22", "narrative": "z",
                                     "csrf_token": "bogus"}, follow_redirects=False)
        check("write without a session fails (never a silent success)",
              r.status_code in (303, 400, 401, 403) and r.status_code != 200, r.status_code)

        # --- 9. regression guards for Phase 6 debug ------------------------------
        sign_in(client, "investigator.demo", "AiiaTrialLead#01")
        check("regression: investigator reads /ae (shipped design; FILE_ADVERSE_EVENT held)",
              client.get("/ae").status_code == 200)
        sign_in(client, "volunteer.demo", "CtmsVolunteer#01")
        check("regression: volunteer still refused /ae (403)",
              client.get("/ae").status_code == 403)
        token = csrf(client.get("/login").text)
        client.post("/logout", data={"csrf_token": token}, follow_redirects=False)

        env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
        for username, _pw, _role, _d, _pi in DEMO_USERS:
            check(f".env.example names the current account {username}", username in env_example)
        for retired in ("pi.demo", "coordinator.demo", "monitor.demo", "ethics.demo",
                        "pv.demo", "admin.demo", "regulator.demo"):
            check(f".env.example: retired account {retired} is gone", retired not in env_example)

    # --- report ---------------------------------------------------------------
    passed = sum(1 for _n, ok, _d in RESULTS if ok)
    width = max(len(n) for n, _ok, _d in RESULTS)
    for name, ok, detail in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {'' if ok else '-> ' + detail}")
    print(f"\n{passed}/{len(RESULTS)} checks passed")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
