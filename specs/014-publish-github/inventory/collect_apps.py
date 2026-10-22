"""App ids that appear in the tracked test files (tests/**) and in all public files, with a name where known.
Sources: JSON keys appid/app_id/id-with-kind-app in fixtures, plus the user's wishlist names/ids anywhere. Read-only."""
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
wish = json.loads((Path(sys.argv[3]) if len(sys.argv) > 3 else root / "extension" / "data" / "sweetspot-extension.json").read_text(encoding="utf-8"))
names = {str(g["app_id"]): g["name"] for g in wish["games"]}
KEY = re.compile(r'"(?:appid|app_id|steam_appid)"\s*:\s*"?(\d{2,8})')
PY = re.compile(r"(?:app_id|appid|app)\s*=\s*(\d{3,8})")
URL = re.compile(r"store\.steampowered\.com/app/(\d{2,8})")

files = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True).stdout.decode("utf-8").split("\0")
where = defaultdict(set)
for rel in filter(None, files):
    if rel == "HANDOFF.md":
        continue
    try:
        text = (root / rel).read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        continue
    found = set(KEY.findall(text)) | set(URL.findall(text))
    if rel.startswith("tests/"):
        found |= set(PY.findall(text))
    for app, name in names.items():
        if (len(name) >= 4 and name in text) or re.search(r"(?<![0-9])" + app + r"(?![0-9])", text):
            found.add(app)
    for app in found:
        where[app].add(rel)

tests = {a for a, rels in where.items() if any(r.startswith("tests/") for r in rels)}
print(f"apps in public files: {len(where)}; in tests/: {len(tests)}; of them on the wishlist: {len(tests & set(names))}")
out.write_text(json.dumps({a: sorted(r) for a, r in where.items()}, ensure_ascii=False, indent=1), encoding="utf-8")
