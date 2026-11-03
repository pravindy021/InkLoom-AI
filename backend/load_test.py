import concurrent.futures
import http.cookiejar
import getpass
import math
import statistics
import threading
import time
import urllib.error
import urllib.request

BASE_URL = "https://inkloom-ai-app.onrender.com"
REVIEW_ID = 4
WORKERS = 3
DURATION = 60
REQUEST_INTERVAL = 2
TIMEOUT = 10

stop_event = threading.Event()
results = []
lock = threading.Lock()


def make_opener():
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar)
    ), jar


def request(opener, path, method="GET", data=None):
    req = urllib.request.Request(
        BASE_URL + path,
        data=data,
        method=method,
        headers={
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if data is not None else {}),
        },
    )
    return opener.open(req, timeout=TIMEOUT)


def login():
    email = input("Account email: ").strip()
    password = getpass.getpass("Account password: ")

    opener, jar = make_opener()

    import json
    body = json.dumps({
        "email": email,
        "password": password
    }).encode("utf-8")

    with request(opener, "/api/auth/login", "POST", body) as response:
        if response.status != 200:
            raise RuntimeError("Login failed: HTTP {}".format(response.status))
        response.read()

    # Verify the authenticated session before starting workers.
    with request(opener, "/api/auth/me") as response:
        if response.status != 200:
            raise RuntimeError("Session verification failed.")

    cookies = [
        "{}={}".format(c.name, c.value)
        for c in jar
        if c.name
    ]

    if not cookies:
        raise RuntimeError("No session cookie received.")

    return "; ".join(cookies)


def worker(cookie_header, deadline, worker_id):
    while not stop_event.is_set() and time.monotonic() < deadline:
        started = time.monotonic()
        status = None
        error = None

        try:
            req = urllib.request.Request(
                BASE_URL + "/api/reviews/{}".format(REVIEW_ID),
                headers={
                    "Accept": "application/json",
                    "Cookie": cookie_header,
                },
                method="GET",
            )

            with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
                status = response.status
                response.read()

            if status != 200:
                error = "Unexpected HTTP {}".format(status)

        except urllib.error.HTTPError as exc:
            status = exc.code
            error = "HTTP {}".format(status)

        except Exception as exc:
            error = type(exc).__name__ + ": " + str(exc)

        elapsed = time.monotonic() - started

        with lock:
            results.append({
                "status": status,
                "elapsed": elapsed,
                "error": error,
            })

        # Stop immediately on authentication, rate-limit or server errors.
        if status in (401, 403, 429) or (
            status is not None and status >= 500
        ):
            stop_event.set()

        if error and status is None:
            stop_event.set()

        remaining = REQUEST_INTERVAL - elapsed
        if remaining > 0:
            stop_event.wait(remaining)


def percentile(values, p):
    ordered = sorted(values)
    index = max(0, math.ceil(p * len(ordered)) - 1)
    return ordered[index]


def main():
    print("\nInkLoom AI - Conservative Read-only Load Test")
    print("Target: review endpoint {}".format(REVIEW_ID))
    print("Workers: {}".format(WORKERS))
    print("Duration: {} seconds".format(DURATION))
    print("Approximate maximum request rate: 1.5 req/sec")
    print("No review/comment/user data will be modified.\n")

    cookie_header = login()
    print("Authentication successful. Starting test...\n")

    deadline = time.monotonic() + DURATION

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=WORKERS
    ) as executor:
        futures = [
            executor.submit(worker, cookie_header, deadline, i)
            for i in range(WORKERS)
        ]
        concurrent.futures.wait(futures)

    total = len(results)
    successful = sum(1 for r in results if r["status"] == 200)
    latencies = [r["elapsed"] for r in results]

    print("\n========== TEST RESULTS ==========")
    print("Total requests :", total)
    print("Successful     :", successful)
    print("Failed         :", total - successful)
    print("Success rate   : {:.2f}%".format(
        successful * 100 / total if total else 0
    ))

    if latencies:
        print("Average latency: {:.3f}s".format(
            statistics.mean(latencies)
        ))
        print("P95 latency    : {:.3f}s".format(
            percentile(latencies, 0.95)
        ))
        print("Maximum latency: {:.3f}s".format(max(latencies)))

    errors = {}
    for result in results:
        if result["error"]:
            key = result["error"]
            errors[key] = errors.get(key, 0) + 1

    if errors:
        print("\nErrors:")
        for error, count in errors.items():
            print("  {} ({} times)".format(error, count))

    print("==================================")
    print("No automatic retries were performed.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        stop_event.set()
        print("\nTest interrupted.")
    except Exception as exc:
        print("\nTest could not start:", type(exc).__name__, str(exc))
