"""014 research: count candidate personal values in the tracked files (HANDOFF.md excluded), by category and area.
Generic patterns only plus the account name and the user's SteamID passed on the command line; prints counts and
the distinct shapes found, never a key."""
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

root, own_sid, account = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
PAT = {
    "steamid64": re.compile(r"(?<!\d)7656119\d{10}(?!\d)"),
    "win_abs_path": re.compile(r"(?i)(?<![A-Za-z])[A-Z]:(?:\\\\|\\|/)(?:[^\s\"'`<>|*?]*)"),
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "session_link": re.compile(r"claude\.ai/(?:code/)?(?:session|chat)[_/][A-Za-z0-9_-]+"),
    "account": re.compile(re.escape(account), re.I),
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}
files = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True).stdout.decode().split("\0")
count, files_hit, shapes = Counter(), defaultdict(set), defaultdict(Counter)
for rel in filter(None, files):
    if rel == "HANDOFF.md":
        continue
    try:
        text = (root / rel).read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        continue
    top = rel.split("/")[0] if "/" in rel else "(root)"
    for cat, pat in PAT.items():
        for m in pat.finditer(text):
            v = m.group(0)
            count[cat] += 1
            files_hit[cat].add(rel)
            if cat == "steamid64":
                shapes[cat]["own" if v == own_sid else "other"] += 1
            elif cat == "win_abs_path":
                shapes[cat][re.sub(r"[\\/]+", "\\\\", v)[:28]] += 1
            elif cat == "email":
                shapes[cat][v if "noreply" in v or "example" in v else v.split("@")[1]] += 1
            else:
                shapes[cat][top] += 1
for cat in PAT:
    print(f"== {cat}: {count[cat]} hits in {len(files_hit[cat])} files")
    for shape, n in shapes[cat].most_common(14):
        print(f"   {n:4d}  {shape}")
