"""
Measure how long ewgf.gg takes to show a battle after it's played.

Start it right before a ranked session. It polls the API once a minute for
the chosen number of minutes and notes when each NEW battle first appears.
Delay = time first seen - battle time.

Only timestamps are kept - no characters, names or IDs.
Writes data/lag-test-<date>.json.

Requires ewgf Pro: on the free tier every battle is held back 24 hours,
so the test stops immediately and says so.

Run by .github/workflows/lag-test.yml.
"""

import gzip
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

TEKKEN_ID = "4bN6AEeddYT6"
URL = f"https://api.ewgf.gg/external/battles/{TEKKEN_ID}"
POLL_SECONDS = 60


def fetch():
    req = urllib.request.Request(URL, headers={
        "Authorization": f"Bearer {os.environ['EWGF_API_KEY']}",
        "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return json.loads(raw)


def parse(ts):
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


def main():
    minutes = int(os.environ.get("TEST_MINUTES", "120"))
    start = datetime.now(timezone.utc)

    first = fetch()
    tier = first.get("_metadata", {}).get("tier")
    if tier != "pro":
        sys.exit(f"API tier is '{tier}', not 'pro'. The free tier delays every "
                 "battle by 24 hours, so there is nothing to measure. "
                 "Activate EWGF Pro, then run this again.")

    already = {b.get("battle_at") for b in first.get("data", [])}
    seen = {}                                     # battle_at -> first seen time
    deadline = time.time() + minutes * 60
    polls = 1
    print(f"Pro confirmed. Watching for new battles for {minutes} minutes...")

    while time.time() < deadline:
        time.sleep(POLL_SECONDS)
        try:
            payload = fetch()
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"poll failed, retrying next minute: {e}")
            continue
        polls += 1
        now = datetime.now(timezone.utc)
        for b in payload.get("data", []):
            at = b.get("battle_at")
            if at in already or at in seen:
                continue
            if parse(at) < start:                 # an old game, not this session
                already.add(at)
                continue
            seen[at] = now
            lag = (now - parse(at)).total_seconds() / 60
            print(f"new battle at {at}, appeared after {lag:.1f} min")

    lags = sorted((seen[at] - parse(at)).total_seconds() / 60 for at in seen)
    result = {
        "tested_at": start.isoformat(timespec="seconds"),
        "minutes_watched": minutes,
        "polls": polls,
        "poll_interval_seconds": POLL_SECONDS,
        "battles_seen": len(lags),
        "lag_minutes": {
            "median": round(statistics.median(lags), 1),
            "best": round(lags[0], 1),
            "worst": round(lags[-1], 1),
            "all": [round(x, 1) for x in lags],
        } if lags else None,
        "note": "Lag includes up to 1 minute of polling granularity. If ewgf's "
                "battle time is when the match STARTED, lag also includes the "
                "match length (about 3-4 minutes).",
    }
    os.makedirs("data", exist_ok=True)
    path = f"data/lag-test-{start:%Y-%m-%d}.json"
    with open(path, "w") as fh:
        json.dump(result, fh, indent=2)
    if lags:
        print(f"\n{len(lags)} battles. Median delay {result['lag_minutes']['median']} min, "
              f"worst {result['lag_minutes']['worst']} min. Saved {path}")
    else:
        print(f"\nNo new battles appeared in {minutes} minutes. Saved {path}")


if __name__ == "__main__":
    main()
