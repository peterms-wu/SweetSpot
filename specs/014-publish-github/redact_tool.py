"""One-off rewrite for feature 014 (research R8–R10, tasks T020, T022, T023): the files to publish lose the owner's
SteamID, local folders and the NSFW example games; the near-complete wishlist fixture and the publisher catalog get
fictional content.

    uv run python specs/014-publish-github/redact_tool.py --owner-config <the owner's sweetspot.toml> [--dry-run]

Nothing personal is written in this file: the SteamID comes from --owner-config, the folders from where this
repository and the home folder are, and the NSFW replacement table from HANDOFF.md (not published). Run it in the
worktree; it prints every file it changes and how many replacements of each kind.
"""

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path, PureWindowsPath

ROOT = Path(__file__).resolve().parents[2]
SKIP = {"HANDOFF.md", "tests/fixtures/steam/wishlist_ok.json"}
CATALOG = [f"tests/fixtures/steam/search_shiravune_{s}.json" for s in (0, 50, 100)]
FAKE_STEAMID = "76561197960265728"                     # account 0 (research R8)
SEP = r"(?P<s>\\\\|\\|/)"
PROJECT_NAMES = ("SweetSpot", "SteamSage2")            # this project, before and after the 2026-09-28 rename
PREDECESSOR = "SteamSage"


def load_table(handoff: Path) -> list[tuple[str, str, str]]:
    section = handoff.read_text(encoding="utf-8").split("### 014 替換對照", 1)[1]
    rows = re.findall(r"^\| (app|package|bundle|name) \| ([^|]+?) \| ([^|]+?) \|$", section, re.M)
    if not rows:
        raise SystemExit("HANDOFF.md has no 014 replacement table")
    return rows


def path_rules(public: bool) -> list[tuple[re.Pattern, object]]:
    """Patterns for the owner's real folders, built from where they are (nothing personal spelled here)."""
    parent = PureWindowsPath(str(ROOT.resolve().parent))
    home = PureWindowsPath(str(Path.home()))
    drive = re.escape(parent.drive[0])
    parent_parts = [re.escape(p) for p in parent.parts[1:]]
    home_parts = [re.escape(p) for p in home.parts[1:]]
    hdrive = re.escape(home.drive[0])

    def joined(parts):
        return r"(?P=s)".join(parts)

    prefix = rf"(?<![A-Za-z0-9])[{drive.upper()}{drive.lower()}]:{SEP}{joined(parent_parts)}"
    home_re = re.compile(rf"(?<![A-Za-z0-9])[{hdrive.upper()}{hdrive.lower()}]:{SEP}{joined(home_parts)}(?![A-Za-z0-9])")
    if public:
        names = "|".join(PROJECT_NAMES)
        return [
            (re.compile(prefix + rf"(?P=s)(?:{names})(?P<suffix>-0\d\d)?(?![A-Za-z0-9])"),
             lambda m: "〈專案資料夾〉" + (m.group("suffix") or "")),
            (re.compile(prefix + rf"(?P=s){PREDECESSOR}(?![A-Za-z0-9])"), lambda m: "〈前身專案資料夾〉"),
            (re.compile(prefix + r"(?![A-Za-z0-9])"), lambda m: "〈專案上層資料夾〉"),
            (home_re, lambda m: "〈使用者資料夾〉"),
        ]
    return [                                            # tests need real-looking absolute paths: fictional ones
        (re.compile(prefix + r"(?![A-Za-z0-9])"), lambda m: f"D:{m.group('s')}Tools"),
        (home_re, lambda m: f"D:{m.group('s')}Home{m.group('s')}someone"),
    ]


def rewrite(text: str, public: bool, steamid: str, table, counts: Counter) -> str:
    def sub(pattern, repl, kind):
        nonlocal text
        text, n = re.subn(pattern, repl, text)
        if n:
            counts[kind] += n

    sub(rf"(?<!\d){steamid}(?!\d)", "〈SteamID〉" if public else FAKE_STEAMID, "steamid")
    for pattern, repl in path_rules(public):
        sub(pattern, repl, "path")
    for kind, real, fake in table:
        if kind == "name":
            continue
        sub(rf"(?<!\d){re.escape(real)}(?!\d)", fake, kind)
    for kind, real, fake in sorted((r for r in table if r[0] == "name"), key=lambda r: -len(r[1])):
        for a, b in ((real, fake), (real.lower(), fake.lower())):      # the report's data-name is lower case
            n = text.count(a)
            if n:
                text = text.replace(a, b)
                counts["name"] += n
    return text


def tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def rewrite_fixtures(table, dry_run: bool) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import record_fixtures as rf

    nsfw = {int(real) for kind, real, _ in table if kind == "app"}
    handoff = (ROOT / "HANDOFF.md").read_text(encoding="utf-8").split("## 014 私人紀錄", 1)[1]
    nsfw |= {int(a) for a in re.findall(r"^\| (\d+) \| [^|]+ \| [\d,]+ \|", handoff, re.M)}
    wl = ROOT / "tests/fixtures/steam/wishlist_ok.json"
    data = rf.anonymize_wishlist(json.loads(wl.read_text(encoding="utf-8")), keep=rf.WISHLIST_KEEP, nsfw=nsfw)
    print(f"tests/fixtures/steam/wishlist_ok.json: keep {len(data['response']['items'])} games, fictional order and dates")
    if not dry_run:
        wl.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    for start, rel in zip((0, 50, 100), CATALOG):
        if not (ROOT / rel).exists():                   # already rewritten and renamed by an earlier run
            continue
        page = rf.fictional_catalog(json.loads((ROOT / rel).read_text(encoding="utf-8")), offset=start)
        new = rel.replace("search_shiravune_", "search_publisher_")
        print(f"{rel} -> {new}: fictional titles and ids")
        if not dry_run:
            subprocess.run(["git", "mv", rel, new], cwd=ROOT, check=True)
            (ROOT / new).write_text(json.dumps(page, ensure_ascii=False, indent=1), encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--owner-config", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    m = re.search(r"/profiles/(\d{17})/", args.owner_config.read_text(encoding="utf-8"))
    if not m:
        raise SystemExit("no numeric wishlist url in --owner-config")
    steamid, table = m.group(1), load_table(ROOT / "HANDOFF.md")
    total = Counter()
    for rel in tracked():
        if rel in SKIP or rel in CATALOG or rel.startswith("specs/014-publish-github/"):
            continue
        path = ROOT / rel
        try:
            old = path.read_bytes().decode("utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        counts = Counter()
        # comparisons.md has the full titles; T024 turns every game name there into a code, so no partial names here
        rows = [r for r in table if r[0] != "name"] if rel == "docs/model/comparisons.md" else table
        new = rewrite(old, not rel.startswith("tests/"), steamid, rows, counts)
        if new != old:
            total.update(counts)
            print(f"{rel}: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
            if not args.dry_run:
                path.write_bytes(new.encode("utf-8"))
    rewrite_fixtures(table, args.dry_run)
    print("total: " + ", ".join(f"{k} {v}" for k, v in sorted(total.items())) + (" (dry run)" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
