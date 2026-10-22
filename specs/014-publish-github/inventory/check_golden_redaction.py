"""014 T026 (read-only): each regenerated golden report page equals the page before the 014 rewrite with the same
replacements applied (redact_tool.rewrite, test-side rules), so the rewrite changed names and ids and nothing else.

    uv run python specs/014-publish-github/inventory/check_golden_redaction.py --owner-config <sweetspot.toml> [--rev HEAD]
"""

import argparse
import importlib.util
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location("redact_tool", ROOT / "specs" / "014-publish-github" / "redact_tool.py")
redact = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(redact)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--owner-config", type=Path, required=True)
    parser.add_argument("--rev", default="HEAD", help="the commit before the rewrite")
    args = parser.parse_args()
    steamid = re.search(r"/profiles/(\d{17})/", args.owner_config.read_text(encoding="utf-8")).group(1)
    table = redact.load_table(ROOT / "HANDOFF.md")
    bad = 0
    for path in sorted((ROOT / "tests" / "fixtures" / "report").glob("golden_*.html")):
        rel = path.relative_to(ROOT).as_posix()
        old = subprocess.run(["git", "show", f"{args.rev}:{rel}"], cwd=ROOT, capture_output=True, check=True).stdout
        counts = Counter()
        expected = redact.rewrite(old.decode("utf-8").replace("\r\n", "\n"), False, steamid, table, counts)
        now = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
        same = expected == now
        bad += not same
        print(f"{path.name}: replacements {dict(counts) or 0}; identical to the rewritten old page: {same}")
    return 1 if bad else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
