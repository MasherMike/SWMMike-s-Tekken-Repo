"""
Adds Wavu Wank skill ratings to Mike's stored ranked games.

Runs 3 times a day (midnight, 8 AM, 4 PM Eastern) from
.github/workflows/collect-wank.yml, plus once per End session (the GitHub
workflow and the Tekken app's Session Gallery), so reviews include ratings.
One request per run to Mike's own public player page, which Wavu Wank's
robots.txt allows. The page lists his recent
games, so any run that gets skipped is caught up by the next one.

Only my_rating and opp_rating are added (plus any ranked game ewgf missed).
Names and IDs on the page are never stored: see wank.py and save_rows().
"""

import gzip
import sys
import urllib.error
import urllib.request

sys.path.insert(0, "scripts")
from collect_battles import TEKKEN_ID, load_rows, save_rows  # noqa: E402
from wank import parse_games, merge                          # noqa: E402

URL = f"https://wank.wavu.wiki/player/{TEKKEN_ID}"
SINCE = "2026-01-01T05:00:00Z"           # Jan 1, 2026 Eastern: the database's start date
HEADERS = {
    "Accept-Encoding": "gzip",           # the site asks for compressed requests
    "User-Agent": "SWMMike-Tekken-Repo/1.0 (personal stats, 3 requests/day; "
                  "github.com/MasherMike/SWMMike-s-Tekken-Repo)",
}


def fetch_page(timeout=60):
    """One request for Mike's player page. Raises urllib errors; callers decide what to do."""
    req = urllib.request.Request(URL, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return raw.decode("utf-8", errors="replace")


def add_ratings(rows, html):
    """Merge the page's games into rows (in place). Returns (games_on_page, rated, added)."""
    games = parse_games(html)
    if not games:
        raise ValueError("No games found on the page; the page layout may have changed.")
    rated, added = merge(rows, games, since=SINCE)
    return len(games), rated, added


def fetch():
    try:
        return fetch_page()
    except urllib.error.HTTPError as e:
        sys.exit(f"Wavu Wank returned HTTP {e.code}; trying again next run.")
    except urllib.error.URLError as e:
        sys.exit(f"Couldn't reach Wavu Wank ({e.reason}); trying again next run.")


def main():
    games = parse_games(fetch())
    if not games:
        sys.exit("No games found on the page; the page layout may have changed.")
    rows = load_rows()
    rated, added = merge(rows, games, since=SINCE)
    save_rows(rows)
    print(f"Page listed {len(games)} games ({games[-1]['battle_at']} to {games[0]['battle_at']}). "
          f"{rated} games given ratings, {added} ranked games added.")


if __name__ == "__main__":
    main()
