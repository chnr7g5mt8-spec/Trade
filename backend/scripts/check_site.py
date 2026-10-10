"""Check the deployed site from outside: health, upstream diagnostics, a rating.

Usage: python check_site.py https://your-app.onrender.com
"""
import json
import sys
import time
import urllib.error
import urllib.request

site = sys.argv[1].rstrip("/")


def get(path):
    req = urllib.request.Request(site + path, headers={"accept": "application/json", "user-agent": "site-check"})
    for attempt in range(6):  # the free tier may be asleep; waking takes up to a minute
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, e.read()[:500].decode(errors="replace")
        except Exception as e:
            print(f"{path}: attempt {attempt + 1} failed: {e!r}", flush=True)
            time.sleep(20)
    return None, "unreachable"


for path in ["/health", "/api/diagnostics", "/api/rating/AAPL"]:
    status, body = get(path)
    print(f"\n===== {path} -> {status}")
    if isinstance(body, dict) and path == "/api/rating/AAPL":
        body = {k: body.get(k) for k in ["ticker", "name", "price", "price_time", "market_state", "score", "label",
                                         "coverage", "source"]}
    print(json.dumps(body, indent=1, default=str)[:6000], flush=True)
