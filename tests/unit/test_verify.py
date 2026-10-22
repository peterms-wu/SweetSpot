"""research R2: the five product verification rules (FR-008, SC-004)."""

import json

import pytest

from sweetspot import sources
from sweetspot.pipeline.verify import verify_mapping
from sweetspot.sources import PriceQuote
from sweetspot.sources import steam_store as ss
from tests.conftest import FIXTURES

STEAM = FIXTURES / "steam"
QUOTE_620 = PriceQuote("TWD", 18800, 18800, 0)


def load(name):
    return json.loads((STEAM / name).read_text(encoding="utf-8"))


class FixtureMetadata:
    """MetadataSource backed by recorded Steam responses, plus overrides for synthetic cases."""

    def __init__(self, packages=None, canonical=None):
        self.packages = packages or {}
        self.canonical = canonical or {}

    def canonical_app_id(self, app_id):
        if app_id in self.canonical:
            return self.canonical[app_id]
        path = STEAM / f"appdetails_{app_id}.json"
        if not path.exists():
            return None
        return ss.parse_canonical_app_id(load(path.name))

    def package_details(self, package_id):
        if package_id in self.packages:
            return self.packages[package_id]
        path = STEAM / f"packagedetails_{package_id}.json"
        return ss.parse_package_details(load(path.name), package_id) if path.exists() else None


def test_single_exact_app_passes_without_requests():
    result = verify_mapping(620, ["app/620"], quote=QUOTE_620, current_packages=[], metadata=None)
    assert result.verification == "verified" and result.warnings == []


def test_alias_app_resolving_to_same_canonical_id_passes():
    # Portal 2: ITAD lists app/659, which Steam resolves to 620, and single-app sub/7877.
    result = verify_mapping(620, ["app/659", "app/620", "sub/7877"], quote=QUOTE_620,
                            current_packages=[204528, 7877, 8187], metadata=FixtureMetadata())
    assert result.verification == "verified", result.reason_code


def test_unqueryable_sub_outside_current_packages_only_warns():
    # Half-Life 2: sub/1187613 and sub/1187615 are not public and not sold now.
    quote_220 = ss.parse_package_details(load("packagedetails_36.json"), 36).quote
    result = verify_mapping(220, ["sub/1187613", "sub/1187615", "app/220", "sub/36"], quote=quote_220,
                            current_packages=[289444, 36, 469], metadata=FixtureMetadata())
    assert result.verification == "verified"
    assert len(result.warnings) == 2 and all("1187613" in w or "1187615" in w for w in result.warnings)


def test_unqueryable_sub_that_is_currently_sold_is_rejected():
    result = verify_mapping(220, ["app/220", "sub/1187613"], quote=None, current_packages=[1187613],
                            metadata=FixtureMetadata())
    assert result.verification == "rejected" and result.reason_code == "package-mismatch"


def test_alias_resolving_to_other_app_is_rejected():
    result = verify_mapping(620, ["app/620", "app/999"], quote=QUOTE_620, current_packages=[],
                            metadata=FixtureMetadata(canonical={999: 12345}))
    assert result.verification == "rejected" and result.reason_code == "different-product"


def test_multi_app_package_is_a_bundle():
    bundle = ss.PackageDetails(500, [620, 400], QUOTE_620)
    result = verify_mapping(620, ["app/620", "sub/500"], quote=QUOTE_620, current_packages=[],
                            metadata=FixtureMetadata(packages={500: bundle}))
    assert result.verification == "rejected" and result.reason_code == "bundle"


def test_package_for_another_app_is_different_product():
    other = ss.PackageDetails(501, [400], QUOTE_620)
    result = verify_mapping(620, ["app/620", "sub/501"], quote=QUOTE_620, current_packages=[],
                            metadata=FixtureMetadata(packages={501: other}))
    assert result.reason_code == "different-product"


def test_single_app_package_with_different_price_is_rejected():
    deluxe = ss.PackageDetails(502, [620], PriceQuote("TWD", 49000, 49000, 0))
    result = verify_mapping(620, ["app/620", "sub/502"], quote=QUOTE_620, current_packages=[],
                            metadata=FixtureMetadata(packages={502: deluxe}))
    assert result.reason_code == "price-mismatch"


def test_mapping_that_does_not_include_the_app_is_rejected():
    result = verify_mapping(620, ["app/400"], quote=QUOTE_620, current_packages=[], metadata=FixtureMetadata())
    assert result.reason_code == "different-product"


def test_no_mapping_is_not_found():
    result = verify_mapping(620, [], quote=QUOTE_620, current_packages=[], metadata=None)
    assert result.verification == "rejected" and result.reason_code == "not-found"


@pytest.mark.parametrize("alias,reason", [("bundle/12", "bundle"), ("garbage", "multiple-candidates")])
def test_unknown_alias_kinds_are_rejected(alias, reason):
    result = verify_mapping(620, ["app/620", alias], quote=QUOTE_620, current_packages=[], metadata=None)
    assert result.verification == "rejected" and result.reason_code == reason


# --- feature 006: verify_version (research R2, spec FR-005) ---------------------------------------------------

from sweetspot.pipeline.verify import verify_version  # noqa: E402
from sweetspot.sources import steam_webapi  # noqa: E402

DYING = 239140
ESSENTIALS, TWIN, TENTH = 1345940, 1345941, 1265945
OPTIONS = {DYING: {ESSENTIALS: (67000, 13400), TENTH: (74900, 14900)}}


def packages():
    return steam_webapi.parse_version_packages(load("getitems_version_packages.json"))


def kinds():
    """Recorded DLC of Essentials, plus the 10th Anniversary package's extra apps as DLC of Dying Light."""
    from sweetspot.sources import AppKind

    known = steam_webapi.parse_app_kinds(load("getitems_dlc_apps.json"))
    for app in packages()[TENTH].app_ids:
        if app != DYING:
            known.setdefault(app, AppKind(app, 4, DYING))
    return known


def run(aliases, *, app=DYING, default=ESSENTIALS, options=None, pkgs=None, kind_map=None, metadata=None):
    return verify_version(app, aliases, default_package=default,
                          options=OPTIONS[DYING] if options is None else options,
                          packages=packages() if pkgs is None else pkgs,
                          kinds=kinds() if kind_map is None else kind_map, metadata=metadata or FixtureMetadata())


def test_essentials_with_own_dlc_and_a_non_public_twin_is_verified():
    result = run([f"sub/{TWIN}", f"sub/{ESSENTIALS}"])
    assert result.verification == "verified" and result.reason_code is None
    assert result.warnings == [f"sub/{TWIN} 無法公開查詢"]


def test_bundle_alias_rejects_with_its_id():
    result = run(["sub/9900011", "bundle/99003"], app=9500003, default=9900011, options={9900011: (22600, 5600)})
    assert (result.verification, result.reason_code, result.reason_detail) == ("rejected", "bundle", "bundle/99003")


def test_package_with_another_game_rejects_other_games():
    from sweetspot.sources import VersionPackage

    pkgs = {**packages(), 555: VersionPackage(555, True, [DYING, 302101, 534380], "Dying Light + DL2")}
    result = run([f"sub/{ESSENTIALS}", "sub/555"], pkgs=pkgs, options={ESSENTIALS: (67000, 13400), 555: (67000, 13400)})
    assert (result.verification, result.reason_code, result.reason_detail) == ("rejected", "other-games", "534380")


def test_sold_package_with_another_price_rejects_price_mismatch():
    result = run([f"sub/{ESSENTIALS}", f"sub/{TENTH}"])
    assert (result.verification, result.reason_code, result.reason_detail) == (
        "rejected", "price-mismatch", f"sub/{TENTH}")


def test_package_not_sold_only_warns():
    result = run([f"sub/{ESSENTIALS}", f"sub/{TENTH}"], options={ESSENTIALS: (67000, 13400)})
    assert result.verification == "verified"
    assert result.warnings == [f"sub/{TENTH} 目前不在這款遊戲的購買選項中"]


def test_non_public_package_that_is_sold_cannot_be_checked():
    result = run([f"sub/{ESSENTIALS}", f"sub/{TWIN}"], options={ESSENTIALS: (67000, 13400), TWIN: (67000, 13400)})
    assert (result.verification, result.reason_code) == ("rejected", "package-mismatch")


def test_prices_come_from_the_apps_options_not_the_packages_best_option():
    """Eternights: GetItems for package 492077 reports a cheaper bundle as its best option (research R0.2)."""
    from sweetspot.sources import VersionPackage

    pkgs = {492077: VersionPackage(492077, True, [1402110], "Eternights")}
    result = run(["app/1402110", "sub/492077"], app=1402110, default=492077, options={492077: (79000, 79000)},
                 pkgs=pkgs, kind_map={})
    assert result.verification == "verified"


def test_app_alias_of_another_game_rejects_different_product():
    result = run(["app/999", f"sub/{ESSENTIALS}"], metadata=FixtureMetadata(canonical={999: 999}))
    assert (result.verification, result.reason_code, result.reason_detail) == ("rejected", "different-product", "app/999")


def test_package_without_the_app_rejects_different_product():
    from sweetspot.sources import VersionPackage

    pkgs = {**packages(), 777: VersionPackage(777, True, [302101], "DLC only")}
    result = run([f"sub/{ESSENTIALS}", "sub/777"], pkgs=pkgs, options={ESSENTIALS: (67000, 13400)})
    assert (result.reason_code, result.reason_detail) == ("different-product", "sub/777")


def test_no_aliases_is_not_found():
    assert run([]).reason_code == "not-found"



# --- feature 009: an edition is verified against itself (research R2) -----------------------------------------

CYBERPUNK, PHANTOM_LIBERTY = 1091500, 2138330
CP_OPTIONS = {367653: (159900, 159900)}                  # the app's packages; the bundle is not a package
CP_KINDS = {PHANTOM_LIBERTY: sources.AppKind(PHANTOM_LIBERTY, 4, CYBERPUNK)}


def test_a_bundle_edition_accepts_its_own_bundle_alias():
    result = verify_version(CYBERPUNK, ["bundle/32470"], default_package=-1, options=CP_OPTIONS, packages={},
                            kinds=CP_KINDS, metadata=FixtureMetadata(), option="bundle/32470",
                            reference_price=(220600, 220600))
    assert result.verification == "verified" and result.reason_code is None


def test_another_bundle_alias_still_rejects():
    result = verify_version(DYING, [f"sub/{TENTH}", "bundle/47759"], default_package=TENTH,
                            options=OPTIONS[DYING], packages=packages(), kinds=kinds(), metadata=FixtureMetadata(),
                            option=f"sub/{TENTH}")
    assert (result.verification, result.reason_code, result.reason_detail) == ("rejected", "bundle", "bundle/47759")


def test_an_edition_package_is_priced_against_itself():
    ac, standard, ultimate = 812140, 349018, 349020
    options = {standard: (169900, 33900), ultimate: (325900, 65100)}
    pkgs = {ultimate: sources.VersionPackage(ultimate, True, [ac, 900001], "Ultimate")}
    ac_kinds = {900001: sources.AppKind(900001, 4, ac)}
    result = verify_version(ac, [f"sub/{ultimate}"], default_package=ultimate, options=options, packages=pkgs,
                            kinds=ac_kinds, metadata=FixtureMetadata(), option=f"sub/{ultimate}")
    assert result.verification == "verified"


def test_without_option_the_006_behaviour_is_unchanged():
    assert run(["bundle/49425"]).reason_detail == "bundle/49425"
    assert run([f"sub/{TWIN}", f"sub/{ESSENTIALS}"]).verification == "verified"
