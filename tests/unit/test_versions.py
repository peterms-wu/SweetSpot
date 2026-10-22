"""feature 006: the daily version step (spec FR-001–FR-006, FR-011; research R1, R2; data-model §1)."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from sweetspot.pipeline import versions
from sweetspot.pipeline.mapping import Mapping
from sweetspot.sources import AppKind, ItadPrice, PriceLookup, PriceQuote, PurchaseOption, VersionPackage
from sweetspot.sources.errors import SourceError
from sweetspot.store.writer import StoreWriter

NOW = datetime(2026, 9, 27, 1, 0, tzinfo=UTC)
DAY = timedelta(days=1)
MAX_AGE = timedelta(days=7)

DYING, OWN_DL, ESSENTIALS_ID = 239140, "itad-dl-old", "itad-essentials"
PORTAL, OWN_PORTAL = 620, "itad-portal"


def quote(original, final):
    return PriceQuote("TWD", original, final, 0 if original == final else round(100 - 100 * final / original))


class FakeSteam:
    def __init__(self):
        self.options = {
            DYING: [PurchaseOption(1345940, None, "Dying Light Essentials Edition", 67000, 13400),
                    PurchaseOption(1265945, None, "Dying Light: Definitive 10th Anniversary Edition", 74900, 14900),
                    PurchaseOption(None, 49425, "Dying Light Collection", 256500, 51300)],
            PORTAL: [PurchaseOption(7877, None, "Portal 2", 18800, 18800)],
        }
        self.packages = {1345940: VersionPackage(1345940, True, [DYING, 302101], "Dying Light Essentials Edition"),
                         7877: VersionPackage(7877, True, [PORTAL], "Portal 2")}
        self.kinds = {302101: AppKind(302101, 4, DYING)}
        self.calls = []
        self.fail = False

    def purchase_options(self, app_ids):
        self.calls.append(("options", sorted(app_ids)))
        if self.fail:
            raise SourceError("steam-webapi: GetItems (purchase options) HTTP 500")
        return {a: self.options[a] for a in app_ids if a in self.options}

    def version_packages(self, package_ids):
        self.calls.append(("packages", sorted(package_ids)))
        return {p: self.packages[p] for p in package_ids if p in self.packages}

    def app_kinds(self, app_ids):
        self.calls.append(("kinds", sorted(app_ids)))
        return {a: self.kinds[a] for a in app_ids if a in self.kinds}


class FakeItad:
    def __init__(self):
        self.subs = {1345940: ESSENTIALS_ID, 7877: OWN_PORTAL}
        self.aliases = {ESSENTIALS_ID: ["sub/1345941", "sub/1345940"], OWN_PORTAL: ["app/620", "sub/7877"]}
        self.deals = {ESSENTIALS_ID: 1, OWN_PORTAL: 1, OWN_DL: 0}
        self.calls = []

    def lookup_packages(self, package_ids):
        self.calls.append(("lookup", sorted(package_ids)))
        return {p: self.subs.get(p) for p in package_ids}

    def reverse_lookup(self, external_ids):
        self.calls.append(("aliases", sorted(external_ids)))
        return {e: self.aliases.get(e, []) for e in external_ids}

    def price_summaries(self, external_ids, country):
        self.calls.append(("prices", sorted(external_ids)))
        return {e: ItadPrice(None, self.deals.get(e, 0)) for e in external_ids}


class NoMetadata:
    def canonical_app_id(self, app_id):
        return None


@pytest.fixture
def writer(db_path):
    w = StoreWriter.open(db_path)
    run = w.start_run("daily")
    for app, name in ((DYING, "Dying Light"), (PORTAL, "Portal 2")):
        w.ensure_product(app, "wishlist", NOW - 10 * DAY)
        w.add_facts(run, app, {"name": name}, source="steam-appdetails", retrieved_at=NOW - 10 * DAY)
    w.add_mapping(run, DYING, "itad", OWN_DL, "verified", checked_at=NOW - 3 * DAY)
    w.add_mapping(run, PORTAL, "itad", OWN_PORTAL, "verified", checked_at=NOW - 2 * DAY)
    yield w
    w.close()


def own(*apps):
    table = {DYING: Mapping(DYING, OWN_DL, "verified", None, True), PORTAL: Mapping(PORTAL, OWN_PORTAL, "verified", None, True)}
    return {a: table[a] for a in apps}


LOOKUPS = {DYING: PriceLookup(DYING, True, quote(67000, 13400)), PORTAL: PriceLookup(PORTAL, True, quote(18800, 18800))}


def resolve(writer, steam, itad, apps=(DYING, PORTAL), lookups=None, now=NOW):
    run = writer.start_run("daily")
    return versions.resolve_versions(writer, steam, itad, NoMetadata(), list(apps), lookups or LOOKUPS, own(*apps),
                                     run_id=run, now=now, max_age=MAX_AGE, region="TW")


def rows(writer, app):
    cur = writer.conn.execute("SELECT * FROM app_versions WHERE app_id = ? ORDER BY checked_at", (app,))
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def test_default_option_is_the_package_priced_like_the_store(writer):
    result = resolve(writer, FakeSteam(), FakeItad())
    dl = result.versions[DYING]
    assert (dl.status, dl.package_id, dl.package_name, dl.external_id) == (
        "ok", 1345940, "Dying Light Essentials Edition", ESSENTIALS_ID)
    [row] = rows(writer, DYING)
    assert (row["regular_cents"], row["price_cents"], row["itad_steam_deals"]) == (67000, 13400, 1)
    assert json.loads(row["aliases_json"]) == ["sub/1345941", "sub/1345940"]


@pytest.mark.parametrize("options,status", [
    ([PurchaseOption(1, None, "a", 67000, 13400), PurchaseOption(2, None, "b", 67000, 13400)], "ambiguous"),
    ([PurchaseOption(1, None, "a", 70000, 13400)], "ambiguous"),
    ([PurchaseOption(None, 9, "bundle", 67000, 13400)], "ambiguous"),        # bundles are never the default
])
def test_no_single_match_is_ambiguous(writer, options, status):
    steam = FakeSteam()
    steam.options[DYING] = options
    result = resolve(writer, steam, FakeItad(), apps=(DYING,))
    assert result.versions[DYING].status == status
    assert result.versions[DYING].history_id == OWN_DL           # falls back to the app's own product (FR-011)
    assert rows(writer, DYING)[0]["package_id"] is None


def test_no_price_is_no_option(writer):
    lookups = {**LOOKUPS, DYING: PriceLookup(DYING, True, None)}
    result = resolve(writer, FakeSteam(), FakeItad(), apps=(DYING,), lookups=lookups)
    assert result.versions[DYING].status == "no-option" and result.summary["no_option"] == 1


def test_package_unknown_to_itad_is_not_in_itad(writer):
    itad = FakeItad()
    del itad.subs[1345940]
    result = resolve(writer, FakeSteam(), itad, apps=(DYING,))
    assert result.versions[DYING].status == "not-in-itad"
    assert result.summary["fallback_own"] == {"ambiguous": 0, "not-in-itad": 1}


def test_same_product_as_own_mapping_is_reused_without_requests(writer):
    steam, itad = FakeSteam(), FakeItad()
    resolve(writer, steam, itad, apps=(PORTAL,))
    assert not any(c[0] in ("packages", "kinds") for c in steam.calls)
    assert not any(c[0] == "aliases" for c in itad.calls)
    [row] = rows(writer, PORTAL)
    assert (row["verification"], row["verified_by"], row["verified_at"]) == (
        "verified", "own-mapping", "2026-09-25T01:00:00.000000Z")      # the 001 mapping's check time (principle II)


def test_different_product_is_verified_then_cached_then_rechecked(writer):
    steam, itad = FakeSteam(), FakeItad()
    first = resolve(writer, steam, itad, apps=(DYING,))
    assert first.versions[DYING].verification == "verified"
    assert rows(writer, DYING)[0]["verified_by"] == "version-check"
    assert first.summary["changed"] == [{"app_id": DYING, "name": "Dying Light", "from": "Dying Light",
                                         "to": "Dying Light Essentials Edition"}]
    steam.calls.clear()
    second = resolve(writer, steam, itad, apps=(DYING,), now=NOW + DAY)
    row = rows(writer, DYING)[1]
    assert (row["verified_by"], row["verified_at"]) == ("cached", "2026-09-27T01:00:00.000000Z")
    assert not any(c[0] == "packages" for c in steam.calls) and second.summary["changed"] == []
    resolve(writer, steam, itad, apps=(DYING,), now=NOW + 8 * DAY)
    assert rows(writer, DYING)[2]["verified_by"] == "version-check"   # older than mapping_days


def test_a_new_product_is_verified_at_once(writer):
    steam, itad = FakeSteam(), FakeItad()
    resolve(writer, steam, itad, apps=(DYING,))
    itad.subs[1345940] = "itad-other"
    itad.aliases["itad-other"] = ["sub/1345940"]
    result = resolve(writer, steam, itad, apps=(DYING,), now=NOW + DAY)
    assert rows(writer, DYING)[1]["verified_by"] == "version-check"        # FR-004: not the cache
    assert result.summary["changed"][0]["from"] == "Dying Light Essentials Edition"


def test_rejected_version_has_no_history_and_is_listed(writer):
    itad = FakeItad()
    itad.aliases[ESSENTIALS_ID] = ["sub/1345940", "bundle/99003"]
    result = resolve(writer, FakeSteam(), itad, apps=(DYING,))
    dl = result.versions[DYING]
    assert (dl.verification, dl.reason_code, dl.reason_detail, dl.history_id) == (
        "rejected", "bundle", "bundle/99003", None)
    assert result.summary["rejected"] == [{"app_id": DYING, "name": "Dying Light", "reason": "bundle",
                                           "detail": "bundle/99003"}]


def test_itad_without_a_steam_price_is_listed_as_stopped(writer):
    itad = FakeItad()
    itad.deals[OWN_PORTAL] = 0
    result = resolve(writer, FakeSteam(), itad, apps=(PORTAL,))
    assert rows(writer, PORTAL)[0]["itad_steam_deals"] == 0
    assert result.summary["stopped"] == [{"app_id": PORTAL, "name": "Portal 2"}]


def test_source_error_writes_nothing_and_keeps_the_last_version(writer):
    steam, itad = FakeSteam(), FakeItad()
    resolve(writer, steam, itad, apps=(DYING,))
    steam.fail = True
    result = resolve(writer, steam, itad, apps=(DYING,), now=NOW + DAY)
    assert len(rows(writer, DYING)) == 1
    assert result.summary["source_error"] is True and result.alerts
    kept = result.versions[DYING]
    assert (kept.external_id, kept.history_id, kept.checked_at) == (ESSENTIALS_ID, ESSENTIALS_ID, NOW)


def test_one_row_per_app_per_run_and_summary_counts(writer):
    result = resolve(writer, FakeSteam(), FakeItad())
    assert result.summary["checked"] == 2 and result.summary["unchanged"] == 1
    assert len(rows(writer, DYING)) == len(rows(writer, PORTAL)) == 1
