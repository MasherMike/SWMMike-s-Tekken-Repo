# Tekken app

Your Tekken tools as one program on your PC: the stage tracker and guides,
the live battle poller, the stream overlay, and a sync that keeps the battle
database and this repo in step. It replaces the old `overlay/` PowerShell
poller.

| Address | What |
|---|---|
| `http://localhost:8787/` | Stage tracker and matchup guides |
| `http://localhost:8787/overlay.html?layout=strip&anchor=bottom&scale=1.25` | Twitch strip (Streamlabs Browser source, 700 x 56) |
| `http://localhost:8787/scoreboard.html` | **Scoreboard** for off-stream sessions: last game, session record against your 10-game minimum (`?min=` to change it), every match, and tonight's opponents with lifetime records and guide links or queue spots. Ranked by default; the All modes button is remembered |
| `http://localhost:8787/review.html` | **Session Gallery**: run a review for any window (last session, today, yesterday, last 7/14/30 days, a date range) and any mix of Ranked/Quick/Player/Group; browse every saved review |

Only your PC can reach these addresses.

## Files

| File | Job |
|---|---|
| `Start Tekken App.bat` | Double-click to start. Close its window to stop. |
| `README - Start here.txt` | One-page cheat sheet that sits in the app folder on the PC |
| `Open Stage Tracker.html`, `Open Session Gallery.html`, `Open Scoreboard.html` | Double-click shortcuts to the app's pages (the app must be running) |
| `Start with Windows (on-off).bat` | Double-click to make the app start by itself at login (minimized, no browser); again to turn it off |
| `server.py` | The local web server; starts the poller and the sync; serves `queue.md` for the Scoreboard |
| `poller.py` | Checks ewgf.gg every 10 s while you're playing (a game in the last 20 min), every 60 s otherwise; feeds the overlay, saves new games (each file written whole, so a crash never leaves half a database); logs only events plus one summary line an hour |
| `sync.py` | Every 15 min: pulls GitHub's battle data (overnight games, Wavu Wank ratings), merges, pushes the app's new games; also downloads new or changed guides, `index.html` and the overlay (never the Python code) |
| `review.py` | Session Gallery: one fresh ewgf check, one Wavu Wank ratings check (ranked reviews only, at most one per 10 minutes), then merges GitHub's battle data, then `scripts/session_review.py`; saves to `reviews/` here and pushes the review **and** `data/` to GitHub as one commit, and lists saved reviews |
| `site/overlay.html` | The overlay (panel or strip) |
| `site/scoreboard.html` | The off-stream Scoreboard |
| `site/review.html` | The Session Gallery page. On GitHub Pages (`…/review.html`, e.g. from your phone) the same page is read-only: it lists `reviews/` from the repo and links to the End session workflow to run a new review |
| `install.py` | Rebuilds a working app folder from this repo |

The app also uses `scripts/collect_battles.py`, `scripts/session_review.py`,
`scripts/wank.py` and `scripts/collect_wank.py`
from the repo unchanged, so the privacy filter (`save_rows`) and the review are
the same everywhere: no names, tags or IDs.

## On your PC only (never in the repo)

- `ewgf-key.txt`: your ewgf.gg API key
- `github-token.txt`: fine-grained token, this repo only, Contents read and write
- `app-log.txt`: everything the app window prints, newest 2,000 lines
- `data/`: the app's battle database (the sync keeps GitHub's copy in step)

## Reinstall (new PC, dead drive)

1. Install Python from the Microsoft Store ("Python install manager"), then run
   `py install --configure` and `py -m pip install tzdata` in a command window
   (Windows has no time zone data of its own; the review needs it).
2. On GitHub: **Code → Download ZIP**, and unzip it.
3. In a command window inside the unzipped folder:
   `py app\install.py D:\SW-T8\app`
4. Put `ewgf-key.txt` and `github-token.txt` into `D:\SW-T8\app`.
5. Double-click `Start Tekken App.bat`.

Guides, `index.html` and the overlay update themselves through the sync.
Running `install.py` again over an existing install also updates the Python
code, and keeps your keys and database.
