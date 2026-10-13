"""
One-time backlog import from saved Wavu Wank player pages.

Mike saves his Wavu Wank player page(s) as HTML (one per character, using
"Show more" so the list reaches far enough back). This script:
  - adds ranked games on or after --since that aren't stored yet
  - adds my_rating / opp_rating to every stored game it can match
then saves through save_rows(), which keeps only approved fields.

  python scripts/import_wank.py --since 2026-01-01 page1.html page2.html ...

The HTML files contain player names and IDs; they are never copied into the
repo. Wavu Wank has no stage or rank tier, so new rows leave those null.
"""

import argparse
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, "scripts")
from collect_battles import load_rows, save_rows  # noqa: E402
from wank import parse_games, merge               # noqa: E402

TZ = ZoneInfo("America/New_York")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-01-01", help="local date (America/New_York), inclusive")
    ap.add_argument("pages", nargs="+")
    args = ap.parse_args()
    since = datetime.fromisoformat(args.since).replace(tzinfo=TZ).astimezone(ZoneInfo("UTC"))
    since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")

    rows = load_rows()
    for page in args.pages:
        games = parse_games(open(page, encoding="utf-8", errors="replace").read())
        rated, added = merge(rows, games, since=since_iso)
        print(f"{page}: {len(games)} games on the page, {added} added, {rated} given ratings")
    rows = save_rows(rows)
    have = sum(r.get("opp_rating") is not None for r in rows if r["mode"] == "ranked")
    print(f"{len(rows)} battles stored; {have} ranked games have ratings.")


if __name__ == "__main__":
    main()
