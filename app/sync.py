"""Keeps the app's battle database and your GitHub repo in step.

Every 15 minutes (and once a minute after the app starts):
  1. download data/battles.jsonl from GitHub (overnight games, Wavu Wank ratings),
  2. merge it with the app's copy: same game from both sides -> one row, every
     known field kept (collect_battles.save_rows does this, privacy filter included),
  3. if GitHub is missing anything, upload the merged battles.jsonl/.js/.csv as one commit.

It also keeps the app's copy of the website current: index.html, the guides
(guides/*.html, guides/manifest.js), the app's pages (app/site/*.html), queue.md
and past reviews (reviews/*.md, for the Session Gallery) are
downloaded whenever GitHub's version differs, so a new weekly guide shows up
here within 15 minutes. The app's Python code is never changed this way.

On GitHub it only ever writes those three data files, plus reviews/*.md when
you press End session (End session merges GitHub's copy first and pushes the
review and the data as ONE commit, so the review never counts a game that
GitHub doesn't have yet). The token lives in github-token.txt
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
    if repo_path.startswith("app/site/") and repo_path.count("/") == 2:     # overlay.html, review.html
        return SITE_DIR / repo_path.split("/")[-1]
    if repo_path == "queue.md":                                            # the review reads guide queue positions
        return APP_DIR / "queue.md"
    if repo_path.startswith("reviews/") and repo_path.count("/") == 1 and repo_path.endswith(".md"):
        return APP_DIR / repo_path                                         # past reviews for the Session Gallery
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

    def push(self, parent_sha, files=None, message="data: sync from the Tekken app"):
        """Upload files ({repo path: local path}; default the three data files) as one commit."""
        files = files or {repo_path: local() for repo_path, local in FILES.items()}
        base_tree = self.api("GET", f"/git/commits/{parent_sha}")["tree"]["sha"]
        tree = []
        for repo_path, local in files.items():
            blob = self.api("POST", "/git/blobs", {"content": lf_bytes(local).decode("utf-8"), "encoding": "utf-8"})
            tree.append({"path": repo_path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        new_tree = self.api("POST", "/git/trees", {"base_tree": base_tree, "tree": tree})["sha"]
        commit = self.api("POST", "/git/commits", {"message": message,
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

    def push_files(self, files, message):
        """Push extra files (e.g. a review), retrying if GitHub moves on meanwhile."""
        for attempt in range(3):
            head = self.api("GET", f"/git/ref/heads/{BRANCH}")["object"]["sha"]
            try:
                return self.push(head, files, message)
            except urllib.error.HTTPError as e:
                if e.code in (409, 422) and attempt < 2:
                    time.sleep(3)
                    continue
                raise

    def sync_once(self):
        site = ""
        try:
            head = self.api("GET", f"/git/ref/heads/{BRANCH}")["object"]["sha"]
            updated = self.pull_site(head)
            if updated:
                site = f"; downloaded from GitHub: {', '.join(updated)}"
        except Exception as e:                        # the data sync still runs
            site = f"; site update failed: {e}"
        return self._sync_data() + site

    def data_files(self):
        return {repo_path: local() for repo_path, local in FILES.items()}

    def merge_remote(self, head):
        """Pull GitHub's battles.jsonl (at commit `head`) into the app's copy.
        Returns (games after merge, games pulled from GitHub, already identical)."""
        remote = self.remote_rows(head)
        with poller.DB_LOCK:
            local = cb.load_rows()
            before = len(local)
            merged = cb.save_rows(local + remote)          # dedupes + privacy filter, writes all 3 files
        remote_text = "".join(json.dumps(r, ensure_ascii=False) + "\n"
                              for r in sorted(cb.merge_duplicates([cb.clean(r) for r in remote]),
                                              key=lambda r: str(r["battle_at"])))
        same = lf_bytes(cb.BATTLES).decode("utf-8") == remote_text
        return len(merged), len(merged) - before, same

    def merge_from_github(self):
        """Merge step for End session: GitHub's games and ratings into the app's copy
        (pushes nothing). Returns a line for the steps list."""
        head = self.api("GET", f"/git/ref/heads/{BRANCH}")["object"]["sha"]
        total, pulled, _ = self.merge_remote(head)
        return f"Merged GitHub's copy ({total} games, {pulled} pulled from GitHub)"

    def push_with_data(self, extra_files, message):
        """One commit with the three data files AND `extra_files` ({repo path: local path}),
        after merging GitHub's copy so nothing GitHub has is overwritten. Retries if
        GitHub moves on meanwhile (a collector run)."""
        for attempt in range(3):
            head = self.api("GET", f"/git/ref/heads/{BRANCH}")["object"]["sha"]
            self.merge_remote(head)
            files = self.data_files()
            files.update(extra_files)
            try:
                return self.push(head, files, message)
            except urllib.error.HTTPError as e:
                if e.code in (409, 422) and attempt < 2:
                    time.sleep(3)
                    continue
                raise

    def _sync_data(self):
        for attempt in range(3):
            head = self.api("GET", f"/git/ref/heads/{BRANCH}")["object"]["sha"]
            merged, pulled, same = self.merge_remote(head)
            if same:
                return f"in sync ({merged} games{f', {pulled} pulled from GitHub' if pulled > 0 else ''})"
            try:
                self.push(head)
                return (f"pushed to GitHub ({merged} games"
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
