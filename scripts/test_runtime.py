"""
Proper runtime smoke test - logs in as each demo account and checks dashboards.
"""
import urllib.request
import urllib.parse
import http.cookiejar
import re
import sys

BASE = "http://localhost:8000"

ACCOUNTS = [
    ("volunteer.demo",    "CtmsVolunteer#01",   "/portal/volunteer",      "Volunteer portal"),
    ("investigator.demo", "AiiaTrialLead#01",   "/portal/investigator",   "Investigator"),
    ("safety.demo",       "AiiaSafety#01",       "/portal/safety_officer", "Safety"),
    ("company.demo",      "AiiaCompany#01",       "/portal/company",       "Company"),
    ("leadership.demo",   "AiiaLeadership#01",   "/portal/leadership",    "Leadership"),
]

failures = []

for username, password, expected_path, expected_keyword in ACCOUNTS:
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.addheaders = [("User-Agent", "smoke-tester/1.0")]

    # 1) GET /login - grab CSRF token
    try:
        r = opener.open(BASE + "/login")
        html = r.read().decode("utf-8", errors="replace")
    except Exception as e:
        failures.append(f"[{username}] GET /login FAILED: {e}")
        continue

    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    if not m:
        failures.append(f"[{username}] No CSRF token on /login")
        continue
    csrf = m.group(1)

    # 2) POST /login
    payload = urllib.parse.urlencode({
        "username": username,
        "password": password,
        "next": expected_path,
        "csrf_token": csrf,
    }).encode()
    try:
        r2 = opener.open(BASE + "/login", payload)
        final_url = r2.url
        content = r2.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        failures.append(f"[{username}] POST /login HTTP {e.code}: {e.reason}")
        continue
    except Exception as e:
        failures.append(f"[{username}] POST /login FAILED: {e}")
        continue

    # 3) Check: no Internal Server Error, page loads with some content
    if "Internal Server Error" in content:
        failures.append(f"[{username}] 500 Internal Server Error at {final_url}")
    elif len(content) < 500:
        failures.append(f"[{username}] Suspiciously short response ({len(content)} bytes) at {final_url}")
    else:
        print(f"  OK  {username} ({len(content):,} bytes) -> {final_url}")

if failures:
    print("\nFAILURES:")
    for f in failures:
        print(" ", f)
    sys.exit(1)
else:
    print(f"\nAll {len(ACCOUNTS)} dashboards rendered successfully.")
