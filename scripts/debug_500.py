"""Get actual 500 error details from the live server."""
import urllib.request
import urllib.parse
import http.cookiejar
import re

BASE = "http://localhost:8000"
cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

# Get login page
r = opener.open(BASE + "/login")
html = r.read().decode()
m = re.search(r'name="csrf_token" value="([^"]+)"', html)
csrf = m.group(1)
print("CSRF found:", csrf[:10], "...")

# Login as volunteer
payload = urllib.parse.urlencode({
    "username": "volunteer.demo",
    "password": "CtmsVolunteer#01",
    "next": "/portal/volunteer",
    "csrf_token": csrf,
}).encode()

try:
    r2 = opener.open(BASE + "/login", payload)
    content = r2.read().decode()
    print("URL:", r2.url)
    print("Status OK. Content length:", len(content))
    if "Internal Server Error" in content or "traceback" in content.lower():
        # Find error
        idx = content.lower().find("traceback")
        if idx < 0:
            idx = content.lower().find("internal server error")
        print(content[max(0, idx-200):idx+3000])
    else:
        print("No traceback. First 800 chars:")
        print(content[:800])
except urllib.error.HTTPError as e:
    print("HTTP Error:", e.code)
    body = e.read().decode()
    print(body[:3000])
except Exception as e:
    print("Exception:", e)
