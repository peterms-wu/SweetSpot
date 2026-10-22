"""Feature 015 test environment: a config file, a database whose wishlist game has editions, and the extension
folder next to the config (the report only writes the extension data file when extension/manifest.json exists;
analyze U2). Nothing here touches the real sweetspot.toml, database or registry."""

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from sweetspot import commands
from tests.config_builders import TEST_TOML
from tests.forecast_builders import BASIC_CALENDAR, GameSpec, add_history, add_purchase_options, add_version, build_db, dt
from tests.report_builders import HISTORY, quiet_cli

ROOT = Path(__file__).resolve().parents[1]
NOW = "2025-07-31T12:00"
CHECKED = "2025-07-31"
APP, OTHER, GONE = 1, 2, 3                    # a wishlist game with editions, one without, one not in the wishlist
DEFAULT = ("sub", 100)                        # APP's Steam default
EDITION = ("bundle", 900)                     # verified edition: choosable
REJECTED = ("sub", 902)                       # edition whose ITAD check failed
SOUNDTRACK = ("bundle", 901)                  # not an edition (role other-games)
NAMES = {DEFAULT: "Cyber", EDITION: "《Cyber：終極版》", REJECTED: "Cyber Broken", SOUNDTRACK: "Cyber + Soundtrack"}


@dataclass
class Env:
    root: Path
    config: Path
    data: Path
    db: Path

    @property
    def report(self) -> Path:
        return self.data / "reports" / "latest.html"

    @property
    def ext_data(self) -> Path:
        return self.root / "extension" / "data" / "sweetspot-extension.json"

    @property
    def forecasts(self) -> Path:
        return self.data / "forecasts"

    def records(self) -> list[str]:
        return sorted(p.name for p in self.forecasts.glob("*.json.gz")) if self.forecasts.is_dir() else []

    def toml(self) -> bytes:
        return self.config.read_bytes()

    def extension_game(self, app: int = APP) -> dict:
        data = json.loads(self.ext_data.read_text(encoding="utf-8"))
        return next(g for g in data["games"] if g["app_id"] == app)

    def snapshot(self) -> dict[str, str | None]:
        """A hash of every file a request may touch (spec SC-002, SC-004)."""
        files = [self.config, self.db, self.report, self.ext_data, *sorted(self.forecasts.glob("*"))] \
            if self.forecasts.is_dir() else [self.config, self.db, self.report, self.ext_data]
        return {str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
                for p in files}


def make_env(root: Path, monkeypatch, *, toml: str = TEST_TOML, now: str = NOW) -> Env:
    quiet_cli(monkeypatch)
    monkeypatch.setattr(commands, "NOW", lambda: dt(now))
    config = root / "sweetspot.toml"
    config.write_bytes(toml.encode("utf-8"))
    (root / "extension").mkdir()
    shutil.copy(ROOT / "extension" / "manifest.json", root / "extension" / "manifest.json")
    db = build_db(root / "data" / "sweetspot.db",
                  [GameSpec(APP, tw=HISTORY, name="Cyber", wishlist=True),
                   GameSpec(OTHER, tw=HISTORY, name="Other", wishlist=True),
                   GameSpec(GONE, tw=HISTORY, name="Gone", wishlist=False)], calendar=BASIC_CALENDAR)
    add_version(db, APP, CHECKED, external_id=f"itad-{APP}", package_id=DEFAULT[1], package_name=NAMES[DEFAULT])
    add_version(db, OTHER, CHECKED, external_id=f"itad-{OTHER}", package_id=200, package_name="Other")
    add_purchase_options(db, APP, CHECKED, [
        dict(kind=DEFAULT[0], option_id=DEFAULT[1], name=NAMES[DEFAULT], original_cents=50000, final_cents=25000,
             role="default"),
        dict(kind=EDITION[0], option_id=EDITION[1], name=NAMES[EDITION], original_cents=80000, final_cents=40000,
             role="edition", external_id="itad-900", verification="verified", verified_by="version-check",
             verified_at=CHECKED),
        dict(kind=SOUNDTRACK[0], option_id=SOUNDTRACK[1], name=NAMES[SOUNDTRACK], original_cents=90000,
             final_cents=90000, role="other-games"),
        dict(kind=REJECTED[0], option_id=REJECTED[1], name=NAMES[REJECTED], original_cents=60000, final_cents=60000,
             role="edition", external_id="itad-902", verification="rejected", verified_by="version-check",
             verified_at=CHECKED, reason_code="bundle", reason_detail="bundle/5"),
    ])
    add_purchase_options(db, OTHER, CHECKED, [
        dict(kind="sub", option_id=200, name="Other", original_cents=50000, final_cents=50000, role="default")])
    add_history(db, APP, "itad-900", tw=[("2024-12-11", 0, 80000), ("2025-06-26T17:00", 50, 80000),
                                         ("2025-07-10T17:00", 0, 80000)],
                regular_cents=80000, fetched=CHECKED, source="itad-option-history", fetch_source="itad-option")
    return Env(root, config, root / "data", db)
