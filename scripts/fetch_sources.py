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
  tekkendocs        https://tekkendocs.com/t8/<character>       frame data table (cross-check)
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
def parse_tekkendocs_table(page):
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
def key(cmd):
    """Normalize notation so 'df+1+2', 'df12' and 'df1+2' match."""
    return re.sub(r"[\s+​]", "", cmd)


def first_int(s):
    m = re.search(r"[+-]?\d+", s or "")
    return int(m.group()) if m else None


def cross_check(wavu_moves, td_rows, character):
    prefix = character.replace(" ", "_") + "-"
    wavu = {key(m["id"][len(prefix):] if m["id"].startswith(prefix) else m["input"]): m for m in wavu_moves}
    td = {key(r.get("Command", "")): r for r in td_rows}
    common = sorted(set(wavu) & set(td))
    differ = []
    for k in common:
        a, b = first_int(wavu[k]["block"]), first_int(td[k].get("Block"))
        if a is not None and b is not None and a != b:
            differ.append({"move": wavu[k]["input"], "wavu_block": wavu[k]["block"], "tekkendocs_block": td[k].get("Block")})
    return {"matched": len(common), "block_differs": differ,
            "only_wavu": len(set(wavu) - set(td)), "only_tekkendocs": len(set(td) - set(wavu))}


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
        ("tekkendocs", f"https://tekkendocs.com/t8/{td_name}", parse_tekkendocs_table),
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
            size = len(data["moves"]) if name == "wavu_counterplay" else len(data)
            if not size:
                raise ValueError("page downloaded but nothing parsed (layout may have changed)")
            entry["data"] = data
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
        else:
            print(f"  {name:<17} {len(d)} moves")
    if "cross_check" in result:
        c = result["cross_check"]
        print(f"  cross-check       {c['matched']} moves on both sites, {len(c['block_differs'])} block-frame disagreements")
        for d in c["block_differs"][:10]:
            print(f"      {d['move']:<16} Wavu {d['wavu_block']:<10} TekkenDocs {d['tekkendocs_block']}")
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
