"""Install or update the Tekken app from this repo.

    py app\\install.py D:\\SW-T8\\app

Run it from an unzipped copy of the repo (GitHub: Code -> Download ZIP).
It copies:
  - the app's code (this folder) and the shared scripts (scripts/collect_battles.py,
    scripts/session_review.py, scripts/wank.py, scripts/collect_wank.py)
  - the website: index.html and guides/
  - the battle database (data/), but ONLY if the target doesn't have one yet

It never touches ewgf-key.txt, github-token.txt or app-log.txt, and never
overwrites an existing database: the app's own copy is the newest one, and
the GitHub sync merges the two by itself.
"""

import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
APP_SRC = REPO / "app"

CODE = ["server.py", "poller.py", "sync.py", "review.py",
        "Start Tekken App.bat", "Start with Windows (on-off).bat",
        "README - Start here.txt", "Open Stage Tracker.html", "Open Session Gallery.html", "Open Scoreboard.html"]
SHARED = ["collect_battles.py", "session_review.py", "wank.py", "collect_wank.py"]     # from scripts/, used unchanged


def copy(src, dst, note):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    print(f"  {note:9} {dst}")


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    target = Path(sys.argv[1]).resolve()
    print(f"Installing the Tekken app into {target}")

    for name in CODE:
        copy(APP_SRC / name, target / name, "code")
    for name in SHARED:
        copy(REPO / "scripts" / name, target / name, "code")
    for page in sorted((APP_SRC / "site").glob("*.html")):           # overlay.html, review.html
        copy(page, target / "site" / page.name, "page")
    copy(REPO / "queue.md", target / "queue.md", "queue")
    copy(REPO / "index.html", target / "site" / "index.html", "site")
    for g in sorted((REPO / "guides").iterdir()):
        if g.suffix in (".html", ".js"):
            copy(g, target / "site" / "guides" / g.name, "guide")

    data = target / "data"
    if (data / "battles.jsonl").exists():
        print(f"  kept      {data / 'battles.jsonl'} (already there; the sync merges it with GitHub)")
        copy(REPO / "data" / "stages.json", data / "stages.json", "data")
    else:
        for name in ("battles.jsonl", "stages.json"):
            copy(REPO / "data" / name, data / name, "data")
        copy(REPO / "data" / "battles.js", target / "site" / "data" / "battles.js", "data")

    for f, what in (("ewgf-key.txt", "ewgf API key"), ("github-token.txt", "GitHub token")):
        if not (target / f).exists():
            print(f"  missing   {target / f}  <- put your {what} here")
    print("Done. Start it with 'Start Tekken App.bat'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
