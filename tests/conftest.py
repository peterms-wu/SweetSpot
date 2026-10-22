from pathlib import Path

import pytest

from sweetspot import config

FIXTURES = Path(__file__).parent / "fixtures"
SECRET_NAMES = ("ITAD_API_KEY", "STEAM_WEB_API_KEY")


@pytest.fixture(autouse=True)
def no_real_secrets(monkeypatch):
    """No test sees this machine's API keys: not from the environment, not from HKCU\\Environment.
    A test that needs a key sets a fake one with monkeypatch.setenv or passes registry_reader."""
    for name in SECRET_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config, "_read_user_registry", lambda name: None)


class _EmptyRegistry:
    def get_default(self, key):
        return None

    def set_default(self, key, value):
        raise AssertionError("a test reached the default registry of sweetspot migrate")

    def delete(self, key):
        raise AssertionError("a test reached the default registry of sweetspot migrate")


class _NoTasks:
    def query(self, name):
        return None


@pytest.fixture(autouse=True)
def no_real_scheduler_or_registry(monkeypatch):
    """Feature 016: `sweetspot migrate` never reaches this machine's Task Scheduler or HKCU registry in a test. A test
    that needs them passes fakes (tests/integration/test_migrate.py) or patches default_registry/default_scheduler."""
    from sweetspot import migrate, schedule

    def forbidden(args):
        raise AssertionError("a test reached the real PowerShell")

    monkeypatch.setattr(migrate, "powershell_runner", forbidden)
    monkeypatch.setattr(schedule, "powershell_runner", forbidden)     # 014: the PowerShell access lives here now
    monkeypatch.setattr(migrate, "default_registry", lambda: _EmptyRegistry())
    monkeypatch.setattr(migrate, "default_scheduler", lambda: _NoTasks())
    monkeypatch.setattr(schedule, "default_scheduler", lambda: _NoTasks())


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Path to a fresh, not-yet-created database file."""
    return tmp_path / "data" / "sweetspot.db"


PARTNER = FIXTURES / "partner"


def partner_page(name: str = "seasonalsales-2026-09-27.html", *, edit: tuple[str, str] | None = None) -> str:
    """A trimmed copy of the official seasonal sales page (feature 012); `edit` is one (old, new) replacement."""
    text = (PARTNER / name).read_text(encoding="utf-8")
    if edit is not None:
        old, new = edit
        assert old in text, old
        text = text.replace(old, new)
    return text


def write_calendar(data_dir: Path, text: str) -> Path:
    """Write a test sale calendar to data_dir/steam_sales.toml."""
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / "steam_sales.toml"
    path.write_text(text, encoding="utf-8")
    return path
