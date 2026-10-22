"""P2: run the P1 parser on every distinct Wayback snapshot of the official page (2024-03 .. 2026-08).

Checks (a) the format stayed parseable, (b) every listed sale matches data/steam_sales.toml (the file's dates come
from other official posts, so this is an independent check of the parser and of "second date = end day"),
(c) how far ahead each sale first appeared, and (d) whether Valve ever changed a listed date.
Research only: the feature itself never reads archive.org. Snapshots are cached in out/wayback/ (3 s between downloads).

Usage: uv run python specs/012-sale-calendar-sync/prototype/p2_wayback.py
"""

import gzip
import json
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from steamsage import calendar

from p1_parse import ROOT, SOURCE, compare, parse, to_utc

HERE = Path(__file__).parent
CACHE = HERE / "out" / "wayback"
CDX = ("https://web.archive.org/cdx/search/cdx?url=partner.steamgames.com/doc/marketing/discounts/seasonalsales"
       "&output=json&fl=timestamp,statuscode,digest&filter=statuscode:200&collapse=digest")
UA = {"User-Agent": "SteamSage2 prototype (personal, local)"}


def get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read()


def snapshots() -> list[str]:
    CACHE.mkdir(parents=True, exist_ok=True)
    index = CACHE / "cdx.json"
    if not index.exists():
        index.write_bytes(get(CDX))
    rows = json.loads(index.read_text())[1:]
    out = []
    for ts, _, _ in rows:
        path = CACHE / f"{ts}.html"
        if not path.exists():
            path.write_bytes(get(f"https://web.archive.org/web/{ts}id_/{SOURCE}"))
            time.sleep(3)
        out.append(ts)
    return out


def main() -> None:
    now = datetime.now(UTC)
    events = calendar.load_calendar(ROOT / "data" / "steam_sales.toml", now=now)
    first_seen: dict = {}
    dates_seen: dict = {}
    problems = total_tbd = 0
    print(f"{'snapshot':<16} sec parsed tbd rej same new conflict  listed")
    for ts in snapshots():
        raw = (CACHE / f"{ts}.html").read_bytes()
        page = (gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw).decode("utf-8", errors="replace")
        at = datetime.strptime(ts, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
        parsed, rejected, found = parse(page)
        tbd = [r for r in rejected if r.reason == "tbd"]
        rejected = [r for r in rejected if r.reason != "tbd"]
        total_tbd += len(tbd)
        diff = compare(parsed, events, at)
        listed = " ".join(f"{p.year % 100}{p.season[:2]}" for p in parsed)
        print(f"{ts:<16} {'y' if found else 'N':>3} {len(parsed):>6} {len(tbd):>3} {len(rejected):>3} {len(diff['same']):>4} "
              f"{len(diff['new']):>3} {len(diff['conflict']):>8}  {listed}")
        for r in rejected:
            print(f"    rejected: {r.reason}: {r.line[:100]}")
        for p, e in diff["conflict"]:
            print(f"    conflict {p.year} {p.season}: page {p.start}..{p.end} vs toml "
                  f"{e.start:%Y-%m-%d}..{e.end:%Y-%m-%d}")
        for p in diff["new"]:
            print(f"    not in toml: {p.year} {p.season} {p.start}..{p.end}")
        problems += len(rejected) + len(diff["conflict"]) + len(diff["new"]) + (not found) + (found and not parsed)
        for p in parsed:
            key = (p.year, p.season)
            first_seen.setdefault(key, at)
            dates_seen.setdefault(key, set()).add((p.start, p.end))
    print(f"\nproblems (rejected + conflict + not-in-toml + no section/no dates): {problems}; TBD lines: {total_tbd}")
    changed = {k: v for k, v in dates_seen.items() if len(v) > 1}
    print(f"sales whose listed dates changed between snapshots: {len(changed)}")
    for k, v in changed.items():
        print(f"    {k}: {sorted(v)}")
    print("\nfirst seen in a snapshot (upper bound of the announcement time) -> sale start, lead days:")
    for key, at in sorted(first_seen.items(), key=lambda kv: to_utc(min(d[0] for d in dates_seen[kv[0]]))):
        start = to_utc(min(d[0] for d in dates_seen[key]))
        print(f"    {key[0]} {key[1]:<7} first seen {at:%Y-%m-%d}  start {start:%Y-%m-%d}  lead {(start - at).days:>4} d")


if __name__ == "__main__":
    main()
