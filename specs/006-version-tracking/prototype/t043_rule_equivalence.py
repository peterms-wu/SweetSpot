"""T043 (spec FR-018): the rule backtest of 2.1.0 (3.1.0) equals 2.0.0 (3.0.0) case by case, on the same dataset.

Usage: python t043_rule_equivalence.py OLD.json NEW.json
Compares every field of the two result files except the rule identity and run metadata; prints the differences.
"""
import json
import sys
from pathlib import Path

IGNORED = {"rule", "generated_at", "run_id", "seconds", "started_at", "file", "timing"}


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def diff(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for key in sorted(set(a) | set(b)):
            if key in IGNORED:
                continue
            out += diff(a.get(key), b.get(key), f"{path}.{key}")
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return [f"{path}: length {len(a)} != {len(b)}"]
        out = []
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff(x, y, f"{path}[{i}]")
        return out
    return [] if a == b else [f"{path}: {a!r} != {b!r}"]


old, new = load(sys.argv[1]), load(sys.argv[2])
print("rules:", old["rule"]["version"], "->", new["rule"]["version"], "| dataset", old["dataset"]["dataset_id"][:8],
      new["dataset"]["dataset_id"][:8], "| cases", len(old.get("cases") or []), len(new.get("cases") or []))
found = diff(old, new)
print(f"differences: {len(found)}")
for line in found[:20]:
    print("  ", line)
