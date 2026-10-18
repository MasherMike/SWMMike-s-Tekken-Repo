# Tekken app

Your Tekken tools as one program on your PC: the stage tracker and guides,
the live battle poller, the stream overlay, and a sync that keeps the battle
database and this repo in step. It replaces the old `overlay/` PowerShell
poller.

| Address | What |
|---|---|
| `http://localhost:8787/` | Stage tracker and matchup guides |
| `http://localhost:8787/overlay.html?layout=strip&anchor=bottom&scale=1.25` | Twitch strip (Streamlabs Browser source, 700 x 56) |
| `http://localhost:8787/overlay.html?opps=8&min=2&scale=1.5` | Full scoreboard for off-stream sessions (Brave) |

Only your PC can reach these addresses.

## Files

| File | Job |
|---|---|
| `Start Tekken App.bat` | Double-click to start. Close its window to stop. |
| `server.py` | The local web server; starts the poller and the sync |
| `poller.py` | Checks ewgf.gg every 30 s or more, feeds the overlay, saves new games |
| `sync.py` | Every 15 min: pulls GitHub's battle data (overnight games, Wavu Wank ratings), merges, pushes the app's new games; also downloads new or changed guides, `index.html` and the overlay (never the Python code) |
| `site/overlay.html` | The overlay (panel or strip) |
| `install.py` | Rebuilds a working app folder from this repo |

The app also uses `scripts/collect_battles.py` from the repo unchanged, so the
privacy filter (`save_rows`) is the same everywhere: no names, tags or IDs.

## On your PC only (never in the repo)

- `ewgf-key.txt`: your ewgf.gg API key
- `github-token.txt`: fine-grained token, this repo only, Contents read and write
- `app-log.txt`: everything the app window prints, newest 2,000 lines
- `data/`: the app's battle database (the sync keeps GitHub's copy in step)

## Reinstall (new PC, dead drive)

1. Install Python from the Microsoft Store ("Python install manager"), then run
   `py install --configure` in a command window.
2. On GitHub: **Code → Download ZIP**, and unzip it.
3. In a command window inside the unzipped folder:
   `py app\install.py D:\SW-T8\app`
4. Put `ewgf-key.txt` and `github-token.txt` into `D:\SW-T8\app`.
5. Double-click `Start Tekken App.bat`.

Guides, `index.html` and the overlay update themselves through the sync.
Running `install.py` again over an existing install also updates the Python
code, and keeps your keys and database.
