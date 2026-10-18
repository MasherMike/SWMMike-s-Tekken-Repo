"""SW-T8 app: your Tekken tools, running on this PC only.

  http://localhost:8787/              stage tracker and matchup guides
  http://localhost:8787/overlay.html  stream overlay (Streamlabs/OBS Browser source)

Start it by double-clicking "Start Tekken App.bat". Stop it by closing its
window (or pressing Ctrl+C in it). Nothing outside this computer can reach it.

While it runs, the live poller (poller.py) checks ewgf.gg for new games, feeds
the overlay and saves every new game to data/battles.jsonl, and sync.py keeps
that database and the GitHub repo in step (needs github-token.txt).
"""

import errno
import functools
import http.server
import json
import os
import socket
import sys
import threading
import webbrowser
from pathlib import Path

PORT = 8787                      # change here if another program already uses 8787
HOST = "127.0.0.1"               # "this PC only"; never change to 0.0.0.0
APP_DIR = Path(__file__).resolve().parent
SITE_DIR = APP_DIR / "site"      # index.html, guides/, overlay.html live here
DATA_DIR = APP_DIR / "data"      # the battle database (battles.jsonl) lives here
URL = f"http://localhost:{PORT}/"

os.chdir(APP_DIR)                # so the shared collector's "data/..." paths land in the app
sys.path.insert(0, str(APP_DIR))
import collect_battles as cb     # noqa: E402  (shared with GitHub; the privacy filter lives here)
import poller                    # noqa: E402
import sync                      # noqa: E402
import review                    # noqa: E402

# Point the shared collector at the app's files. The website reads its copy
# from site/data/battles.js; the CSV copy sits with the database.
cb.BATTLES = str(DATA_DIR / "battles.jsonl")
cb.STAGES = str(DATA_DIR / "stages.json")
cb.PAGE_COPY = str(SITE_DIR / "data" / "battles.js")
cb.CSV_COPY = str(DATA_DIR / "battles.csv")

POLLER = None                    # set in main() once the key is found
SYNC = None                      # set in main() once the GitHub token is found


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    """Serves files from site/, without browser caching and without log spam."""

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/favicon.ico":               # browsers ask for a tab icon; we have none yet
            self.send_response(204)
            self.end_headers()
            return
        if path == "/overlay-data.js":           # the overlay's live data, straight from memory
            if POLLER is None:
                self.send_error(503, "Poller not running")
                return
            body = POLLER.overlay_js().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/api/review/latest":
            text = review.latest()
            return self.send_json({"ok": bool(text), "markdown": text or ""})
        if path == "/api/reviews":
            return self.send_json({"ok": True, "reviews": review.gallery()})
        if path == "/api/review":
            from urllib.parse import parse_qs, urlsplit
            name = parse_qs(urlsplit(self.path).query).get("name", [""])[0]
            text = review.read(name)
            return self.send_json({"ok": bool(text), "markdown": text or ""}, 200 if text else 404)
        super().do_GET()

    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        # Only the app's own pages may ask for this: a page on another site can't
        # send the custom header without a permission check this server never grants.
        origin = self.headers.get("Origin")
        if self.headers.get("X-Tekken-App") != "1" or (origin and origin not in (URL.rstrip("/"), f"http://127.0.0.1:{PORT}")):
            return self.send_json({"ok": False, "error": "Not allowed"}, 403)
        if self.path.split("?", 1)[0] != "/api/end-session":
            return self.send_json({"ok": False, "error": "Unknown action"}, 404)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            body = {}
        result = review.run(body.get("scope"), body.get("mode"), POLLER, SYNC)
        self.send_json(result)

    def end_headers(self):
        # Always send the newest file, so fresh battle data shows on refresh.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        # Only report problems (404s and errors), not every page load.
        if len(args) > 1 and str(args[1])[:1] in "45":
            print(f"  [!] {self.path} -> {args[1]}")


def already_running():
    """True if something is already answering on our port (likely another copy)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((HOST, PORT)) == 0


def start_poller():
    global POLLER
    key, where = poller.find_key()
    if not key:
        print("  Poller : OFF. No ewgf-key.txt found. Looked in:")
        for p in poller.KEY_FILES:
            print(f"           {p}")
        print("           The site still works; the overlay and live saving need the key.")
        return
    print(f"  Poller : ON (key from {where})")
    POLLER = poller.Poller(key)
    POLLER.start()


def start_sync():
    token = sync.find_token()
    if not token:
        print(f"  GitHub : OFF. No github-token.txt in {APP_DIR}")
        print("           Games are still saved here; they just aren't backed up to GitHub.")
        return
    global SYNC
    print(f"  GitHub : ON (syncs a minute after start, then every {sync.EVERY // 60} min)")
    SYNC = sync.Sync(token)
    SYNC.start()


def main():
    if not (SITE_DIR / "index.html").exists():
        print(f"Can't find {SITE_DIR / 'index.html'}.")
        print("The 'site' folder should sit next to server.py.")
        input("Press Enter to close")
        return 1

    if already_running():
        print("The Tekken app is already running. Opening it in your browser.")
        webbrowser.open(URL)
        return 0

    handler = functools.partial(QuietHandler, directory=str(SITE_DIR))
    try:
        server = http.server.ThreadingHTTPServer((HOST, PORT), handler)
    except OSError as e:
        if e.errno in (errno.EADDRINUSE, 10048):
            print(f"Port {PORT} is taken by another program.")
            print("Open server.py in Notepad and change PORT near the top (e.g. to 8788).")
        else:
            print(f"Couldn't start the server: {e}")
        input("Press Enter to close")
        return 1

    print("Tekken app running.")
    print(f"  Site   : {URL}")
    print(f"  Overlay: {URL}overlay.html")
    start_poller()
    start_sync()
    print(f"  Gallery: {URL}review.html  (Session Gallery: reviews)")
    if not review.tz_ok():
        print("  [!] " + review.TZDATA_FIX)
    print("  Leave this window open. Close it to stop the app.")
    print()
    if not os.environ.get("TEKKEN_APP_NO_BROWSER"):    # set when started with Windows
        threading.Timer(0.5, webbrowser.open, args=(URL,)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("Tekken app stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
