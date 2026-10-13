# SWMMike's Tekken Repo

Mike's Tekken 8 training system: battle data collected automatically, reviewed
after every session and every month, and turned into anti-character guides.

**The loop:** play → collect → review → prepare → play.

## What runs on its own

| What | When | Where |
|---|---|---|
| Collect battles from ewgf.gg (Pro API) | Every hour | `.github/workflows/collect-battles.yml` → `scripts/collect_battles.py` |
| Add ratings from Wavu Wank | Midnight, 8 AM, 4 PM Eastern | `.github/workflows/collect-wank.yml` → `scripts/collect_wank.py` |
| Build one anti-character guide | Fridays, 9:47 AM | Claude scheduled task, reads `queue.md` |
| Monthly ranked review with coach's notes | 1st of the month, 9:55 AM | Claude scheduled task → `reviews/monthly/` |

## What you run

- **End-of-session review:** GitHub → Actions → **End session** → Run workflow.
  Pick *last session* or *today*, and *ranked* (default) or *all*. The report
  lands in `reviews/LATEST.md` and on the run's summary page.
- **Stream overlay:** see `overlay/README.md`. Runs on your PC with your own
  ewgf key, which never leaves it.
- **Backlog import from saved Wavu Wank pages** (one-time, e.g. Jin or Armor King):
  `python scripts/import_wank.py --since 2026-01-01 page1.html page2.html`.
  Never commit the saved pages; they contain names and IDs.

## The data

`data/battles.jsonl` is the database: one battle per line, ranked from
Jan 1, 2026 plus all modes since Oct 3, 2026. `data/battles.js` (for the
website) and `data/battles.csv` (for the Google Sheet) are copies rewritten on
every save.

| Field | Meaning | Source |
|---|---|---|
| `battle_at` | When the game ended (UTC) | both |
| `mode` | ranked / quick / player / group | ewgf (Wank games are all ranked) |
| `my_char`, `opp_char` | Characters | both |
| `opp_rank` | Opponent's rank tier | ewgf only (null on backlog games) |
| `result`, `rounds` | W/L and round score, yours first | both |
| `stage_id`, `stage` | Stage (names in `data/stages.json`) | ewgf only (null on backlog games) |
| `my_rating`, `opp_rating` | Each player's rating **going into** the game, per character | Wavu Wank (ranked only) |

**Privacy rule: no player names, tags or IDs, ever.** It's enforced in code:
every write goes through `save_rows()` in `scripts/collect_battles.py`, which
keeps only `ALLOWED_FIELDS` and stops the run if a value looks like a player
ID. Adding a field means changing that list on purpose.

## Coaching rules

- Coaching reads **ranked only**. Quick match is played loosely to feed the
  collector and isn't graded.
- Numbers under 10 games are hints, not verdicts.
- Opponent strength is judged by rating (every ranked game has it) rather than
  rank tier (only ewgf games have it).

## Where things are

| Path | What |
|---|---|
| `index.html` | Website: stage tracker, live records, Matchup Guides tab |
| `guides/` | Anti-character guides + `manifest.js` (powers the Guides tab) |
| `queue.md` | Order the weekly guide task follows; edit freely |
| `sidestep.md` | Community sidestep chart, used as secondary evidence in guides |
| `reviews/` | Session reviews (`LATEST.md` = newest) and `monthly/` reviews |
| `scripts/` | Collectors, reviews, Wank parser and importer |
| `overlay/` | OBS stream overlay and its local poller |
| `data/ewgf-schema.json` | Field list of the ewgf API (no personal values) |
| `data/lag-test-2026-10-10.json` | Result of the Pro lag test: median 0.7 min from game to API (worst 9.7) over 26 games |

## Outside the repo

- **Google Sheet "Tekken 8 Battle Log":** reads `data/battles.csv`. The Mode filter is set to Ranked.
- **Secrets:** `EWGF_API_KEY` is a repository secret. Nobody, Claude included, sees its value.
- If a collector fails, GitHub emails you about the failed run (Settings → Notifications → Actions).
