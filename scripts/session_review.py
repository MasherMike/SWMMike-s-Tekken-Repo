"""
End-of-session review for Mike's Tekken 8 battles.

Reads data/battles.jsonl (kept current by collect_battles.py) and writes:
  reviews/<date>-<HHMM>.md   one file per session reviewed
  reviews/LATEST.md          a copy of the newest review
and prints the same report so the workflow can show it on the run page.

A "session" is a run of games with no break of SESSION_GAP_MIN or longer.
Set SCOPE=today to review every game played today instead.

MODE picks which games count. It defaults to "ranked": Mike plays quick match
loosely to feed the data collector, so coaching reads ranked games only.
Set MODE=all to review every mode. Games left out are named in one line.

Run by .github/workflows/end-session.yml.
"""

import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")    # Mike's time zone; handles daylight saving
SESSION_GAP_MIN = 45                 # a break this long starts a new session
REMATCH_GAP_MIN = 6                  # back-to-back games closer than this can be a rematch set
REMATCH_MIN_GAMES = 3
MIN_SAMPLE = 3                       # rows with fewer games are shown but not called out

UNKNOWN_RANK = "Rank unknown"     # backlog games imported from Wavu Wank have no rank tier or stage
BATTLES = "data/battles.jsonl"
MANIFEST = "guides/manifest.js"
QUEUE = "queue.md"
OUT_DIR = "reviews"


# ── helpers ──────────────────────────────────────────────────────────────────
def local(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(TZ)


def margin(b):
    """Opponent's rounds minus Mike's: 1 = lost by one round, -1 = won by one."""
    mine, theirs = (int(x) for x in b["rounds"].split("-"))
    return theirs - mine


def record(games):
    w = sum(g["result"] == "W" for g in games)
    return w, len(games) - w


def pct(w, n):
    return f"{round(100 * w / n)}%" if n else "–"


def fmt_record(games):
    w, l = record(games)
    return f"{w}–{l} ({pct(w, w + l)})"


def hm(dt):
    return dt.strftime("%-I:%M %p")


def load_guides():
    """{character: artifact link} from guides/manifest.js."""
    if not os.path.exists(MANIFEST):
        return {}
    text = open(MANIFEST).read()
    pairs = re.findall(r"character:\s*'([^']+)'.*?artifact:\s*'([^']+)'", text, re.S)
    return dict(pairs)


def load_queue():
    """{character: position} for characters still waiting for a guide."""
    if not os.path.exists(QUEUE):
        return {}
    text = open(QUEUE).read().split("## Queue", 1)[-1].split("##", 1)[0]
    names = re.findall(r"^- ([A-Za-z0-9 .\-]+?)\s*(?:<!--|$)", text, re.M)
    return {n.strip(): i for i, n in enumerate(names, 1)}


# ── picking the games to review ──────────────────────────────────────────────
def split_sessions(games):
    sessions, current = [], []
    for g in games:
        if current and (g["t"] - current[-1]["t"]) >= timedelta(minutes=SESSION_GAP_MIN):
            sessions.append(current)
            current = []
        current.append(g)
    if current:
        sessions.append(current)
    return sessions


def pick_games(games, scope):
    if scope == "today":
        today = datetime.now(TZ).date()
        picked = [g for g in games if g["t"].date() == today]
        return picked, "Today"
    sessions = split_sessions(games)
    return (sessions[-1], "Last session") if sessions else ([], "Last session")


# ── analysis ─────────────────────────────────────────────────────────────────
def rematch_sets(games):
    """Back-to-back games vs the same character at the same rank, same mode and
    same character for Mike, each within REMATCH_GAP_MIN of the last."""
    sets, run = [], [games[0]] if games else []
    key = lambda g: (g["mode"], g["my_char"], g["opp_char"], g["opp_rank"])
    for prev, g in zip(games, games[1:]):
        close_in_time = (g["t"] - prev["t"]) <= timedelta(minutes=REMATCH_GAP_MIN)
        if key(g) == key(prev) and close_in_time:
            run.append(g)
        else:
            if len(run) >= REMATCH_MIN_GAMES:
                sets.append(run)
            run = [g]
    if len(run) >= REMATCH_MIN_GAMES:
        sets.append(run)
    return sets


def streaks(games):
    best = {"W": (0, None, None), "L": (0, None, None)}
    run_kind, run = None, []
    for g in games + [None]:
        if g is not None and g["result"] == run_kind:
            run.append(g)
            continue
        if run and len(run) > best[run_kind][0]:
            best[run_kind] = (len(run), run[0], run[-1])
        if g is not None:
            run_kind, run = g["result"], [g]
    return best


def loss_breakdown(games):
    losses = [g for g in games if g["result"] == "L"]
    return {
        "close": sum(margin(g) == 1 for g in losses),
        "two": sum(margin(g) == 2 for g in losses),
        "blowout": sum(margin(g) >= 3 for g in losses),
        "close_wins": sum(g["result"] == "W" and margin(g) == -1 for g in games),
        "losses": len(losses),
    }


def table(rows, headers):
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


# ── report ───────────────────────────────────────────────────────────────────
def build(games, label, all_games, mode="all", skipped=()):
    guides, queue = load_guides(), load_queue()
    start, end = games[0]["t"], games[-1]["t"]
    lines = [f"# Session review: {start:%a %b %-d, %Y}",
             f"{label} · {hm(start)} – {hm(end)} · {len(games)} games", ""]
    if mode != "all":
        note = f"Reviewing **{mode} games only**."
        if skipped:
            modes = ", ".join(sorted({g["mode"] for g in skipped}))
            note += (f" Left out {len(skipped)} {modes} game(s) played in the same window "
                     f"({fmt_record(skipped)}); set the mode to \"all\" to include them.")
        lines += [note, ""]

    # Results by mode and by character
    lines += ["## Results", ""]
    rows = []
    for m in ("ranked", "quick", "player", "group"):
        sub = [g for g in games if g["mode"] == m]
        if sub:
            rows.append([m.capitalize(), len(sub), fmt_record(sub)])
    rows.append(["**All**", len(games), f"**{fmt_record(games)}**"])
    lines += [table(rows, ["Mode", "Games", "Record"]), ""]

    chars = Counter(g["my_char"] for g in games)
    if len(chars) > 1:
        rows = [[c, n, fmt_record([g for g in games if g["my_char"] == c])] for c, n in chars.most_common()]
        lines += [table(rows, ["Playing as", "Games", "Record"]), ""]

    # Compared with Mike's stored ranked history
    ranked_now = [g for g in games if g["mode"] == "ranked"]
    earlier = [g for g in all_games if g["mode"] == "ranked" and g["t"] < start]
    if ranked_now and len(earlier) >= 10:
        w, l = record(earlier)
        lines += [f"Ranked this session: **{pct(record(ranked_now)[0], len(ranked_now))}** "
                  f"vs **{pct(w, w + l)}** across your {w + l} earlier stored ranked games.", ""]

    # How the losses went
    lb = loss_breakdown(games)
    if lb["losses"]:
        lines += ["## How the losses went", "",
                  table([["Close (lost by 1 round)", lb["close"]],
                         ["Lost by 2 rounds", lb["two"]],
                         ["Blowouts (lost by 3+ rounds)", lb["blowout"]],
                         ["Close wins (won by 1 round)", lb["close_wins"]]], ["", "Games"]),
                  "",
                  "Close losses are matchups you're nearly solving. Blowouts are the ones to lab.", ""]

    # Rematch sets
    sets = rematch_sets(games)
    if sets:
        why = ("In ranked these are where you adapt: the last column shows whether you did."
               if mode == "ranked" else
               "These are fights you chose, so read them as practice, not results.")
        lines += ["## Rematch sets", "",
                  "Back-to-back games against the same character at the same rank. " + why, ""]
        rows = []
        for s in sets:
            half = len(s) // 2
            early = sum(margin(g) for g in s[:half]) / half
            late = sum(margin(g) for g in s[half:]) / (len(s) - half)
            if late < early - 0.3:
                trend = f"tightening ({early:+.1f} → {late:+.1f})"
            elif late > early + 0.3:
                trend = f"widening ({early:+.1f} → {late:+.1f})"
            else:
                trend = f"steady ({early:+.1f} → {late:+.1f})"
            rows.append([f"{s[0]['my_char']} vs {s[0]['opp_char']} ({s[0]['opp_rank']})",
                         s[0]["mode"], f"{hm(s[0]['t'])} – {hm(s[-1]['t'])}",
                         fmt_record(s), trend])
        lines += [table(rows, ["Set", "Mode", "When", "Record", "Round margin, early → late"]),
                  "", "Round margin is the opponent's rounds minus yours, averaged: "
                  "a number moving toward zero or below means the set was getting closer.", ""]

    # Streaks and tilt
    st = streaks(games)
    n, first, last = st["L"]
    if n >= 3:
        streak = [g for g in games if first["t"] <= g["t"] <= last["t"]]
        set_ids = {id(g) for s in sets for g in s}
        in_sets = [g for g in streak if id(g) in set_ids]
        outside = [g for g in streak if id(g) not in set_ids]
        outside_opps = {(g["opp_char"], g["opp_rank"]) for g in outside}
        if len(in_sets) >= len(streak) / 2:
            biggest = Counter(g["opp_char"] for g in in_sets).most_common(1)[0][0]
            note = (f"{len(in_sets)} of the {n} were rematch-set games (mostly vs {biggest}), "
                    f"so this is mainly the set, not tilt.")
            if len(outside_opps) >= 3:
                note += f" The other {len(outside)} came against {len(outside_opps)} different opponents, which is worth watching."
        elif len(outside_opps) >= 3:
            note = (f"against {len(outside_opps)} different opponents outside any rematch set. "
                    "That spread is what tilt usually looks like: worth a break next time.")
        else:
            opps = sorted({g["opp_char"] for g in streak})
            who = opps[0] if len(opps) == 1 else ", ".join(opps[:-1]) + " and " + opps[-1]
            ranks = sorted({g["opp_rank"] for g in streak})
            rank_note = f", all {ranks[0]}" if len(ranks) == 1 else ""
            note = f"against {who}{rank_note}."
        lines += ["## Streaks", "",
                  f"- Longest losing streak: **{n}** ({hm(first['t'])} – {hm(last['t'])}), {note}"]
        wn, wf, wl = st["W"]
        if wn >= 2:
            lines += [f"- Longest winning streak: **{wn}** ({hm(wf['t'])} – {hm(wl['t'])})"]
        lines += [""]

    # Opponents (rematch sets counted once per game, like any other game)
    by_opp = defaultdict(list)
    for g in games:
        by_opp[g["opp_char"]].append(g)
    rows = []
    for opp, gs in sorted(by_opp.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if opp in guides:
            ref = f"[guide]({guides[opp]})"
        elif opp in queue:
            ref = f"queue #{queue[opp]}"
        else:
            ref = ""
        rows.append([opp, len(gs), fmt_record(gs), ref])
    lines += ["## Opponents", "", table(rows, ["Character", "Games", "Record", "Guide"]), ""]

    # Stages
    by_stage = defaultdict(list)
    for g in games:
        if g.get("stage_id") is None:
            continue                     # backlog game: no stage recorded
        by_stage[g.get("stage") or f"Stage {g['stage_id']}"].append(g)
    rows = [[s, len(gs), fmt_record(gs)] for s, gs in sorted(by_stage.items(), key=lambda kv: (-len(kv[1]), kv[0]))]
    lines += ["## Stages", "", table(rows, ["Stage", "Games", "Record"]),
              "", f"One session is too few games per stage to judge a stage; use the Battle Log sheet for that.", ""]

    # Worth a look: worst non-rematch matchup with enough games
    rematch_games = {id(g) for s in sets for g in s}
    candidates = []
    for opp, gs in by_opp.items():
        free = [g for g in gs if id(g) not in rematch_games]
        if len(free) >= MIN_SAMPLE:
            w, l = record(free)
            candidates.append((w / (w + l), -len(free), opp, free))
    if candidates:
        rate, _, opp, free = sorted(candidates)[0]
        if rate < 0.5:
            ref = (f"Its guide: {guides[opp]}" if opp in guides
                   else f"No guide yet; it's #{queue[opp]} in the queue. Move it up in queue.md if it keeps happening."
                   if opp in queue else "")
            caution = (f" Only {len(free)} games, so treat it as a hint, not a verdict."
                       if len(free) < 5 else "")
            lines += ["## Worth a look", "",
                      f"Outside rematch sets, your roughest matchup was **{opp}**: {fmt_record(free)}.{caution} {ref}", ""]

    lines += ["---", f"Generated {datetime.now(TZ):%b %-d, %Y %-I:%M %p} from data/battles.jsonl. "
              f"A session is a run of games with no break of {SESSION_GAP_MIN}+ minutes."]
    return "\n".join(lines) + "\n"


def main():
    scope = os.environ.get("SCOPE", "last session").strip().lower()
    with open(BATTLES) as fh:
        games = [json.loads(line) for line in fh if line.strip()]
    for g in games:
        g["t"] = local(g["battle_at"])
        g["opp_rank"] = g.get("opp_rank") or UNKNOWN_RANK
    games.sort(key=lambda g: g["t"])

    mode = os.environ.get("MODE", "ranked").strip().lower() or "ranked"
    pool = games if mode == "all" else [g for g in games if g["mode"] == mode]
    picked, label = pick_games(pool, scope)
    if not picked:
        print(f"No {mode} games found for '{scope}'.")
        return
    if mode != "all":
        label = f"{label} ({mode})"
    start, end = picked[0]["t"], picked[-1]["t"]
    skipped = [g for g in games if g["mode"] != mode and start <= g["t"] <= end] if mode != "all" else []
    report = build(picked, label, games, mode, skipped)

    os.makedirs(OUT_DIR, exist_ok=True)
    name = f"{OUT_DIR}/{picked[0]['t']:%Y-%m-%d-%H%M}.md"
    for path in (name, f"{OUT_DIR}/LATEST.md"):
        with open(path, "w") as fh:
            fh.write(report)
    print(report)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as fh:
            fh.write(report)


if __name__ == "__main__":
    main()
