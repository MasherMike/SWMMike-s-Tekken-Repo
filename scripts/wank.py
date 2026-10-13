"""
Shared reader for Wavu Wank player pages (wank.wavu.wiki/player/<id>).

parse_games(html) returns one dict per game in the page's match table,
from Mike's side:
  battle_at, mode ("ranked"), my_char, opp_char, result, rounds,
  my_rating, opp_rating      (each player's rating BEFORE the game)

Player names and IDs are read only to tell which side of a row is Mike, and are
never returned. save_rows() in collect_battles.py is the second safety net.
"""

import re
from datetime import datetime, timezone

from collect_battles import TEKKEN_ID

ROW = re.compile(r'<tr>\s*<td class="battle-at">(.*?)</tr>', re.S)


def _side(html):
    pid = re.search(r'/player/(\w+)"', html)
    char = re.search(r'class="char">([^<]+)<', html)
    rating = re.search(r'class="rating">\s*(-?\d+)', html)
    return (pid.group(1) if pid else None,
            char.group(1).strip() if char else None,
            int(rating.group(1)) if rating else None)


def parse_games(html):
    games = []
    for r in ROW.findall(html):
        ts = re.search(r"printDateTime\((\d+)\)", r)
        res = re.search(r'<td class="result">\s*(\d)-(\d)\s*</td>', r)
        left = re.search(r'<td class="left">(.*?)</td>', r, re.S)
        right = re.search(r'<td class="right">(.*?)</td>', r, re.S)
        if not (ts and res and left and right):
            continue
        (lid, lchar, lrate), (rid, rchar, rrate) = _side(left.group(1)), _side(right.group(1))
        a, b = int(res.group(1)), int(res.group(2))
        if lid == TEKKEN_ID:
            mine, theirs, me, opp = a, b, (lchar, lrate), (rchar, rrate)
        elif rid == TEKKEN_ID:
            mine, theirs, me, opp = b, a, (rchar, rrate), (lchar, lrate)
        else:
            continue
        games.append({
            "battle_at": datetime.fromtimestamp(int(ts.group(1)), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "mode": "ranked",
            "my_char": me[0],
            "opp_char": opp[0],
            "result": "W" if mine > theirs else "L",
            "rounds": f"{mine}-{theirs}",
            "my_rating": me[1],
            "opp_rating": opp[1],
        })
    return games


def game_key(r):
    """Matches the same game across ewgf.gg and Wavu Wank (timestamps are identical)."""
    return (r["battle_at"], r["my_char"], r["opp_char"], r["rounds"])


def merge(rows, games, since=None):
    """Add ratings to games already stored, and add ranked games that are missing.
    Returns (rated, added)."""
    by_key = {game_key(r): r for r in rows}
    rated = added = 0
    for g in games:
        r = by_key.get(game_key(g))
        if r is not None:
            if r.get("my_rating") != g["my_rating"] or r.get("opp_rating") != g["opp_rating"]:
                r["my_rating"], r["opp_rating"] = g["my_rating"], g["opp_rating"]
                rated += 1
            continue
        if since and g["battle_at"] < since:
            continue
        new = {**g, "opp_rank": None, "stage_id": None, "stage": None}
        rows.append(new)
        by_key[game_key(new)] = new
        added += 1
    return rated, added
