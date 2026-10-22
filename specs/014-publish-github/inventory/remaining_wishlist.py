"""Option C: which wishlist games still appear in the public files once wishlist_ok.json, comparisons.md and
HANDOFF.md are handled. Name matches and app-id-only matches are reported apart (an id can be an unrelated number)."""
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

root = Path(sys.argv[1])
HANDLED = {"tests/fixtures/steam/wishlist_ok.json", "docs/model/comparisons.md", "HANDOFF.md"}
data = json.loads((Path(sys.argv[2]) if len(sys.argv) > 2 else root / "extension" / "data" / "sweetspot-extension.json").read_text(encoding="utf-8"))
games = [(str(g["app_id"]), g["name"]) for g in data["games"]]

files = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True).stdout.decode("utf-8").split("\0")
by_name, by_id = defaultdict(set), defaultdict(set)
for rel in filter(None, files):
    if rel in HANDLED:
        continue
    try:
        text = (root / rel).read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        continue
    for app, name in games:
        if len(name) >= 4 and name in text:
            by_name[(app, name)].add(rel)
        elif re.search(r"(?<![0-9])" + app + r"(?![0-9])", text):
            by_id[(app, name)].add(rel)


def area(rel):
    p = rel.split("/")
    return p[0] if p[0] not in ("tests", "specs") else "/".join(p[:2])


print(f"wishlist: {len(games)} games; remaining by name: {len(by_name)}; by app id only: {len(set(by_id) - set(by_name))}")
print("=== by name (files, areas)")
for (app, name), rels in sorted(by_name.items(), key=lambda kv: -len(kv[1])):
    areas = sorted({area(r) for r in rels})
    print(f"{len(rels):3d}  {name}  [{app}]  {', '.join(areas)}")
print("=== app id only (may be a coincidence)")
for (app, name), rels in sorted(by_id.items(), key=lambda kv: -len(kv[1])):
    if (app, name) in by_name:
        continue
    print(f"{len(rels):3d}  {name}  [{app}]  {', '.join(sorted(rels))[:160]}")
none = [n for a, n in games if (a, n) not in by_name and (a, n) not in by_id]
print(f"=== not anywhere else: {len(none)}")
