import argparse
import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

_ = load_dotenv()

URL = "https://ws.audioscrobbler.com/2.0/"
USER = "kncecil"
API_KEY = os.environ["LASTFM_API_KEY"]
FIXTURES = Path("scripts/fixtures")
FIXTURES.mkdir(parents=True, exist_ok=True)

BASE = {
    "method": "user.getRecentTracks",
    "user": USER,
    "api_key": API_KEY,
    "format": "json",
    "limit": 5,
}

CASES = {
    "ok": {},
    "limit_1": {"limit": 1},
    "limit_0": {"limit": 0},
    "limit_1001": {"limit": 1001},
    "unknown_user": {"user": "nobody_xyz_123456"},
    "missing_user": {"user": None},
    "bad_key": {"api_key": "invalid"},
    "missing_key": {"api_key": None},
    "bad_method": {"method": "user.nope"},
    "page_past_end": {"page": 99999},
    "empty_window": {"from": 1798761600, "to": 1830297600},
    "from_after_to": {"from": 1830297600, "to": 1798761600},
}


def run(name: str, overrides: dict, tag: str = "") -> None:
    params = {k: v for k, v in {**BASE, **overrides}.items() if v is not None}
    try:
        resp = requests.get(URL, params=params, timeout=10)
    except requests.RequestException as exc:
        record = {"case": name, "transport_error": type(exc).__name__}
        status = error = message = "-"
    else:
        try:
            body = resp.json()
        except ValueError:
            body = resp.text[:2000]
        record = {
            "case": name,
            "status": resp.status_code,
            "content_type": resp.headers.get("content-type"),
            "elapsed_s": round(resp.elapsed.total_seconds(), 2),
            "params": {k: v for k, v in params.items() if k != "api_key"},
            "body": body,
        }
        status = resp.status_code
        error = body.get("error", "") if isinstance(body, dict) else ""
        message = body.get("message", "") if isinstance(body, dict) else ""
    stem = f"{name}_{tag}" if tag else name
    (FIXTURES / f"{stem}.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False)
    )
    print(f"{stem:24} {status!s:>4}  error={error!s:<3} {message}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cases", nargs="*", help="case names; default is all")
    ap.add_argument("--tag", default="", help="filename suffix, e.g. idle or playing")
    args = ap.parse_args()

    unknown = [c for c in args.cases if c not in CASES]
    if unknown:
        raise SystemExit(f"unknown case(s) {unknown}; choose from {list(CASES)}")

    for case in args.cases or CASES:
        run(case, CASES[case], args.tag)
        time.sleep(0.5)
