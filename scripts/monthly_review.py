"""
Monthly ranked review for Mike's Tekken 8 battles.

Reads data/battles.jsonl and writes reviews/monthly/<YYYY-MM>.md with the
month's ranked numbers. Ranked only: quick match is played loosely to feed the
data collector, so it isn't coaching data.

  MONTH=2026-10 python scripts/monthly_review.py   # a specific month
  python scripts/monthly_review.py                 # last month (or this month
                                                   # if run on the 1st... see pick_month)

The monthly scheduled task runs this on the 1st, then adds "Coach's notes"
at the top of the file it writes.
"""

import json
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta

from session_review import (TZ, local, margin, record, pct, fmt_record, table,
                            load_guides, load_queue, split_sessions, UNKNOWN_RANK)

BATTLES = "data/battles.jsonl"
MANIFEST = "guides/manifest.js"
OUT_DIR = "reviews/monthly"
MIN_GAMES = 4          # rows with fewer games are listed but never called out
TRUST_GAMES = 10       # below this, a number gets a "small sample" flag

ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8}


# ── helpers ──────────────────────────────────────────────────────────────────
def rank_order(rank):
    """Sort key: below God of Destruction < God of Destruction < GoD I < GoD II ..."""
    if rank == UNKNOWN_RANK:
        return (9, 0)                    # always last
    m = re.match(r"God of Destruction(?: (\w+))?$", rank)
    if not m:
        return (0, rank)
    return (1, ROMAN.get(m.group(1), 0) if m.group(1) else 0)


def is_decider(g):
    """The game went to a final round (3-2 either way)."""
    return sorted(int(x) for x in g["rounds"].split("-")) == [2, 3]


def rate(games):
    w, l = record(games)
    return w / (w + l) if games else 0.0


def flag(n):
    return "" if n >= TRUST_GAMES else " *"


def row(label, games):
    return [label, len(games), fmt_record(games) + flag(len(games))]


def load_guide_dates():
    """{character: 'YYYY-MM-DD'} from guides/manifest.js."""
    if not os.path.exists(MANIFEST):
        return {}
    text = open(MANIFEST).read()
    return dict(re.findall(r"character:\s*'([^']+)'.*?added:\s*'([^']+)'", text, re.S))


def first_games(games):
    """Mark each game as the first against that opponent (same character and
    rank, same session) or a follow-up. Ranked rematches are the only way to
    face the same player twice in a row, so this is a good proxy for 'game 1'."""
    out = []
    for session in split_sessions(games):
        prev = None
        for g in session:
            key = (g["my_char"], g["opp_char"], g["opp_rank"])
            out.append((g, prev != key))
            prev = key
    return out


def pick_month(arg):
    if arg:
        return arg
    now = datetime.now(TZ)
    # On the first few days of a month, review the month that just ended.
    target = now.replace(day=1) - timedelta(days=1) if now.day <= 7 else now
    return f"{target:%Y-%m}"


# ── ratings (Wavu Wank, rating before each game) ─────────────────────────────
RATING_GAP = 100       # opponents this much above/below Mike's rating count as stronger/weaker


def expected(g):
    """Chance of winning implied by the two ratings (Elo-style approximation of Glicko)."""
    return 1 / (1 + 10 ** ((g["opp_rating"] - g["my_rating"]) / 400))


def ratings_section(games):
    rated = [g for g in games if g.get("my_rating") is not None and g.get("opp_rating") is not None]
    if not rated:
        return ["## Ratings", "", "No rating data for this month.", ""]
    L = ["## Ratings", "",
         "From Wavu Wank: each player's rating going into the game (separate rating per character).", ""]

    rows = []
    for c in sorted({g["my_char"] for g in rated}, key=lambda c: -sum(g["my_char"] == c for g in rated)):
        gs = [g for g in rated if g["my_char"] == c]
        first, last = gs[0]["my_rating"], gs[-1]["my_rating"]
        rows.append([c, len(gs), first, last, f"{last - first:+d}", max(g["my_rating"] for g in gs)])
    L += [table(rows, ["Playing as", "Games", "Start of month", "Latest", "Change", "Peak"]), "",
          "Latest is the rating going into the month's last game.", ""]

    gap = lambda g: g["opp_rating"] - g["my_rating"]
    stronger = [g for g in rated if gap(g) >= RATING_GAP]
    even = [g for g in rated if -RATING_GAP < gap(g) < RATING_GAP]
    weaker = [g for g in rated if gap(g) <= -RATING_GAP]
    def vs_expected(gs):
        if not gs:
            return "–"
        exp = sum(expected(g) for g in gs)
        w = sum(g["result"] == "W" for g in gs)
        return f"{w} won vs {exp:.1f} expected ({w - exp:+.1f})"
    L += [table([
        row(f"Stronger opponent ({RATING_GAP}+ above you)", stronger) + [vs_expected(stronger)],
        row(f"Even (within {RATING_GAP})", even) + [vs_expected(even)],
        row(f"Weaker opponent ({RATING_GAP}+ below you)", weaker) + [vs_expected(weaker)],
        row("**All rated games**", rated) + [vs_expected(rated)],
    ], ["Opponent strength", "Games", "Record", "Wins vs what the ratings predicted"]), "",
        "Expected wins come from the rating gap (an Elo-style estimate). Beating the prediction means "
        "you played above your rating against that group; falling short means below it.", ""]
    return L


# ── report ───────────────────────────────────────────────────────────────────
def build(month, games, all_ranked):
    guides, queue, guide_dates = load_guides(), load_queue(), load_guide_dates()
    sessions = split_sessions(games)
    L = [f"# Monthly ranked review: {datetime.strptime(month, '%Y-%m'):%B %Y}",
         f"{len(games)} ranked games across {len(sessions)} sessions · "
         f"{games[0]['t']:%b %-d} – {games[-1]['t']:%b %-d}", "",
         f"`*` = fewer than {TRUST_GAMES} games: a hint, not a verdict.", ""]

    # Headline
    L += ["## Headline", "", table(
        [row("**All ranked**", games)] +
        [row(c, [g for g in games if g["my_char"] == c])
         for c in sorted({g["my_char"] for g in games},
                         key=lambda c: -sum(g["my_char"] == c for g in games))],
        ["", "Games", "Record"]), ""]

    prev_month = (datetime.strptime(month, "%Y-%m").replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    prev = [g for g in all_ranked if f"{g['t']:%Y-%m}" == prev_month]
    if len(prev) >= TRUST_GAMES:
        L += [f"Last month ({prev_month}): {fmt_record(prev)} over {len(prev)} games.", ""]
    else:
        L += [f"No month-over-month comparison yet ({len(prev)} ranked games stored for {prev_month}).", ""]

    # Trend by week
    weeks = defaultdict(list)
    for g in games:
        monday = (g["t"] - timedelta(days=g["t"].weekday())).date()
        weeks[monday].append(g)
    L += ["## Week by week", "", table(
        [row(f"Week of {w:%b %-d}", gs) for w, gs in sorted(weeks.items())],
        ["", "Games", "Record"]), ""]

    # Sessions
    L += ["## Sessions", "", table(
        [[f"{s[0]['t']:%a %b %-d}, {s[0]['t']:%-I:%M %p}", len(s), fmt_record(s)] for s in sessions],
        ["Session", "Games", "Record"]), ""]

    # Known weak points
    fg = first_games(games)
    g1 = [g for g, first in fg if first]
    later = [g for g, first in fg if not first]
    dec = [g for g in games if is_decider(g)]
    dec_g1 = [g for g, first in fg if first and is_decider(g)]
    losses = [g for g in games if g["result"] == "L"]
    L += ["## The tracked weak points", "",
          "These are the patterns flagged in session reviews; the month shows whether they moved.", "",
          table([
              row("Game 1 vs a new opponent", g1),
              row("Game 2+ vs the same opponent", later),
              row("Final rounds (games that went 3-2 / 2-3)", dec),
              row("…of which game 1s", dec_g1),
          ], ["", "Games", "Record"]), "",
          table([
              ["Close losses (by 1 round)", sum(margin(g) == 1 for g in losses)],
              ["Lost by 2 rounds", sum(margin(g) == 2 for g in losses)],
              ["Blowouts (by 3 rounds)", sum(margin(g) >= 3 for g in losses)],
              ["Close wins (by 1 round)", sum(g["result"] == "W" and margin(g) == -1 for g in games)],
          ], ["Losses and close wins", "Games"]), ""]

    # Opponent rank
    by_rank = defaultdict(list)
    for g in games:
        by_rank[g["opp_rank"]].append(g)
    L += ["## By opponent rank", "", table(
        [row(r, by_rank[r]) for r in sorted(by_rank, key=rank_order)],
        ["Opponent rank", "Games", "Record"]), ""]
    if UNKNOWN_RANK in by_rank:
        L += [f"{UNKNOWN_RANK}: games imported from Wavu Wank, which doesn't record rank tiers. "
              "For those games, game 1 vs game 2+ is judged by opponent character alone.", ""]

    L += ratings_section(games)

    # Opponent characters
    by_opp = defaultdict(list)
    for g in games:
        by_opp[g["opp_char"]].append(g)
    rows = []
    for opp, gs in sorted(by_opp.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        added = guide_dates.get(opp)
        if added:
            before = [g for g in gs if f"{g['t']:%Y-%m-%d}" < added]
            after = [g for g in gs if f"{g['t']:%Y-%m-%d}" >= added]
            status = f"guide {added}: {fmt_record(before) if before else '–'} before, {fmt_record(after) if after else '–'} after"
        elif opp in queue:
            status = f"queue #{queue[opp]}"
        else:
            status = ""
        rows.append([opp, len(gs), fmt_record(gs) + flag(len(gs)), status])
    L += ["## Opponents", "", table(rows, ["Character", "Games", "Record", "Guide"]), ""]

    losing = sorted((rate(gs), -len(gs), o) for o, gs in by_opp.items()
                    if len(gs) >= MIN_GAMES and rate(gs) < 0.5)
    names = ", ".join(f"**{o}** {fmt_record(by_opp[o])}" for _, _, o in losing[:3])
    L += [f"Losing matchups with {MIN_GAMES}+ games: {names or 'none'}.", ""]

    # Session fatigue: early vs late games in a session
    early = [g for s in sessions for g in s[:10]]
    late = [g for s in sessions for g in s[10:]]
    L += ["## Within a session", "", table(
        [row("Games 1–10 of a session", early), row("Game 11 onward", late)],
        ["", "Games", "Record"]), ""]

    # Stages (only those with enough games)
    by_stage = defaultdict(list)
    no_stage = 0
    for g in games:
        if g.get("stage_id") is None:
            no_stage += 1                # backlog game: no stage recorded
            continue
        by_stage[g.get("stage") or f"Stage {g['stage_id']}"].append(g)
    st = [(s, gs) for s, gs in by_stage.items() if len(gs) >= MIN_GAMES]
    L += ["## Stages", ""]
    if st:
        L += [table([row(s, gs) for s, gs in sorted(st, key=lambda kv: -rate(kv[1]))],
                    ["Stage", "Games", "Record"]), "",
              f"Only stages with {MIN_GAMES}+ games are listed.", ""]
    else:
        L += [f"No stage reached {MIN_GAMES} games this month.", ""]
    if no_stage:
        L += [f"{no_stage} imported game(s) have no stage recorded and are left out here.", ""]

    L += ["---", f"Generated {datetime.now(TZ):%b %-d, %Y %-I:%M %p} from data/battles.jsonl, ranked games only. "
          "A session is a run of games with no break of 45+ minutes."]
    return "\n".join(L) + "\n"


def main():
    month = pick_month(os.environ.get("MONTH", "").strip())
    with open(BATTLES) as fh:
        games = [json.loads(line) for line in fh if line.strip()]
    ranked = [g for g in games if g["mode"] == "ranked"]
    for g in ranked:
        g["t"] = local(g["battle_at"])
        g["opp_rank"] = g.get("opp_rank") or UNKNOWN_RANK
    ranked.sort(key=lambda g: g["t"])
    picked = [g for g in ranked if f"{g['t']:%Y-%m}" == month]
    if not picked:
        print(f"No ranked games found for {month}.")
        return
    report = build(month, picked, ranked)
    os.makedirs(OUT_DIR, exist_ok=True)
    path = f"{OUT_DIR}/{month}.md"
    with open(path, "w") as fh:
        fh.write(report)
    print(report)
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
