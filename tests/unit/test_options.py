"""feature 009: the daily purchase-option step (spec FR-001–FR-004, FR-009, FR-017; research R1, R2, R8)."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from sweetspot.pipeline import options
from sweetspot.pipeline.versions import AppVersion
from sweetspot.sources import AppKind, BundleContents, ItadPrice, PurchaseOption, VersionPackage
from sweetspot.sources.errors import SourceError
from sweetspot.store.writer import StoreWriter

NOW = datetime(2026, 9, 27, 1, 0, tzinfo=UTC)
DAY = timedelta(days=1)
MAX_AGE = timedelta(days=7)          # mapping_days: verification cache
KINDS_AGE = timedelta(days=30)       # static_metadata_days: app kinds inside bundles

CP, PL = 1091500, 2138330                         # Cyberpunk 2077 and its DLC Phantom Liberty
DAVE, DAVE_DLC, MISIDE = 1868140, 2492320, 2527500
DMC, DMC_DLC = 601150, 941950
CP_DEFAULT, CP_ULT = 367653, 32470
DAVE_DEFAULT, DAVE_DELUXE, DAVE_MISIDE, DAVE_GONE = 672152, 32958, 77855, 1
DMC_DEFAULT, DMC_DELUXE, DMC_UPGRADE = 613144, 613145, 10318
ITAD_CP_ULT, ITAD_DAVE_DELUXE, ITAD_DMC_DELUXE = "itad-cp-ult", "itad-dave-deluxe", "itad-dmc-deluxe"


class FakeSteam:
    def __init__(self):
        self.packages = {DMC_DELUXE: VersionPackage(DMC_DELUXE, True, [DMC, DMC_DLC], "Devil May Cry 5 Deluxe")}
        self.bundles = {CP_ULT: BundleContents(CP_ULT, True, [CP, PL], "終極版"),
                        DAVE_DELUXE: BundleContents(DAVE_DELUXE, True, [DAVE, DAVE_DLC], "Deluxe"),
                        DAVE_MISIDE: BundleContents(DAVE_MISIDE, True, [DAVE, MISIDE], "DAVE x MiSide"),
                        DMC_UPGRADE: BundleContents(DMC_UPGRADE, True, [DMC_DLC], "Deluxe Upgrade"),
                        DAVE_GONE: BundleContents(DAVE_GONE, False, [], None)}
        self.kinds = {PL: AppKind(PL, 4, CP), DAVE_DLC: AppKind(DAVE_DLC, 4, DAVE), MISIDE: AppKind(MISIDE, 0, None),
                      DMC_DLC: AppKind(DMC_DLC, 4, DMC)}
        self.calls = []
        self.fail = False

    def version_packages(self, package_ids):
        self.calls.append(("packages", sorted(package_ids)))
        if self.fail:
            raise SourceError("steam-webapi: GetItems (packages) HTTP 500")
        return {p: self.packages[p] for p in package_ids if p in self.packages}

    def bundle_contents(self, bundle_ids):
        self.calls.append(("bundles", sorted(bundle_ids)))
        return {b: self.bundles[b] for b in bundle_ids if b in self.bundles}

    def app_kinds(self, app_ids):
        self.calls.append(("kinds", sorted(app_ids)))
        return {a: self.kinds[a] for a in app_ids if a in self.kinds}


class FakeItad:
    def __init__(self):
        self.ids = {("bundle", CP_ULT): ITAD_CP_ULT, ("bundle", DAVE_DELUXE): ITAD_DAVE_DELUXE,
                    ("sub", DMC_DELUXE): ITAD_DMC_DELUXE}
        self.aliases = {ITAD_CP_ULT: ["bundle/32470"], ITAD_DAVE_DELUXE: ["bundle/32958", "bundle/99999"],
                        ITAD_DMC_DELUXE: ["sub/613145"]}
        self.calls = []

    def lookup_ids(self, ids):
        self.calls.append(("lookup", sorted(ids)))
        return {i: self.ids.get(i) for i in ids}

    def reverse_lookup(self, external_ids):
        self.calls.append(("aliases", sorted(external_ids)))
        return {e: self.aliases.get(e, []) for e in external_ids}

    def price_summaries(self, external_ids, country):
        self.calls.append(("prices", sorted(external_ids)))
        return {e: ItadPrice(None, 1) for e in external_ids}


class NoMetadata:
    def canonical_app_id(self, app_id):
        return None


OPTIONS = {
    CP: [PurchaseOption(CP_DEFAULT, None, "Cyberpunk 2077", 159900, 159900),
         PurchaseOption(None, CP_ULT, "《電馭叛客 2077：終極版》", 220600, 220600)],
    DAVE: [PurchaseOption(DAVE_DEFAULT, None, "DAVE THE DIVER", 35000, 35000),
           PurchaseOption(None, DAVE_DELUXE, "Deluxe", 45900, 45900),
           PurchaseOption(None, DAVE_MISIDE, "DAVE x MiSide", 55600, 55600),
           PurchaseOption(None, DAVE_GONE, "Gone", 10000, 10000)],
    DMC: [PurchaseOption(DMC_DEFAULT, None, "Devil May Cry 5 + Vergil", 86000, 86000),
          PurchaseOption(DMC_DELUXE, None, "Devil May Cry 5 Deluxe + Vergil", 119000, 119000),
          PurchaseOption(None, DMC_UPGRADE, "Deluxe Upgrade", 43300, 43300)],
}
VERSIONS = {CP: AppVersion(CP, "ok", NOW, CP_DEFAULT, "Cyberpunk 2077", "itad-cp", "verified",
                           history_id="itad-cp"),
            DAVE: AppVersion(DAVE, "ok", NOW, DAVE_DEFAULT, "DAVE THE DIVER", "itad-dave", "verified",
                             history_id="itad-dave"),
            DMC: AppVersion(DMC, "ok", NOW, DMC_DEFAULT, "Devil May Cry 5", "itad-dmc", "verified",
                            history_id="itad-dmc")}


@pytest.fixture
def writer(db_path):
    w = StoreWriter.open(db_path)
    run = w.start_run("daily")
    for app, name in ((CP, "Cyberpunk 2077"), (DAVE, "DAVE THE DIVER"), (DMC, "Devil May Cry 5")):
        w.ensure_product(app, "wishlist", NOW - 10 * DAY)
        w.add_facts(run, app, {"name": name}, source="steam-appdetails", retrieved_at=NOW - 10 * DAY)
    yield w
    w.close()


def resolve(writer, steam, itad, *, now=NOW, chosen=None, apps=(CP, DAVE, DMC), opts=None):
    run = writer.start_run("daily")
    return options.resolve_options(writer, steam, itad, NoMetadata(), list(apps), OPTIONS if opts is None else opts,
                                   VERSIONS, chosen or {}, run_id=run, now=now, max_age=MAX_AGE,
                                   kinds_age=KINDS_AGE, region="TW")


def rows(writer, app=None):
    cur = writer.conn.execute("SELECT * FROM purchase_options " + ("WHERE app_id = ? " if app else "") +
                              "ORDER BY checked_at, app_id, position", (app,) if app else ())
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def test_roles_of_every_option(writer):
    resolve(writer, FakeSteam(), FakeItad())
    roles = {(r["kind"], r["option_id"]): r["role"] for r in rows(writer)}
    assert roles == {("sub", CP_DEFAULT): "default", ("bundle", CP_ULT): "edition",
                     ("sub", DAVE_DEFAULT): "default", ("bundle", DAVE_DELUXE): "edition",
                     ("bundle", DAVE_MISIDE): "other-games", ("bundle", DAVE_GONE): "unknown",
                     ("sub", DMC_DEFAULT): "default", ("sub", DMC_DELUXE): "edition",
                     ("bundle", DMC_UPGRADE): "without-app"}
    default = next(r for r in rows(writer, CP) if r["role"] == "default")
    assert default["is_default"] == 1 and default["external_id"] is None and default["verification"] is None
    ult = next(r for r in rows(writer, CP) if r["option_id"] == CP_ULT)
    assert (ult["original_cents"], ult["final_cents"], ult["position"], ult["name"]) == (220600, 220600, 1,
                                                                                        "《電馭叛客 2077：終極版》")
    assert json.loads(ult["contents_json"]) == [{"app_id": CP, "type": None, "parent_app_id": None},
                                                {"app_id": PL, "type": 4, "parent_app_id": CP}]


def test_only_editions_are_looked_up_and_verified(writer):
    itad = FakeItad()
    result = resolve(writer, FakeSteam(), itad)
    [lookup] = [c for c in itad.calls if c[0] == "lookup"]
    assert lookup[1] == sorted([("bundle", CP_ULT), ("bundle", DAVE_DELUXE), ("sub", DMC_DELUXE)])
    got = {r["option_id"]: (r["external_id"], r["verification"], r["reason_code"], r["reason_detail"])
           for r in rows(writer) if r["role"] == "edition"}
    assert got[CP_ULT] == (ITAD_CP_ULT, "verified", None, None)            # its own bundle alias is accepted
    assert got[DMC_DELUXE] == (ITAD_DMC_DELUXE, "verified", None, None)
    assert got[DAVE_DELUXE] == (ITAD_DAVE_DELUXE, "rejected", "bundle", "bundle/99999")   # another bundle
    assert result.summary["editions"] == 3 and result.summary["editions_verified"] == 2
    assert result.summary["rejected"] == [{"app_id": DAVE, "name": "DAVE THE DIVER", "option": "bundle/32958",
                                           "reason": "bundle", "detail": "bundle/99999"}]
    assert any("DAVE THE DIVER" in a and "bundle/32958" in a for a in result.alerts)


def test_verified_editions_are_returned_for_history_fetching(writer):
    result = resolve(writer, FakeSteam(), FakeItad(), chosen={CP: ("bundle", CP_ULT)})
    fetch = {(f.app_id, f.external_id): f.aux for f in result.fetch}
    assert fetch == {(CP, ITAD_CP_ULT): True, (DMC, ITAD_DMC_DELUXE): False}   # US only for the chosen one (D2)


def test_edition_of_the_default_product_is_not_fetched_again(writer):
    itad = FakeItad()
    itad.ids[("sub", DMC_DELUXE)] = "itad-dmc"          # same ITAD product as the default version
    itad.aliases["itad-dmc"] = ["sub/613145"]
    result = resolve(writer, FakeSteam(), itad)
    assert (DMC, "itad-dmc") not in {(f.app_id, f.external_id) for f in result.fetch}


def test_app_kinds_are_reused_for_30_days_with_their_original_time(writer):
    steam = FakeSteam()
    resolve(writer, steam, FakeItad())
    asked = {a for c in steam.calls if c[0] == "kinds" for a in c[1]}
    assert asked >= {PL, DAVE_DLC, MISIDE, DMC_DLC}
    steam.calls.clear()
    resolve(writer, steam, FakeItad(), now=NOW + 3 * DAY)
    assert [c for c in steam.calls if c[0] == "kinds" and set(c[1]) & {PL, DAVE_DLC, MISIDE, DMC_DLC}] == []
    ult = [r for r in rows(writer, CP) if r["option_id"] == CP_ULT][-1]
    assert ult["contents_checked_at"] == "2026-09-27T01:00:00.000000Z"
    steam.calls.clear()
    resolve(writer, steam, FakeItad(), now=NOW + 31 * DAY)
    assert any(c[0] == "kinds" and PL in c[1] for c in steam.calls)


def test_kinds_never_reach_products_or_facts(writer):
    resolve(writer, FakeSteam(), FakeItad())
    tracked = {a for (a,) in writer.conn.execute("SELECT app_id FROM products")}
    assert tracked == {CP, DAVE, DMC}
    assert {a for (a,) in writer.conn.execute("SELECT DISTINCT app_id FROM product_facts")} == {CP, DAVE, DMC}


def test_verification_is_cached_for_seven_days(writer):
    itad = FakeItad()
    resolve(writer, FakeSteam(), itad)
    itad.calls.clear()
    resolve(writer, FakeSteam(), itad, now=NOW + 2 * DAY)
    assert [c for c in itad.calls if c[0] == "aliases"] == []
    ult = [r for r in rows(writer, CP) if r["option_id"] == CP_ULT][-1]
    assert (ult["verified_by"], ult["verified_at"]) == ("cached", "2026-09-27T01:00:00.000000Z")
    resolve(writer, FakeSteam(), itad, now=NOW + 8 * DAY)
    assert any(c[0] == "aliases" for c in itad.calls)


def test_rejection_alert_only_on_first_appearance(writer):
    first = resolve(writer, FakeSteam(), FakeItad())
    second = resolve(writer, FakeSteam(), FakeItad(), now=NOW + DAY)
    assert any("bundle/32958" in a for a in first.alerts)
    assert not any("bundle/32958" in a for a in second.alerts)


def test_source_error_writes_nothing(writer):
    steam = FakeSteam()
    steam.fail = True
    result = resolve(writer, steam, FakeItad())
    assert rows(writer) == [] and result.fetch == []
    assert result.summary["source_error"] is True
    assert any("購買選項" in a for a in result.alerts)


def test_summary_counts(writer):
    result = resolve(writer, FakeSteam(), FakeItad(), chosen={CP: ("bundle", CP_ULT)})
    s = result.summary
    assert (s["apps"], s["options"], s["editions"], s["editions_verified"]) == (3, 9, 3, 2)
    assert s["specified"]["active"] == [{"app_id": CP, "name": "Cyberpunk 2077", "option": "bundle/32470"}]
    assert s["source_error"] is False and "seconds" in s
