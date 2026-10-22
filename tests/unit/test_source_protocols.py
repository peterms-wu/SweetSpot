"""FR-010: pipelines depend on source Protocols, not on concrete clients."""

import ast
from pathlib import Path

from sweetspot import sources

PIPELINE_DIR = Path(__file__).parents[2] / "src" / "sweetspot" / "pipeline"
CONCRETE = {"sweetspot.sources.itad", "sweetspot.sources.steam_store", "sweetspot.sources.steam_webapi",
            "sweetspot.sources.http", "sweetspot.sources.steam_partner"}


class FakeWishlist:
    def get_wishlist(self, steamid):
        return [sources.WishlistEntry(620, 1, None)]


class FakeHistory:
    def lookup_steam(self, app_ids):
        return {}

    def reverse_lookup(self, external_ids):
        return {}

    def history(self, external_id, country, since):
        return []

    def current_prices(self, external_ids, country):
        return {}


def test_fake_sources_satisfy_protocols():
    assert isinstance(FakeWishlist(), sources.WishlistSource)
    assert isinstance(FakeHistory(), sources.HistorySource)
    assert not isinstance(FakeWishlist(), sources.HistorySource)


def test_partner_docs_satisfy_protocol():
    from sweetspot.sources.http import RateLimitedClient
    from sweetspot.sources.steam_partner import SteamPartnerDocs

    http = RateLimitedClient("steam-partner", min_interval=0)
    try:
        assert isinstance(SteamPartnerDocs(http), sources.SeasonalSalesSource)
    finally:
        http.close()


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def test_pipeline_modules_do_not_import_concrete_clients():
    offenders = {
        path.name: sorted(_imported_modules(path) & CONCRETE)
        for path in PIPELINE_DIR.glob("*.py")
        if _imported_modules(path) & CONCRETE
    }
    assert offenders == {}
