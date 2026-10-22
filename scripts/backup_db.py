"""Back up the local data that git does not hold to the private GitHub repo's releases (HANDOFF §3a, 014 private backup).

The zip holds a consistent SQLite copy of data/sweetspot.db (backup API, safe while another process has it open),
sweetspot.toml and data/forecasts/ (accumulated daily, cannot be regenerated). Reports and backtests are regenerable
and left out. One release per day, tag db-YYYY-MM-DD (a rerun on the same day replaces the asset); older releases are
pruned to the newest DAILY plus the oldest one of each of the newest MONTHLY months.

The repo comes from the git remote named "private", so no repo name is written in the code.

Usage: uv run python scripts/backup_db.py [--dry-run]
Exit codes: 0 done (or skipped: no git remote named "private", feature 014), 1 failed, 4 only the files named before
feature 016 exist (run `uv run sweetspot migrate`).
"""

import argparse
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REMOTE = "private"
TAG_PREFIX = "db-"
DAILY = 14
MONTHLY = 12
_TAG = re.compile(r"^db-(\d{4})-(\d{2})-(\d{2})$")

sys.path.insert(0, str(ROOT / "src"))
from sweetspot import legacy  # noqa: E402
from sweetspot.cli import EXIT_NEEDS_MIGRATION, _utf8_when_redirected  # noqa: E402
from sweetspot.config import load_secrets  # noqa: E402
from sweetspot.logs import log_result, setup_logging  # noqa: E402


def keep_tags(tags: list[str], daily: int = DAILY, monthly: int = MONTHLY) -> set[str]:
    """Tags to keep: the newest `daily`, plus the oldest tag of each of the newest `monthly` months.
    Tags that do not look like db-YYYY-MM-DD are always kept (not ours to delete)."""
    ours = sorted(t for t in tags if _TAG.match(t))
    keep = {t for t in tags if not _TAG.match(t)}
    keep.update(ours[-daily:] if daily > 0 else [])
    first_of_month: dict[str, str] = {}
    for t in ours:
        first_of_month.setdefault(t[3:10], t)
    months = sorted(first_of_month)
    keep.update(first_of_month[m] for m in (months[-monthly:] if monthly > 0 else []))
    return keep


def repo_from_remote(url: str) -> str:
    """owner/repo from an ssh or https GitHub remote URL."""
    m = re.search(r"github\.com[:/]([^/]+)/(.+?)(?:\.git)?/?$", url.strip())
    if not m:
        raise ValueError(f"not a GitHub remote: {url}")
    return f"{m.group(1)}/{m.group(2)}"


def needs_migration(root: Path) -> str | None:
    """Feature 016: while only the old-name database or settings file exists there is nothing current to back up."""
    for f in legacy.items(root, root / "data"):
        if f.item.blocks and f.state == legacy.OLD_ONLY:
            return legacy.refusal(f.old)
    return None


def build_zip(dest: Path, root: Path | None = None) -> None:
    root = root or ROOT
    data = root / "data"
    snapshot = dest.with_suffix(".db")
    src = sqlite3.connect(f"file:{(data / 'sweetspot.db').as_posix()}?mode=ro", uri=True)
    try:
        out = sqlite3.connect(snapshot)
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(snapshot, "data/sweetspot.db")
        if (root / "sweetspot.toml").exists():
            z.write(root / "sweetspot.toml", "sweetspot.toml")
        for f in sorted((data / "forecasts").glob("*")):
            if f.is_file():
                z.write(f, f"data/forecasts/{f.name}")
    snapshot.unlink()


def gh(*args: str) -> str:
    done = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    if done.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:2])} failed: {done.stderr.strip()}")
    return done.stdout


def main(argv: list[str] | None = None) -> int:
    _utf8_when_redirected()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="build the zip and list what would be pruned, upload nothing")
    args = parser.parse_args(argv)
    blocked = needs_migration(ROOT)
    if blocked:
        print(blocked, file=sys.stderr)
        return EXIT_NEEDS_MIGRATION
    if not args.dry_run:                               # one result line in the daily log, like every sweetspot command
        setup_logging(ROOT / "data", load_secrets().redaction_values())
    started = time.monotonic()
    code, note = run(args.dry_run)
    if not args.dry_run:
        log_result("backup", code, time.monotonic() - started, note=note)
    return code


def run(dry_run: bool) -> tuple[int, str]:
    """The exit code and what happened, in the words printed (for the daily log)."""
    said: list[str] = []

    def say(line: str) -> None:
        print(line)
        said.append(line)

    try:
        remote = subprocess.run(["git", "remote", "get-url", REMOTE], capture_output=True, text=True, cwd=ROOT)
        if getattr(remote, "returncode", 0) != 0:      # 014 FR-013: only the owner's environment has the private repo
            say(f"略過雲端備份：沒有名為 {REMOTE} 的 git remote（只有原作者的環境有私人備份 repo）")
            return 0, "；".join(said)
        repo = repo_from_remote(remote.stdout)
        tag = f"{TAG_PREFIX}{datetime.now():%Y-%m-%d}"
        with tempfile.TemporaryDirectory() as tmp:
            zpath = Path(tmp) / f"sweetspot-{tag}.zip"
            build_zip(zpath)
            size_mb = zpath.stat().st_size / 1048576
            existing = gh("release", "list", "-R", repo, "--limit", "1000", "--json", "tagName", "-q", ".[].tagName").split()
            if dry_run:
                say(f"[dry-run] {zpath.name} {size_mb:.1f} MB -> {repo} {tag}")
            elif tag in existing:
                gh("release", "upload", tag, str(zpath), "-R", repo, "--clobber")
                say(f"備份已更新：{repo} {tag}（{size_mb:.1f} MB）")
            else:
                gh("release", "create", tag, str(zpath), "-R", repo, "--title", tag,
                   "--notes", "SweetSpot 本機資料備份：data/sweetspot.db、sweetspot.toml、data/forecasts/")
                say(f"備份已上傳：{repo} {tag}（{size_mb:.1f} MB）")
        tags = sorted(set(existing) | {tag})
        for old in sorted(set(tags) - keep_tags(tags)):
            if dry_run:
                say(f"[dry-run] would delete {old}")
            else:
                gh("release", "delete", old, "-R", repo, "--cleanup-tag", "--yes")
                say(f"已刪除舊備份：{old}")
    except Exception as exc:  # noqa: BLE001 - one line in the background log is the whole report
        print(f"備份失敗：{exc}", file=sys.stderr)
        return 1, "；".join([*said, f"備份失敗：{exc}"])
    return 0, "；".join(said)


if __name__ == "__main__":
    sys.exit(main())
