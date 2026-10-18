"""Live battle poller: checks ewgf.gg for new games and saves them.

This replaces the old poller.ps1 window. Every check:
  1. asks ewgf.gg for your latest 100 battles,
  2. keeps a slim copy in memory for the stream overlay (never written to disk),
  3. saves any new games to data/battles.jsonl through collect_battles.save_rows(),
     the same privacy filter GitHub uses: no names, tags or IDs, ever.

Pacing follows the old poller exactly: never more often than every 30 seconds,
the hour's remaining requests spread evenly over what's left of the hour, a few
kept spare for the GitHub collector, and a clean pause if the limit is hit.
"""

import gzip
import json
import math
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import collect_battles as cb     # shared with GitHub's collector; don't edit the copy here

APP_DIR = Path(__file__).resolve().parent
TEKKEN_ID = cb.TEKKEN_ID
BASE_URL = os.environ.get("EWGF_BASE_URL", "https://api.ewgf.gg")   # override for testing only

INTERVAL = 30             # fastest check, in seconds
RESERVE = 3               # requests per hour left for the GitHub collector
MIN_WAIT = 60             # shortest pause after a "too many requests" reply
WINDOW = 3600             # ewgf.gg counts requests in one-hour windows
BLIND_WAIT_MAX = 600      # longest wait while the window's end is unknown
if os.environ.get("EWGF_TEST_FAST"):                                 # testing only
    INTERVAL, MIN_WAIT, WINDOW, BLIND_WAIT_MAX = 2, 2, 20, 4

# Where to look for your key, in order. The first file that exists is used.
KEY_FILES = [APP_DIR / "ewgf-key.txt", Path(r"D:\TekkenOverlay\ewgf-key.txt")]

LOG_FILE = APP_DIR / "app-log.txt"
DB_LOCK = threading.Lock()  # one writer at a time: the poller and the GitHub sync share the database
LOG_MAX_LINES = 2000      # about two weeks of streaming; older lines are trimmed at start


def utc_now():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def parse_utc(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def log(text):
    """Print a line in the app window and keep a dated copy in app-log.txt."""
    line = f"[{datetime.now().strftime('%I:%M:%S %p').lstrip('0')}] {text}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now():%Y-%m-%d} {line}\n")
    except OSError:
        pass


def trim_log():
    try:
        lines = LOG_FILE.read_text(encoding="utf-8").splitlines(keepends=True)
        if len(lines) > LOG_MAX_LINES:
            LOG_FILE.write_text("".join(lines[-LOG_MAX_LINES:]), encoding="utf-8")
    except OSError:
        pass


def find_key():
    for path in KEY_FILES:
        if path.exists():
            key = path.read_text(encoding="utf-8-sig").strip()
            if key:
                return key, path
    return None, None


class RateLimited(Exception):
    def __init__(self, retry_after):
        super().__init__("rate limited")
        self.retry_after = retry_after


class Poller(threading.Thread):
    """Runs in the background for as long as the app is open."""

    def __init__(self, key):
        super().__init__(daemon=True, name="ewgf-poller")
        self.key = key
        self.lock = threading.Lock()
        # What the overlay shows. Kept in memory only.
        self.overlay = {"updated": None, "tier": None, "error": "starting",
                        "paused_until": None, "battles": []}
        self.window_end = None        # when the current hourly window ends, as far as we can tell
        self.prev_remaining = None
        self.saving_ok = True         # turned off if the privacy check ever objects

    # ---- the overlay's data, served at /overlay-data.js ----------------------
    def overlay_js(self):
        with self.lock:
            return "window.OVERLAY_DATA = " + json.dumps(self.overlay, separators=(",", ":")) + ";"

    def set_overlay(self, battles=None, tier=None, error=None, paused_until=None):
        with self.lock:
            if battles is not None:
                self.overlay["battles"] = battles
            if tier is not None:
                self.overlay["tier"] = tier
            self.overlay.update(updated=iso(utc_now()), error=error, paused_until=iso(paused_until))

    # ---- talking to ewgf.gg ---------------------------------------------------
    def fetch(self):
        req = urllib.request.Request(f"{BASE_URL}/external/battles/{TEKKEN_ID}", headers={
            "Authorization": f"Bearer {self.key}", "Accept-Encoding": "gzip"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                ra = e.headers.get("Retry-After")
                raise RateLimited(int(ra) if ra and ra.strip().isdigit() else None)
            raise RuntimeError(f"ewgf.gg answered {e.code}") from None

    @staticmethod
    def overlay_rows(raw):
        """Only what the overlay shows: characters, ranks, result, rounds. No names or IDs."""
        rows = []
        for b in raw:
            if b.get("p1_tekken_id") == TEKKEN_ID:
                me, op, won = "p1", "p2", b.get("winner") == 1
            elif b.get("p2_tekken_id") == TEKKEN_ID:
                me, op, won = "p2", "p1", b.get("winner") == 2
            else:
                continue
            rows.append({
                "battle_at": b.get("battle_at"),
                "mode": cb.MODES.get(b.get("battle_type"), str(b.get("battle_type", "")).lower()),
                "my_char": b.get(f"{me}_char"), "my_rank": b.get(f"{me}_dan_rank"),
                "opp_char": b.get(f"{op}_char"), "opp_rank": b.get(f"{op}_dan_rank"),
                "result": "W" if won else "L",
                "rounds": f"{b.get(f'{me}_rounds_won')}-{b.get(f'{op}_rounds_won')}",
            })
        return rows

    # ---- saving to the battle database ----------------------------------------
    def save_new(self, raw):
        """Same steps as collect_battles.main(), minus the GitHub-only parts. Returns # new."""
        if not self.saving_ok:
            return 0
        with DB_LOCK:
            return self._save_new(raw)

    def _save_new(self, raw):
        with open(cb.STAGES, encoding="utf-8") as fh:
            stage_names = json.load(fh)["confirmed"]
        existing = cb.load_rows()
        seen = {cb.key(r) for r in existing}
        wank_only = {cb.game_id(r): r for r in existing if r.get("stage_id") is None}
        new, filled = [], 0
        for b in raw:
            r = cb.slim(b, stage_names)
            if r and cb.game_id(r) in wank_only:
                wank_only.pop(cb.game_id(r)).update({f: r[f] for f in ("opp_rank", "stage_id", "stage", "mode")})
                filled += 1
                continue
            if r and cb.key(r) not in seen:
                seen.add(cb.key(r))
                new.append(r)
        if new or filled:
            try:
                cb.save_rows(existing + new)
            except SystemExit as e:              # the privacy check refused a value
                self.saving_ok = False
                log(f"STOPPED SAVING: {e}. The overlay keeps working; nothing more is written.")
                return 0
        return len(new)

    # ---- pacing (same rules as the old poller) --------------------------------
    def delay(self, remaining):
        if remaining is None:
            return INTERVAL
        seconds_left = WINDOW                                  # unknown end: assume a whole hour
        if self.window_end:
            s = (self.window_end - utc_now()).total_seconds()
            if s > 0:
                seconds_left = s
        usable = int(remaining) - RESERVE
        if usable <= 0:
            d = math.ceil(seconds_left) + 5                    # wait for the reset
        else:
            d = max(INTERVAL, math.ceil(seconds_left / usable))
        if not self.window_end:
            d = min(d, BLIND_WAIT_MAX)
        return d

    def check_once(self):
        """One check. Returns how many seconds to wait before the next."""
        try:
            payload = self.fetch()
        except RateLimited as e:
            wait = e.retry_after
            if not wait and self.window_end:
                wait = int((self.window_end - utc_now()).total_seconds()) + 5
            if not wait or wait < MIN_WAIT:
                wait = max(MIN_WAIT, 300)
            wait = min(wait, 3600)
            resume = utc_now() + timedelta(seconds=wait)
            log(f"ewgf.gg hourly limit reached. Pausing until "
                f"{resume.astimezone().strftime('%I:%M %p').lstrip('0')}.")
            self.set_overlay(error="rate_limited", paused_until=resume)
            self.prev_remaining = 0        # the first reply after the pause counts as a new window
            return wait
        except Exception as e:             # network down, ewgf slow, bad reply...
            log(f"Could not reach ewgf.gg: {e}")
            self.set_overlay(error=str(e))
            return INTERVAL

        raw = payload.get("data", []) or []
        meta = payload.get("_metadata", {}) or {}
        remaining, tier = meta.get("rate_limit_remaining"), meta.get("tier")
        now = utc_now()

        # Work out when the hourly window ends: a count that jumps back up means
        # a new hour started; a reset time in the future is trusted as-is.
        if remaining is not None and self.prev_remaining is not None and int(remaining) > int(self.prev_remaining):
            self.window_end = now + timedelta(seconds=WINDOW)
        reset = parse_utc(meta.get("rate_limit_reset"))
        if reset and reset > now + timedelta(seconds=5):
            self.window_end = reset
        if self.window_end and self.window_end <= now:
            self.window_end = None
        self.prev_remaining = remaining

        rows = self.overlay_rows(raw)
        wait = self.delay(remaining)
        if wait > 300:
            self.set_overlay(rows, tier, "rate_limited", now + timedelta(seconds=wait))
        else:
            self.set_overlay(rows, tier)

        added = self.save_new(raw)
        saved = f"{added} new saved" if added else "no new games"
        log(f"{len(rows)} battles, {saved} | {tier} tier, {remaining} requests left this hour, "
            f"next check in {wait}s")
        return wait

    def run(self):
        trim_log()
        log(f"Poller started (checks every {INTERVAL}s or more)")
        while True:
            time.sleep(self.check_once())
