import getpass
import json
import urllib.request
import urllib.error
import http.cookiejar

base = "https://inkloom-ai-app.onrender.com"
email = input("Account email: ").strip()
password = getpass.getpass("Account password: ")

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(jar)
)

body = json.dumps({
    "email": email,
    "password": password
}).encode("utf-8")

req = urllib.request.Request(
    base + "/api/auth/login",
    data=body,
    headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
    },
    method="POST",
)

try:
    with opener.open(req, timeout=30) as response:
        print("Login HTTP status:", response.status)
        print("Session cookie received:", bool(list(jar)))
except urllib.error.HTTPError as exc:
    print("Login HTTP status:", exc.code)
    print("Response:", exc.read().decode("utf-8", errors="replace"))
except Exception as exc:
    print("Request failed:", type(exc).__name__)
