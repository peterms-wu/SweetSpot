"""Where do the user's current wishlist games appear in the tracked files? Counts by area; read-only."""
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

root = Path(sys.argv[1])
data = json.loads((Path(sys.argv[2]) if len(sys.argv) > 2 else root / "extension" / "data" / "sweetspot-extension.json").read_text(encoding="utf-8"))
games = [(g["app_id"], g["name"]) for g in data["games"]]
names = [n for _, n in games if len(n) >= 5]
ids = [str(a) for a, _ in games]
id_re = re.compile(r"(?<![0-9])(" + "|".join(ids) + r")(?![0-9])")

files = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True).stdout.decode("utf-8").split("\0")
area_files = defaultdict(set)
area_games = defaultdict(set)
per_file = Counter()
for rel in filter(None, files):
    p = root / rel
    try:
        text = p.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        continue
    found = {n for n in names if n in text} | {i for i in id_re.findall(text)}
    if not found:
        continue
    parts = rel.split("/")
    area = "/".join(parts[:3]) if parts[0] in ("specs", "tests") else "/".join(parts[:2]) if len(parts) > 1 else rel
    area_files[area].add(rel)
    area_games[area] |= found
    per_file[rel] = len(found)

print(f"wishlist games: {len(games)} (names >= 5 chars: {len(names)})")
print(f"files with any: {len(per_file)}")
for area in sorted(area_files, key=lambda a: -len(area_files[a])):
    print(f"{len(area_files[area]):4d} files  {len(area_games[area]):3d} games/ids  {area}")
print("--- top files")
for rel, n in per_file.most_common(15):
    print(f"{n:3d}  {rel}")
