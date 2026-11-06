"""
Download and parse the four sources an anti-character guide is built from.

  python scripts/fetch_sources.py "Armor King"

Writes build/sources/<Character>/ (git-ignored):
  sources.json   everything parsed, ready to build a guide from
  *.html         the raw pages, kept for re-parsing
and prints a short summary. Exit code 0 = all four sources parsed;
2 = at least one failed (its "error" says why) - fall back to the fetch tool
for that source only. A missing anti-strat page (404) is normal for some
characters and is reported as "missing", not as a failure.

Sources (each site's robots.txt allows this; requests are identified and spaced):
  wavu_movelist     https://wavu.wiki/t/<Character>_movelist   full frame data (primary)
  wavu_counterplay  https://wavu.wiki/t/<Character>_counterplay standing-block punishment buckets + prose
  tekkendocs        https://tekkendocs.com/t8/<character>       frame data (cross-check); "parsed_from"
                    says which reader worked - see parse_tekkendocs
  antistrat         https://tekkendocs.com/t8/<character>/antistrat community strategy notes,
                    incl. step direction (use for Movement; verify its frames against Wavu)
"""

import gzip
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

UA = "SWMMike-Tekken-Repo/1.0 (personal matchup guides; github.com/MasherMike/SWMMike-s-Tekken-Repo)"
OUT_ROOT = "build/sources"
PAUSE = 2  # seconds between requests


# ── download ─────────────────────────────────────────────────────────────────
def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        raw = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return raw.decode("utf-8", errors="replace")


def text(fragment):
    """HTML fragment -> plain text (hover tooltips dropped, zero-width chars removed)."""
    fragment = re.sub(r'<span class="tooltip-body">.*?</span>', "", fragment, flags=re.S)
    fragment = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", fragment, flags=re.S)
    fragment = re.sub(r"<br\s*/?>|</(p|li|div|tr|h\d)>", "\n", fragment)
    out = html.unescape(re.sub(r"<[^>]+>", " ", fragment)).replace("​", "")
    out = re.sub(r"[ \t]+", " ", out)
    return re.sub(r"\s*\n\s*", "\n", out).strip()


# ── Wavu movelist / counterplay: one div.movedata per move ───────────────────
FIELDS = {  # output name: (lead class, main class)
    "input": ("movedata-inputLead", "movedata-input"),
    "hit_level": ("movedata-targetLead", "movedata-target"),
    "damage": ("movedata-damageLead", "movedata-damage"),
    "startup": ("movedata-startupRoot", "movedata-startup"),
    "block": (None, "movedata-block"),
    "hit": (None, "movedata-hit"),
    "ch": (None, "movedata-ch"),
    "states": (None, "movedata-crush"),
    "recovery": (None, "movedata-recv"),
    "notes": (None, "movedata-notes"),
    "name": (None, "movedata-name"),
}


def field(block, cls):
    m = re.search(rf'class="{cls}(?: [^"]*)?"[^>]*>(.*?)</(?:span|div)>', block, re.S)
    return text(m.group(1)).replace("\n", " ") if m else ""


def parse_movedata(page):
    moves = []
    parts = re.split(r'(<div[^>]*class="movedata[ "][^>]*>)', page)
    for opener, body in zip(parts[1::2], parts[2::2]):
        mid = re.search(r'id="([^"]+)"', opener)
        if not mid:
            continue  # the column-header block has no id
        move = {"id": html.unescape(mid.group(1))}
        for name, (lead, main) in FIELDS.items():
            move[name] = (field(body, lead) if lead else "") + field(body, main)
        notes = re.search(r'class="movedata-notes"[^>]*>(.*?)</div>\s*</div>', body, re.S)
        if notes:
            move["notes"] = text(notes.group(1)).replace("\n", " | ")
        moves.append(move)
    return moves


def parse_wavu_counterplay(page):
    """Punishment buckets (heading -> move ids) plus any prose sections."""
    body = page[page.find("mw-parser-output"):]
    # headings may carry an empty anchor span before the title: <h3><span id=".."></span><span class="mw-headline">
    chunks = re.split(r'<h([23])[^>]*>\s*(?:<span id="[^"]*"></span>)?<span class="mw-headline" id="([^"]+)"[^>]*>(.*?)</span>', body)
    buckets, prose = {}, {}
    for i in range(1, len(chunks) - 3, 4):
        heading, content = text(chunks[i + 2]), chunks[i + 3]
        ids = [html.unescape(x) for x in re.findall(r'<div[^>]*class="movedata[ "][^>]*id="([^"]+)"', content)]
        ids += [html.unescape(x) for x in re.findall(r'<div[^>]*id="([^"]+)"[^>]*class="movedata[ "]', content)]
        if ids:
            buckets[heading] = ids
        else:
            t = text(content)
            if t:
                prose[heading] = t
    return {"buckets": buckets, "prose": prose, "moves": parse_movedata(page)}


# ── TekkenDocs ───────────────────────────────────────────────────────────────
# The frame-data page has changed layout before: an HTML <table> until late Oct 2026,
# React-drawn divs after that. So parse_tekkendocs tries three readers in order and
# reports which one worked. Every reader returns rows keyed by the site's own column
# names ("Command", "Block frame", "Notes", ...).
#
#   1. turbo-stream  the page's embedded React Router data - every move, complete
#   2. html table    the pre-Oct-2026 layout, in case it comes back
#   3. meta tag      a pipe table in <meta name="description"> - only ~10 moves, so a
#                    result from here is kept but marked partial (and counts as a failure)

def turbo_stream_decode(page):
    """Decode React Router's serialized page data ("turbo-stream") from its <script> tags.

    The data is one flat JSON array. Objects are written as {"_<key index>": <value index>}
    and arrays as lists of indexes, and any value used twice is stored once and pointed
    to by index - so it has to be decoded as a whole, not regex-matched.
    Returns the decoded data, or None if the page has no stream.
    """
    decoder, chunks = json.JSONDecoder(), []
    for m in re.finditer(r"streamController\.enqueue\(", page):
        try:
            # raw_decode reads exactly one JSON string literal, escaped quotes and all
            chunk, _ = decoder.raw_decode(page, m.end())
        except ValueError:
            continue
        if isinstance(chunk, str):
            chunks.append(chunk)
    if not chunks:
        return None
    try:
        # line 1 is the page data; any later lines are deferred values the page doesn't use
        flat = json.loads("".join(chunks).split("\n", 1)[0])
    except ValueError:
        return None
    if not isinstance(flat, list) or not flat:
        return None

    memo = {}  # index -> decoded value; also stops shared/looping references from repeating

    def value(i):
        if not isinstance(i, int) or not 0 <= i < len(flat):
            return None  # negative indexes are constants (null, undefined, NaN...); None is close enough
        if i in memo:
            return memo[i]
        raw = flat[i]
        if isinstance(raw, dict):
            out = memo[i] = {}
            for k, ref in raw.items():
                name = flat[int(k[1:])] if k[1:].isdigit() else k
                out[str(name)] = value(ref)
        elif isinstance(raw, list) and not (raw and isinstance(raw[0], str)):
            out = memo[i] = []
            out.extend(value(r) for r in raw)
        else:
            out = memo[i] = raw  # a plain string/number, or a typed value like ["D", date] kept as-is
        return out

    return value(0)


def find_frame_data(node, seen=None):
    """Depth-first search of the decoded page data for the object holding the move list."""
    seen = set() if seen is None else seen
    if id(node) in seen:
        return None
    seen.add(id(node))
    if isinstance(node, dict):
        if isinstance(node.get("tables"), list) or isinstance(node.get("moves"), list):
            return node
        children = node.values()
    elif isinstance(node, list):
        children = node
    else:
        return None
    for child in children:
        found = find_frame_data(child, seen)
        if found is not None:
            return found
    return None


MOVE_FIELDS = [  # move-object field -> column name; only used if the page has no "tables"
    ("command", "Command"), ("hitLevel", "Hit level"), ("damage", "Damage"),
    ("startup", "Start up frame"), ("block", "Block frame"), ("hit", "Hit frame"),
    ("counterHit", "Counter hit frame"), ("notes", "Notes"), ("name", "Name"),
    ("recovery", "Recovery"), ("id", "Id"),
]


def cell(v):
    return "" if v is None else str(v)


def rows_from_turbo_stream(page):
    data = find_frame_data(turbo_stream_decode(page))
    if data is None:
        return []
    rows = []
    for table in data.get("tables") or []:  # e.g. {"name": "frames_normal", "headers": [...], "rows": [[...], ...]}
        if not isinstance(table, dict):
            continue
        heads, body = table.get("headers"), table.get("rows")
        if isinstance(heads, list) and isinstance(body, list):
            rows += [{cell(h): cell(v) for h, v in zip(heads, r)} for r in body if isinstance(r, list) and any(r)]
    if not rows:
        rows = [{c: cell(m.get(f)) for f, c in MOVE_FIELDS} for m in data.get("moves") or [] if isinstance(m, dict)]
    return [r for r in rows if r.get("Command")]


def rows_from_html_table(page):
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S)
    if not rows:
        return []
    head = [text(c) for c in re.findall(r"<th[^>]*>(.*?)</th>", rows[0], re.S)]
    out = []
    for r in rows[1:]:
        cells = [text(c).replace("\n", " ") for c in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)]
        if any(cells):
            out.append(dict(zip(head, cells)))
    return out


def rows_from_meta_description(page):
    m = re.search(r'<meta\s+name="description"\s+content="([^"]*)"', page)
    if not m:
        return []
    lines = [ln for ln in html.unescape(m.group(1)).split("\n") if "|" in ln]
    if len(lines) < 2:
        return []
    head = [c.strip() for c in lines[0].split("|")]
    return [dict(zip(head, (c.strip() for c in ln.split("|")))) for ln in lines[1:]]


PARTIAL = "meta description (partial)"


def parse_tekkendocs(page):
    """-> (rows, which reader found them). The first reader that finds rows wins."""
    for how, reader in (("turbo-stream", rows_from_turbo_stream),
                        ("html table", rows_from_html_table),
                        (PARTIAL, rows_from_meta_description)):
        rows = reader(page)
        if rows:
            return rows, how
    return [], None


def parse_antistrat(page):
    main = re.sub(r"<(script|style|nav|header|footer)[^>]*>.*?</\1>", "", page, flags=re.S)
    parts = re.split(r"<h([2-4])[^>]*>(.*?)</h\1>", main, flags=re.S)
    sections = {}
    for i in range(1, len(parts) - 2, 3):
        heading, content = text(parts[i + 1]), text(parts[i + 2])
        if heading and content:
            sections[heading] = content
    return sections


# ── cross-check ──────────────────────────────────────────────────────────────
HEAT = re.compile(r"(?<![A-Za-z])H\.")  # "H." as a Heat marker, not the end of a stance like "WH."


def key(cmd):
    """Normalize notation so 'df+1+2', 'df12' and 'df1+2' match, Wavu's underscores match
    spaces ('Back_Throw' = 'Back Throw'), and a Heat marker counts the same wherever it
    sits: Wavu writes '4~3,H.1+2', TekkenDocs writes 'H.4~3,1+2'."""
    cmd = re.sub(r"[\s+_​]", "", cmd)
    return ("H." if HEAT.search(cmd) else "") + HEAT.sub("", cmd)


def strip_character(move_id, character):
    """'Devil_Jin-1,2' or 'Devil Jin-1,2' -> '1,2'."""
    for p in (character + "-", character.replace(" ", "_") + "-"):
        if move_id.startswith(p):
            return move_id[len(p):]
    return None


def first_int(s):
    m = re.search(r"[+-]?\d+", s or "")
    return int(m.group()) if m else None


def td_block(row):
    # TekkenDocs calls the column "Block frame"; "Block" kept in case it's ever renamed back
    return row.get("Block frame") or row.get("Block") or ""


def cross_check(wavu_moves, td_rows, character):
    # Wavu lists some moves twice (e.g. in a stance section too); same frames, so one entry each is enough
    wavu = {key(strip_character(m["id"], character) or m["input"]): m for m in wavu_moves}
    # TekkenDocs rows carry the Wavu id they were copied from - the most exact link - so try that first,
    # then the command ('f,n,d,df#2' on Wavu is 'f,n,d,df:2' on TekkenDocs, but both say Wavu id 'df#2')
    by_wavu_id = {}
    for r in td_rows:
        wid = strip_character(r.get("Wavu id", ""), character)
        if wid:
            by_wavu_id.setdefault(key(wid), r)
    by_command = {key(r.get("Command", "")): r for r in td_rows}
    pairs = {k: by_wavu_id.get(k) or by_command.get(k) for k in wavu}
    pairs = {k: r for k, r in pairs.items() if r is not None}
    differ = []
    for k in sorted(pairs):
        w, t = wavu[k], pairs[k]
        a, b = first_int(w["block"]), first_int(td_block(t))
        if a is not None and b is not None and a != b:
            differ.append({"move": w["input"], "wavu_block": w["block"], "tekkendocs_block": td_block(t)})
    used = {id(r) for r in pairs.values()}
    return {"matched": len(pairs), "block_differs": differ,
            "only_wavu": len(wavu) - len(pairs), "only_tekkendocs": sum(1 for r in td_rows if id(r) not in used)}


# ── main ─────────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        sys.exit('usage: python scripts/fetch_sources.py "Character Name"')
    character = " ".join(sys.argv[1:]).strip()
    wavu_name = character.replace(" ", "_")
    td_name = character.lower().replace(" ", "-")
    out = os.path.join(OUT_ROOT, wavu_name)
    os.makedirs(out, exist_ok=True)

    plan = [
        ("wavu_movelist", f"https://wavu.wiki/t/{wavu_name}_movelist", parse_movedata),
        ("wavu_counterplay", f"https://wavu.wiki/t/{wavu_name}_counterplay", parse_wavu_counterplay),
        ("tekkendocs", f"https://tekkendocs.com/t8/{td_name}", parse_tekkendocs),
        ("antistrat", f"https://tekkendocs.com/t8/{td_name}/antistrat", parse_antistrat),
    ]
    result, ok = {"character": character, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, True
    for i, (name, url, parser) in enumerate(plan):
        if i:
            time.sleep(PAUSE)
        entry = {"url": url}
        try:
            page = fetch(url)
            open(os.path.join(out, f"{name}.html"), "w").write(page)
            data = parser(page)
            if name == "tekkendocs":
                data, entry["parsed_from"] = data
            size = len(data["moves"]) if name == "wavu_counterplay" else len(data)
            if not size:
                raise ValueError("page downloaded but nothing parsed (layout may have changed)")
            entry["data"] = data
            if entry.get("parsed_from") == PARTIAL:
                # keep the rows, but don't pass this off as a full parse
                entry["error"] = (f"only {size} moves recovered, from the page's summary tag - "
                                  "full move data not found (layout may have changed)")
                ok = False
        except urllib.error.HTTPError as e:
            if name == "antistrat" and e.code == 404:
                # TekkenDocs links an anti-strat page for every character, but some aren't written yet
                entry["missing"] = "no anti-strat page for this character yet - use the sidestep chart for Movement"
            else:
                entry["error"] = str(e)
                ok = False
        except (urllib.error.URLError, OSError, ValueError) as e:
            entry["error"] = str(e)
            ok = False
        result[name] = entry

    if "data" in result["wavu_movelist"] and "data" in result["tekkendocs"]:
        result["cross_check"] = cross_check(result["wavu_movelist"]["data"], result["tekkendocs"]["data"], character)

    path = os.path.join(out, "sources.json")
    json.dump(result, open(path, "w"), indent=1, ensure_ascii=False)

    # summary
    print(f"{character}: wrote {path}")
    for name, *_ in plan:
        e = result[name]
        if "error" in e:
            print(f"  {name:<17} FAILED - {e['error']}  ({e['url']})")
            continue
        if "missing" in e:
            print(f"  {name:<17} not available - {e['missing']}")
            continue
        d = e["data"]
        if name == "wavu_counterplay":
            print(f"  {name:<17} {len(d['moves'])} moves in {len(d['buckets'])} buckets, {len(d['prose'])} prose sections")
        elif name == "antistrat":
            print(f"  {name:<17} {len(d)} sections: {', '.join(d)}")
        elif name == "tekkendocs":
            print(f"  {name:<17} {len(d)} moves (read from {e['parsed_from']})")
        else:
            print(f"  {name:<17} {len(d)} moves")
    if "cross_check" in result:
        c = result["cross_check"]
        partial = " (TekkenDocs data partial)" if result["tekkendocs"].get("parsed_from") == PARTIAL else ""
        print(f"  cross-check       {c['matched']} moves on both sites, {len(c['block_differs'])} block-frame disagreements{partial}")
        for d in c["block_differs"][:10]:
            print(f"      {d['move']:<16} Wavu {d['wavu_block']:<10} TekkenDocs {d['tekkendocs_block']}")
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
