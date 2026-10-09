"""
Collect Mike's Tekken 8 battles from the ewgf.gg API into data/battles.jsonl.

Runs every 6 hours from .github/workflows/collect-battles.yml.
The free API tier returns the last 50 battles (24h delayed); polling every
6 hours keeps every window well under 50 games, so nothing is missed.

PRIVACY: only these 7 fields are ever written - no names, IDs, regions or
Tekken Power, for Mike or for opponents:
  battle_at, mode, my_char, opp_char, opp_rank, result (+ round score), stage
"""

import gzip
import json
import os
import sys
import urllib.error
import urllib.request

TEKKEN_ID = "4bN6AEeddYT6"          # Mike's Tekken ID (public, from his ewgf URL)
URL = f"https://api.ewgf.gg/external/battles/{TEKKEN_ID}"
BATTLES = "data/battles.jsonl"
STAGES = "data/stages.json"

MODES = {"RANKED_BATTLE": "ranked", "QUICK_BATTLE": "quick",
         "PLAYER_BATTLE": "player", "GROUP_BATTLE": "group"}


def fetch():
    key = os.environ.get("EWGF_API_KEY")
    if not key:
        sys.exit("EWGF_API_KEY secret is missing.")
    req = urllib.request.Request(URL, headers={
        "Authorization": f"Bearer {key}", "Accept-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        body = e.read()
        try:
            body = gzip.decompress(body)
        except OSError:
            pass
        sys.exit(f"API error {e.code}: {body.decode(errors='replace')[:500]}")


def slim(b, stage_names):
    """Reduce one raw battle to the 7 approved fields, from Mike's point of view."""
    me_first = b.get("p1_tekken_id") == TEKKEN_ID
    if not me_first and b.get("p2_tekken_id") != TEKKEN_ID:
        return None                                  # not Mike's battle; skip
    me, opp = ("p1", "p2") if me_first else ("p2", "p1")
    my_rounds, opp_rounds = b.get(f"{me}_rounds_won"), b.get(f"{opp}_rounds_won")
    won = b.get("winner") == (1 if me_first else 2)
    stage_id = b.get("stage_id")
    return {
        "battle_at": b.get("battle_at"),
        "mode": MODES.get(b.get("battle_type"), str(b.get("battle_type", "")).lower()),
        "my_char": b.get(f"{me}_char"),
        "opp_char": b.get(f"{opp}_char"),
        "opp_rank": b.get(f"{opp}_dan_rank"),
        "result": "W" if won else "L",
        "rounds": f"{my_rounds}-{opp_rounds}",
        "stage_id": stage_id,
        "stage": stage_names.get(str(stage_id)),     # None until the ID is confirmed
    }


def key(r):
    """Same battle seen in two pulls -> same key, so it's stored once."""
    return (r["battle_at"], r["my_char"], r["opp_char"], r["rounds"], r["stage_id"])


def main():
    with open(STAGES) as fh:
        stage_names = json.load(fh)["confirmed"]

    existing = []
    if os.path.exists(BATTLES):
        with open(BATTLES) as fh:
            existing = [json.loads(line) for line in fh if line.strip()]
    seen = {key(r) for r in existing}

    payload = fetch()
    raw = payload.get("data", [])
    new = []
    for b in raw:
        r = slim(b, stage_names)
        if r and key(r) not in seen:
            seen.add(key(r))
            new.append(r)

    # Back-fill stage names for older rows if an ID was confirmed since.
    for r in existing:
        if r.get("stage") is None:
            r["stage"] = stage_names.get(str(r.get("stage_id")))

    rows = sorted(existing + new, key=lambda r: str(r["battle_at"]))
    os.makedirs("data", exist_ok=True)
    with open(BATTLES, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    unknown = sorted({r["stage_id"] for r in rows if r["stage"] is None})
    print(f"Pulled {len(raw)} battles, {len(new)} new, {len(rows)} total. "
          f"Requests left this hour: {payload.get('_metadata', {}).get('rate_limit_remaining')}.")
    if unknown:
        print(f"Unmapped stage IDs: {unknown}")


if __name__ == "__main__":
    main()
