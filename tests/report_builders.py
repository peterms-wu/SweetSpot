"""Running `sweetspot report` in tests the way the user runs it by hand: no keys, no browser, the JSON summary back.
Shared by tests/integration/test_report_flow.py and the feature 015 host tests (tests/host_builders.py)."""

import io
import json
from pathlib import Path

from sweetspot import cli, commands

# Three 50% sales around the BASIC_CALENDAR seasons, the last one ending 2025-07-10.
HISTORY = [("2024-12-11", 0), ("2024-12-19T18:00", 50), ("2025-01-02T18:00", 0), ("2025-03-13T17:00", 50),
           ("2025-03-20T17:00", 0), ("2025-06-26T17:00", 50), ("2025-07-10T17:00", 0)]


def quiet_cli(monkeypatch) -> None:
    """No keys from this machine and no report opened in a browser."""
    monkeypatch.setattr(cli, "load_secrets", lambda: cli.Secrets())
    monkeypatch.setattr(commands, "OPEN_FILE", lambda path: None)


def run_report(config: Path, *extra: str) -> tuple[int, dict | None]:
    """`sweetspot report --json` on this config: the exit code and the summary."""
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(["report", "--json", "--config", str(config), *extra], stdout=out, stderr=err)
    return code, json.loads(out.getvalue()) if out.getvalue() else None
