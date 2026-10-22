r"""016 T002: one-off rewrite of 'steamsage' -> 'sweetspot' in tracked files (research R1, contracts/names.md).

Run once from the repository root after `git mv src/steamsage src/sweetspot`:

    python specs/016-rename-internal-ids/rename_tool.py --dry-run   # report only
    python specs/016-rename-internal-ids/rename_tool.py             # write

Order per line: protect -> replace -> restore. Protected:
  - the three kept data identifiers (contracts/names.md section 2);
  - the predecessor project SteamSage (exact case, not followed by 2) on a line that says so, or as a path segment
    (followed by \ or / and a letter; the regex escape `SteamSage\.` in a test is not a path);
  - whole lines that explain the old name ("舊名" / "formerly"), listed for review (016 T004);
  - any SteamSage2 left after the task-name replacement, listed for manual editing.
Files are read and written as bytes decoded as UTF-8, so line endings stay as they are. This script lives under specs/,
which the rewrite and the scan both leave alone.
"""

import argparse
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

EXCLUDED_PREFIXES = ("specs/", ".specify/")
EXCLUDED_FILES = {"HANDOFF.md", "docs/model/comparisons.md", ".gitignore", "uv.lock"}

KEPT = [
    ("format", re.compile(r"steamsage\.[a-z][a-z-]*/\d+")),
    ("split-salt", re.compile(r"steamsage-004-split")),
    ("record-field", re.compile(r"steamsage_version")),
]
PREDECESSOR = re.compile(r"SteamSage(?![0-9A-Za-z])")
PREDECESSOR_PATH = re.compile(r"[\\/]{1,2}[A-Za-z]")   # 〈前身專案資料夾〉\state, not a regex escape like SteamSage\.
PREDECESSOR_LINE = re.compile(r"前身|舊專案|legacy", re.I)
OLD_NAME_LINE = re.compile(r"舊名|formerly", re.I)
OLD_NAME_2 = re.compile(r"SteamSage2")

REPLACEMENTS = [
    ("SteamSage2 每日背景更新", "SweetSpot 每日背景更新"),
    ("steamsageRefresh", "sweetspotRefresh"),
    ("SteamSage", "SweetSpot"),
    ("steamsage", "sweetspot"),
]
ANY = re.compile(r"steamsage", re.I)


def tracked_files(root: Path) -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def in_scope(path: str) -> bool:
    return not path.startswith(EXCLUDED_PREFIXES) and path not in EXCLUDED_FILES


def rewrite_line(line: str, stats: Counter, notes: list[str], where: str) -> str:
    if not ANY.search(line):
        return line
    if OLD_NAME_LINE.search(line):
        stats["protected:old-name-line"] += 1
        notes.append(f"whole line kept (old-name line): {where}: {line.strip()}")
        return line
    held: list[str] = []

    def hold(kind: str):
        def repl(m: re.Match) -> str:
            held.append(m.group(0))
            stats[f"protected:{kind}"] += 1
            return f"\0{len(held) - 1}\0"
        return repl

    for kind, pattern in KEPT:
        line = pattern.sub(hold(kind), line)
    predecessor_line = bool(PREDECESSOR_LINE.search(line))

    def predecessor(m: re.Match) -> str:
        if predecessor_line or PREDECESSOR_PATH.match(m.string, m.end()):
            return hold("predecessor")(m)
        return m.group(0)

    line = PREDECESSOR.sub(predecessor, line)
    for old, new in REPLACEMENTS[:1]:
        stats["replaced"] += line.count(old)
        line = line.replace(old, new)

    def manual(m: re.Match) -> str:
        notes.append(f"SteamSage2 left for manual editing: {where}: {m.string.strip()}")
        return hold("manual-SteamSage2")(m)

    line = OLD_NAME_2.sub(manual, line)
    for old, new in REPLACEMENTS[1:]:
        stats["replaced"] += line.count(old)
        line = line.replace(old, new)
    return re.sub(r"\0(\d+)\0", lambda m: held[int(m.group(1))], line)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    total, notes, changed = Counter(), [], 0
    for rel in tracked_files(args.root):
        if not in_scope(rel):
            continue
        path = args.root / rel
        try:
            text = path.read_bytes().decode("utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        if not ANY.search(text):
            continue
        stats = Counter()
        lines = text.splitlines(keepends=True)
        new = "".join(rewrite_line(line, stats, notes, f"{rel}:{n}") for n, line in enumerate(lines, 1))
        total.update(stats)
        if new != text:
            changed += 1
            print(f"{rel}: " + ", ".join(f"{k}={v}" for k, v in sorted(stats.items())))
            if not args.dry_run:
                path.write_bytes(new.encode("utf-8"))
    print("--- files changed:", changed, "(dry run)" if args.dry_run else "")
    print("--- totals:", dict(sorted(total.items())))
    for note in notes:
        print("NOTE", note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
