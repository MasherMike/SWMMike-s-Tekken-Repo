"""Session Gallery: the same review as GitHub's "End session" workflow, run on this PC,
for any window (last session, today, yesterday, last 7/14/30 days, a date range)
and any mix of modes (ranked, quick, player, group).

  1. one fresh check of ewgf.gg, so your last game is included,
  2. one ratings check of Wavu Wank (ranked reviews only), so the review has ratings,
  3. scripts/session_review.py (copied into the app as session_review.py), unchanged,
  4. the review saved to reviews/ here and pushed to reviews/ on GitHub.

The Session Gallery page (site/review.html) calls these through the server.
"""

import os
import re
import threading
import time
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


SCOPES = ("last session", "today", "yesterday", "last 7 days", "last 14 days", "last 30 days")
MODES = ("ranked", "quick", "player", "group")
RANGE = re.compile(r"^range:\d{4}-\d{2}-\d{2}\.\.\d{4}-\d{2}-\d{2}$")
NAME = re.compile(r"^[0-9A-Za-z_-]+\.md$")


WANK_STAMP = APP_DIR / "wank-last-check.txt"   # time of the last ratings check from this PC
WANK_MIN_GAP = 10 * 60                         # at most one Wavu Wank request per 10 minutes


def add_ratings():
    """One request to your Wavu Wank page; adds my_rating/opp_rating to the games
    it lists. Returns a line for the steps list. Never raises: a review without
    ratings is still a review."""
    try:
        last = float(WANK_STAMP.read_text().strip())
    except (OSError, ValueError):
        last = 0
    if time.time() - last < WANK_MIN_GAP:
        return "Ratings checked less than 10 minutes ago: skipped (be kind to Wavu Wank)"
    try:
        import collect_wank
        html = collect_wank.fetch_page(timeout=30)
        WANK_STAMP.write_text(str(time.time()))
        with poller.DB_LOCK:
            rows = cb.load_rows()
            listed, rated, added = collect_wank.add_ratings(rows, html)
            cb.save_rows(rows)
        poller.log(f"Wavu Wank: {listed} games listed, {rated} given ratings, {added} added")
        extra = f", {added} game{'s' if added != 1 else ''} ewgf hadn't sent yet" if added else ""
        return f"Checked Wavu Wank: {rated} game{'s' if rated != 1 else ''} got ratings{extra}"
    except Exception as e:                       # offline, site down, layout changed
        poller.log(f"Wavu Wank check failed: {e}")
        return f"Couldn't reach Wavu Wank ({e}); reviewed without new ratings"


def latest():
    f = OUT_DIR / "LATEST.md"
    return f.read_text(encoding="utf-8") if f.exists() else None


def gallery():
    """Saved reviews, newest first: name, title line and summary line."""
    items = []
    for p in OUT_DIR.glob("*.md") if OUT_DIR.exists() else []:
        if p.name == "LATEST.md":
            continue
        head = p.read_text(encoding="utf-8").splitlines()[:2] + ["", ""]
        items.append({"name": p.name, "title": head[0].lstrip("# ").strip(), "summary": head[1].strip(),
                      "saved": p.stat().st_mtime})
    # newest first by the last day covered: "2026-10-17-2053.md" or "2026-10-10-to-2026-10-17.md"
    end = lambda n: n.split("-to-")[1][:10] + "-9999" if "-to-" in n else n[:15]
    return sorted(items, key=lambda i: end(i["name"]), reverse=True)


def read(name):
    if not NAME.match(name or ""):
        return None
    f = OUT_DIR / name
    return f.read_text(encoding="utf-8") if f.exists() else None


def run(scope, mode, poller_obj=None, sync_obj=None):
    """Returns {"ok", "markdown", "file", "steps": [...]}."""
    scope = (scope or "").strip().lower()
    if scope not in SCOPES and not RANGE.match(scope):
        scope = "last session"
    modes = [m for m in (mode if isinstance(mode, list) else str(mode or "").split(",")) if m in MODES] or ["ranked"]
    mode = ",".join(modes)
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

        # 2. ratings (Wavu Wank only rates ranked games)
        if "ranked" in modes:
            steps.append(add_ratings())

        # 3. the review itself (the repo's script, pointed at the app's files)
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

        # 4. GitHub
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
