"""
One-time backlog import from saved Wavu Wank player pages.

Mike saves his Wavu Wank player page(s) as HTML (one per character, using
"Show more" so the list reaches far enough back) and this script merges those
ranked games into data/battles.jsonl, then rewrites data/battles.js and
data/battles.csv exactly like the collector does.

  python scripts/import_wank.py --since 2026-01-01 page1.html page2.html ...

PRIVACY: the saved pages contain player names and IDs. Only the approved
fields are kept, and the HTML files are never copied into the repo.
Wavu Wank has no stage or rank-tier data, so those fields are left empty
(stage_id/stage/opp_rank = null). Everything Wank lists is ranked.

Duplicates are skipped by (battle_at, my_char, opp_char, rounds); rows already
collected from ewgf.gg are kept as-is because they carry stage and rank.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, "scripts")
from collect_battles import BATTLES, write_page_copy, write_csv_copy, TEKKEN_ID  # noqa: E402

TZ = ZoneInfo("America/New_York")
ROW = re.compile(r'<tr>\s*<td class="battle-at">(.*?)</tr>', re.S)


def parse(path):
    text = open(path, encoding="utf-8", errors="replace").read()
    out = []
    for r in ROW.findall(text):
        ts = re.search(r"printDateTime\((\d+)\)", r)
        res = re.search(r'<td class="result">\s*(\d)-(\d)\s*</td>', r)
        left = re.search(r'<td class="left">(.*?)</td>', r, re.S)
        right = re.search(r'<td class="right">(.*?)</td>', r, re.S)
        if not (ts and res and left and right):
            continue
        sides = []
        for side in (left.group(1), right.group(1)):
            pid = re.search(r'/player/(\w+)"', side)
            char = re.search(r'class="char">([^<]+)<', side)
            sides.append((pid and pid.group(1), char and char.group(1).strip()))
        a, b = int(res.group(1)), int(res.group(2))
        if sides[0][0] == TEKKEN_ID:
            mine, theirs, my_char, opp_char = a, b, sides[0][1], sides[1][1]
        elif sides[1][0] == TEKKEN_ID:
            mine, theirs, my_char, opp_char = b, a, sides[1][1], sides[0][1]
        else:
            continue
        out.append({
            "battle_at": datetime.fromtimestamp(int(ts.group(1)), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "mode": "ranked",
            "my_char": my_char,
            "opp_char": opp_char,
            "opp_rank": None,
            "result": "W" if mine > theirs else "L",
            "rounds": f"{mine}-{theirs}",
            "stage_id": None,
            "stage": None,
        })
    return out


def key(r):
    return (r["battle_at"], r["my_char"], r["opp_char"], r["rounds"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-01-01", help="local date (America/New_York), inclusive")
    ap.add_argument("pages", nargs="+")
    args = ap.parse_args()
    since = datetime.fromisoformat(args.since).replace(tzinfo=TZ)

    with open(BATTLES) as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    seen = {key(r) for r in rows}

    added = 0
    for page in args.pages:
        found = parse(page)
        n = 0
        for r in found:
            when = datetime.fromisoformat(r["battle_at"].replace("Z", "+00:00"))
            if when < since or key(r) in seen:
                continue
            seen.add(key(r))
            rows.append(r)
            n += 1
        print(f"{page}: {len(found)} games on the page, {n} new since {args.since}")
        added += n

    rows.sort(key=lambda r: str(r["battle_at"]))
    with open(BATTLES, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    write_page_copy(rows)
    write_csv_copy(rows)
    print(f"Added {added}. {len(rows)} battles stored in total.")


if __name__ == "__main__":
    main()
