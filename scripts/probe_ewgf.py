"""
One-time probe of the ewgf.gg battles API.

Goal: learn what fields a battle record has WITHOUT saving anyone's identity.
It writes data/ewgf-schema.json containing only:
  - each field's name and type
  - for low-variety fields (characters, stages, ranks, results...): the
    distinct values seen
  - for high-variety fields (player names, IDs, timestamps): just a count,
    never the values

Run by .github/workflows/probe-ewgf.yml. Needs the EWGF_API_KEY secret.
"""

import gzip
import json
import os
import sys
import urllib.error
import urllib.request

TEKKEN_ID = "4bN6AEeddYT6"          # Mike's Tekken ID (public, from his ewgf URL)
URL = f"https://api.ewgf.gg/external/battles/{TEKKEN_ID}"
OUT = "data/ewgf-schema.json"

# A field with at most this many distinct values is treated as a category
# (character, stage, rank, result) and its values are shown. Anything with
# more distinct values is treated as an identifier and only counted.
MAX_CATEGORY_VALUES = 45

# Field names that are never shown, however few distinct values they have.
# Matched as substrings, case-insensitive.
NEVER_SHOW = ("name", "polaris", "tekken_id", "tekkenid", "user", "player_id", "playerid",
              "platform", "region", "lang", "msg", "message", "comment")


def fetch():
    key = os.environ.get("EWGF_API_KEY")
    if not key:
        sys.exit("EWGF_API_KEY secret is missing.")
    req = urllib.request.Request(URL, headers={
        "Authorization": f"Bearer {key}",
        "Accept-Encoding": "gzip",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        # The error body holds a stable code like "invalid_api_key" - safe to show.
        body = e.read()
        try:
            body = gzip.decompress(body)
        except OSError:
            pass
        sys.exit(f"API error {e.code}: {body.decode(errors='replace')[:500]}")


def flatten(obj, prefix=""):
    """Turn nested dicts into dotted keys: {"a": {"b": 1}} -> {"a.b": 1}."""
    out = {}
    for k, v in obj.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flatten(v, key + "."))
        else:
            out[key] = v
    return out


def describe(battles):
    fields = {}
    for b in battles:
        for key, value in flatten(b).items():
            f = fields.setdefault(key, {"types": set(), "values": set()})
            f["types"].add(type(value).__name__)
            f["values"].add(json.dumps(value, sort_keys=True))

    schema = {}
    for key in sorted(fields):
        f = fields[key]
        entry = {"type": sorted(f["types"]), "distinct_values": len(f["values"])}
        hidden = any(word in key.lower() for word in NEVER_SHOW)
        if not hidden and len(f["values"]) <= MAX_CATEGORY_VALUES:
            entry["values"] = sorted(json.loads(v) for v in f["values"]) \
                if all(t in ("int", "float", "str", "bool") for t in f["types"]) \
                else "complex - not shown"
        else:
            entry["values"] = "hidden (identifier or high-variety field)"
        schema[key] = entry
    return schema


def main():
    payload = fetch()
    data = payload.get("data", payload)
    battles = data if isinstance(data, list) else data.get("battles", [])
    report = {
        "endpoint": "/external/battles/{tekkenId}",
        "top_level_keys": sorted(payload.keys()) if isinstance(payload, dict) else type(payload).__name__,
        "metadata": payload.get("_metadata") if isinstance(payload, dict) else None,
        "battle_count": len(battles),
        "fields": describe(battles) if battles else {},
    }
    os.makedirs("data", exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(report, fh, indent=2, default=str)
    print(f"Saved field summary for {len(battles)} battles to {OUT}")


if __name__ == "__main__":
    main()
