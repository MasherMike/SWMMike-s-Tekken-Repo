"""Keeps the app's battle database and your GitHub repo in step.

Every 15 minutes (and once a minute after the app starts):
  1. download data/battles.jsonl from GitHub (overnight games, Wavu Wank ratings),
  2. merge it with the app's copy: same game from both sides -> one row, every
     known field kept (collect_battles.save_rows does this, privacy filter included),
  3. if GitHub is missing anything, upload the merged battles.jsonl/.js/.csv as one commit.

It also keeps the app's copy of the website current: index.html, the guides
(guides/*.html, guides/manifest.js) and the overlay (app/site/overlay.html) are
downloaded whenever GitHub's version differs, so a new weekly guide shows up
here within 15 minutes. The app's Python code is never changed this way.

On GitHub it only ever writes those three data files. The token lives in github-token.txt
next to this file and never leaves the PC except to talk to api.github.com.
"""

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import collect_battles as cb
import poller                      # for log() and the shared database lock

APP_DIR = Path(__file__).resolve().parent
OWNER, REPO, BRANCH = "MasherMike", "SWMMike-s-Tekken-Repo", "main"
API = os.environ.get("GITHUB_API_URL", "https://api.github.com")      # override for testing only
TOKEN_FILE = APP_DIR / "github-token.txt"
EVERY = int(os.environ.get("SYNC_EVERY", "900"))                     # seconds between syncs
FIRST = int(os.environ.get("SYNC_FIRST", "60"))                       # first sync after start
FILES = {                                                             # repo path -> local file
    "data/battles.jsonl": lambda: cb.BATTLES,
    "data/battles.js": lambda: cb.PAGE_COPY,
    "data/battles.csv": lambda: cb.CSV_COPY,
}


SITE_DIR = APP_DIR / "site"


def site_target(repo_path):
    """Where a repo file goes in the app's site folder, or None if it isn't a site file."""
    if repo_path == "index.html":
        return SITE_DIR / "index.html"
    if repo_path == "app/site/overlay.html":
        return SITE_DIR / "overlay.html"
    if repo_path.startswith("guides/") and repo_path.count("/") == 1 and repo_path.endswith((".html", ".js")):
        return SITE_DIR / repo_path
    return None


def git_blob_sha(path):
    """The id GitHub gives a file's contents, so unchanged files aren't downloaded again."""
    data = path.read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def find_token():
    if TOKEN_FILE.exists():
        t = TOKEN_FILE.read_text(encoding="utf-8-sig").strip()
        return t or None
    return None


def lf_bytes(path):
    """File contents with Unix line endings, the way GitHub stores them.
    (Python on Windows writes \\r\\n; uploading that would change every line.)"""
    return Path(path).read_bytes().replace(b"\r\n", b"\n")


class Sync(threading.Thread):
    def __init__(self, token):
        super().__init__(daemon=True, name="github-sync")
        self.token = token
        self.last = None             # short status for the window

    def api(self, method, path, body=None, raw=False):
        req = urllib.request.Request(f"{API}/repos/{OWNER}/{REPO}{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None)
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Accept", "application/vnd.github.raw+json" if raw else "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        if body is not None:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
        return data if raw else json.loads(data or b"{}")

    def remote_rows(self, commit_sha):
        text = self.api("GET", f"/contents/data/battles.jsonl?ref={commit_sha}", raw=True).decode("utf-8")
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def push(self, parent_sha):
        """Upload the three data files as one commit on top of parent_sha."""
        base_tree = self.api("GET", f"/git/commits/{parent_sha}")["tree"]["sha"]
        tree = []
        for repo_path, local in FILES.items():
            blob = self.api("POST", "/git/blobs", {"content": lf_bytes(local()).decode("utf-8"), "encoding": "utf-8"})
            tree.append({"path": repo_path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        new_tree = self.api("POST", "/git/trees", {"base_tree": base_tree, "tree": tree})["sha"]
        commit = self.api("POST", "/git/commits", {"message": "data: sync from the Tekken app",
                                                     "tree": new_tree, "parents": [parent_sha]})["sha"]
        # Not forced: if GitHub moved on meanwhile (a collector run), this fails and we retry.
        self.api("PATCH", f"/git/refs/heads/{BRANCH}", {"sha": commit, "force": False})

    def pull_site(self, commit_sha):
        """Download site files that differ from GitHub's. Returns the names updated."""
        tree = self.api("GET", f"/git/commits/{commit_sha}")["tree"]["sha"]
        entries = self.api("GET", f"/git/trees/{tree}?recursive=1")["tree"]
        updated = []
        for e in entries:
            target = site_target(e["path"]) if e.get("type") == "blob" else None
            if not target or (target.exists() and git_blob_sha(target) == e["sha"]):
                continue
            data = self.api("GET", f"/contents/{e['path']}?ref={commit_sha}", raw=True)
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(target.suffix + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, target)                   # swap in whole, never half a file
            updated.append(e["path"].split("/")[-1])
        return updated

    def sync_once(self):
        site = ""
        try:
            head = self.api("GET", f"/git/ref/heads/{BRANCH}")["object"]["sha"]
            updated = self.pull_site(head)
            if updated:
                site = f"; site updated: {', '.join(updated)}"
        except Exception as e:                        # the data sync still runs
            site = f"; site update failed: {e}"
        return self._sync_data() + site

    def _sync_data(self):
        for attempt in range(3):
            head = self.api("GET", f"/git/ref/heads/{BRANCH}")["object"]["sha"]
            remote = self.remote_rows(head)
            with poller.DB_LOCK:
                local = cb.load_rows()
                before = len(local)
                merged = cb.save_rows(local + remote)          # dedupes + privacy filter, writes all 3 files
            remote_text = "".join(json.dumps(r, ensure_ascii=False) + "\n"
                                  for r in sorted(cb.merge_duplicates([cb.clean(r) for r in remote]),
                                                  key=lambda r: str(r["battle_at"])))
            pulled = len(merged) - before
            if lf_bytes(cb.BATTLES).decode("utf-8") == remote_text:
                return f"in sync ({len(merged)} games{f', {pulled} pulled from GitHub' if pulled > 0 else ''})"
            try:
                self.push(head)
                return (f"pushed to GitHub ({len(merged)} games"
                        f"{f', {pulled} pulled from GitHub' if pulled > 0 else ''})")
            except urllib.error.HTTPError as e:
                if e.code in (409, 422) and attempt < 2:   # GitHub moved on; start over from the new head
                    time.sleep(3)
                    continue
                raise
        return "GitHub kept changing; will try again next time"

    def run(self):
        time.sleep(FIRST)
        while True:
            try:
                self.last = self.sync_once()
                poller.log(f"GitHub sync: {self.last}")
            except SystemExit as e:                 # privacy filter objected: stop syncing
                poller.log(f"GitHub sync STOPPED: {e}")
                return
            except urllib.error.HTTPError as e:
                hint = " (check github-token.txt: expired or missing 'Contents: read and write'?)" if e.code in (401, 403, 404) else ""
                poller.log(f"GitHub sync failed: GitHub answered {e.code}{hint}")
            except Exception as e:
                poller.log(f"GitHub sync failed: {e}")
            time.sleep(EVERY)
