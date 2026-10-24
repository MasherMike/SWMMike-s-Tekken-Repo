"""Live battle poller: checks ewgf.gg for new games and saves them.

This replaces the old poller.ps1 window. Every check:
  1. asks ewgf.gg for your latest 100 battles,
  2. keeps a slim copy in memory for the stream overlay (never written to disk),
  3. saves any new games to data/battles.jsonl through collect_battles.save_rows(),
     the same privacy filter GitHub uses: no names, tags or IDs, ever.

Pacing: every 10 seconds while you're playing (a game in the last 20 minutes),
every 60 seconds otherwise. Never faster than the hour's remaining requests
allow, spread evenly over what's left of the hour, a few kept spare for the
GitHub collector, and a clean pause if the limit is hit.

The window and app-log.txt only get a line when something happens (new games,
a problem, the pace changing), plus one summary line an hour.
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

ACTIVE_INTERVAL = 10      # check this often while you're playing, in seconds
IDLE_INTERVAL = 60        # ...and this often otherwise
ACTIVE_FOR = 20 * 60      # "playing" = your newest game is less than this old
RESERVE = 3               # requests per hour left for the GitHub collector
MIN_WAIT = 60             # shortest pause after a "too many requests" reply
WINDOW = 3600             # ewgf.gg counts requests in one-hour windows
BLIND_WAIT_MAX = 600      # longest wait while the window's end is unknown
HEARTBEAT = 3600          # one "still running" summary line this often
if os.environ.get("EWGF_TEST_FAST"):                                 # testing only
    ACTIVE_INTERVAL, IDLE_INTERVAL, MIN_WAIT, WINDOW, BLIND_WAIT_MAX, HEARTBEAT = 1, 2, 2, 20, 4, 6

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


class safe_open:
    """open() for the battle database files that never leaves half a file behind.
    Writes go to "<file>.tmp" and replace the real file only once complete, so a
    crash or power cut mid-save keeps the previous version. Reading is plain open().
    server.py hands this to collect_battles as its open(), so that file stays
    identical to GitHub's copy."""

    def __new__(cls, path, mode="r", *args, **kwargs):
        if "w" not in mode:
            return open(path, mode, *args, **kwargs)
        return super().__new__(cls)

    def __init__(self, path, mode="r", *args, **kwargs):
        self.path, self.tmp = str(path), f"{path}.tmp"
        self.fh = open(self.tmp, mode, *args, **kwargs)

    def __enter__(self):
        return self.fh

    def __exit__(self, kind, *_):
        try:
            if kind is None:
                self.fh.flush()
                os.fsync(self.fh.fileno())
        finally:
            self.fh.close()
        if kind is not None:
            try:
                os.remove(self.tmp)
            except OSError:
                pass
            return
        for attempt in range(10):
            try:
                os.replace(self.tmp, self.path)
                return
            except PermissionError:           # Windows: the page is reading it right now
                if attempt == 9:
                    raise
                time.sleep(0.2)


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
        self.check_lock = threading.Lock()   # the End session button can ask for a check too
        self.pace = IDLE_INTERVAL     # seconds between checks: ACTIVE_ or IDLE_INTERVAL
        self.problems = {}            # last error logged per kind, so it's logged once, not every check
        self.throttled = False        # pacing itself to the hourly limit right now
        self.checks = self.saved = 0  # since the last summary line
        self.next_heartbeat = time.monotonic() + HEARTBEAT

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
        try:
            with DB_LOCK:
                added = self._save_new(raw)
            self.resolved("save", "Saving games works again")
            return added
        except OSError as e:                     # disk full, file locked...: try again next check
            self.report(f"Could not save new games: {e}. Will try again next check.", "save")
            return 0

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

    # ---- logging: only when something happens -------------------------------
    def report(self, problem, kind="ewgf"):
        """Log a problem once; the same problem on every check stays quiet."""
        if problem != self.problems.get(kind):
            log(problem)
            self.problems[kind] = problem

    def resolved(self, kind, what):
        if self.problems.pop(kind, None):
            log(what)

    def heartbeat(self, remaining, tier):
        if time.monotonic() < self.next_heartbeat:
            return
        saved = f"{self.saved} new game{'s' if self.saved != 1 else ''} saved" if self.saved else "no new games"
        log(f"Still checking: {self.checks} checks in the last hour, {saved} | "
            f"{tier} tier, {remaining} requests left this hour")
        self.checks = self.saved = 0
        self.next_heartbeat = time.monotonic() + HEARTBEAT
        trim_log()

    # ---- pacing ----------------------------------------------------------------
    def set_pace(self, rows):
        """Fast while you're playing (newest game under ACTIVE_FOR old), slow otherwise."""
        newest = max((t for t in (parse_utc(r["battle_at"]) for r in rows) if t), default=None)
        playing = newest is not None and (utc_now() - newest).total_seconds() < ACTIVE_FOR
        pace = ACTIVE_INTERVAL if playing else IDLE_INTERVAL
        if pace != self.pace:
            log(f"{'Playing' if playing else 'No games for ' + str(ACTIVE_FOR // 60) + ' minutes'}: "
                f"checking every {pace}s")
            self.pace = pace

    def delay(self, remaining):
        if remaining is None:
            return self.pace
        seconds_left = WINDOW                                  # unknown end: assume a whole hour
        if self.window_end:
            s = (self.window_end - utc_now()).total_seconds()
            if s > 0:
                seconds_left = s
        usable = int(remaining) - RESERVE
        if usable <= 0:
            d = math.ceil(seconds_left) + 5                    # wait for the reset
        else:
            d = max(self.pace, math.ceil(seconds_left / usable))
        if not self.window_end:
            d = min(d, BLIND_WAIT_MAX)
        return d

    def check_once(self):
        """One check. Returns how many seconds to wait before the next."""
        with self.check_lock:
            return self._check_once()

    def _check_once(self):
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
            self.problems["ewgf"] = "rate limited"   # so the next good reply says it's answering again
            self.set_overlay(error="rate_limited", paused_until=resume)
            self.prev_remaining = 0        # the first reply after the pause counts as a new window
            return wait
        except Exception as e:             # network down, ewgf slow, bad reply...
            self.report(f"Could not reach ewgf.gg: {e}")
            self.set_overlay(error=str(e))
            return self.pace
        self.resolved("ewgf", "ewgf.gg is answering again")

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
        self.set_pace(rows)
        wait = self.delay(remaining)
        if wait > 300:
            self.set_overlay(rows, tier, "rate_limited", now + timedelta(seconds=wait))
        else:
            self.set_overlay(rows, tier)

        added = self.save_new(raw)
        self.checks += 1
        self.saved += added
        if added:
            log(f"{added} new game{'s' if added != 1 else ''} saved | {tier} tier, "
                f"{remaining} requests left this hour")
        throttled = wait > self.pace * 2   # pacing itself to the hourly limit: worth knowing, once
        if throttled and not self.throttled:
            log(f"Only {remaining} requests left this hour: slowing to one check every {wait}s")
        self.throttled = throttled
        self.heartbeat(remaining, tier)
        return wait

    def run(self):
        trim_log()
        log(f"Poller started (every {ACTIVE_INTERVAL}s while you're playing, every {IDLE_INTERVAL}s otherwise; "
            f"this window stays quiet unless something happens)")
        while True:
            try:
                wait = self.check_once()
            except Exception as e:             # never let one bad check stop the poller for good
                self.report(f"Poller hit a problem: {e}")
                wait = self.pace
            time.sleep(wait)
