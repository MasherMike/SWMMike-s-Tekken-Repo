"""End session: the same review as GitHub's "End session" workflow, run on this PC.

  1. one fresh check of ewgf.gg, so your last game is included,
  2. scripts/session_review.py (copied into the app as session_review.py), unchanged,
  3. the review saved to reviews/ here and pushed to reviews/ on GitHub.

The website's End session page (review.html) calls run() through the server.
"""

import os
import threading
from pathlib import Path

import collect_battles as cb
import poller

APP_DIR = Path(__file__).resolve().parent
OUT_DIR = APP_DIR / "reviews"
LOCK = threading.Lock()           # one review at a time (double-clicks)

TZDATA_FIX = ("Python can't find time zone data on this PC. Fix it once: open a command "
              "window and run   py -m pip install tzdata   then restart the app.")


def tz_ok():
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo("America/New_York")
        return True
    except Exception:
        return False


def latest():
    f = OUT_DIR / "LATEST.md"
    return f.read_text(encoding="utf-8") if f.exists() else None


def run(scope, mode, poller_obj=None, sync_obj=None):
    """Returns {"ok", "markdown", "file", "steps": [...]}."""
    scope = "today" if scope == "today" else "last session"
    mode = "all" if mode == "all" else "ranked"
    steps = []
    if not tz_ok():
        return {"ok": False, "error": TZDATA_FIX, "steps": steps}
    if not LOCK.acquire(blocking=False):
        return {"ok": False, "error": "A review is already running.", "steps": steps}
    try:
        # 1. fresh games
        if poller_obj is not None:
            poller_obj.check_once()
            steps.append("Checked ewgf.gg for your newest games")
        else:
            steps.append("Poller off: reviewed the games already saved")

        # 2. the review itself (the repo's script, pointed at the app's files)
        import session_review as sr
        sr.BATTLES = cb.BATTLES
        sr.MANIFEST = str(APP_DIR / "site" / "guides" / "manifest.js")
        sr.QUEUE = str(APP_DIR / "queue.md")
        sr.OUT_DIR = str(OUT_DIR)
        old_env = {k: os.environ.get(k) for k in ("SCOPE", "MODE", "GITHUB_STEP_SUMMARY")}
        os.environ.update(SCOPE=scope, MODE=mode)
        os.environ.pop("GITHUB_STEP_SUMMARY", None)
        printed = []
        sr.print = lambda *a, **k: printed.append(" ".join(map(str, a)))   # keep the window tidy
        try:
            with poller.DB_LOCK:
                sr.main()
        finally:
            for k, v in old_env.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        if printed and printed[0].startswith("No "):
            return {"ok": False, "error": printed[0], "steps": steps}
        text = latest() or ""
        # the dated file the script just wrote is the newest one with LATEST.md's contents
        same = [p for p in OUT_DIR.glob("*.md") if p.name != "LATEST.md" and p.read_text(encoding="utf-8") == text]
        name = max(same, key=lambda p: p.stat().st_mtime).name if same else "LATEST.md"
        steps.append(f"Wrote reviews/{name}")

        # 3. GitHub
        if sync_obj is not None:
            try:
                sync_obj.push_files({f"reviews/{name}": str(OUT_DIR / name),
                                     "reviews/LATEST.md": str(OUT_DIR / "LATEST.md")},
                                    f"review: {scope} ({mode}) from the Tekken app")
                steps.append("Saved to GitHub (reviews/)")
            except Exception as e:
                steps.append(f"Couldn't save to GitHub ({e}); it's kept here in reviews/")
        else:
            steps.append("GitHub sync off: kept here in reviews/ only")
        poller.log(f"End session: {scope} ({mode}) -> reviews/{name}")
        return {"ok": True, "markdown": text, "file": name, "steps": steps}
    finally:
        LOCK.release()
