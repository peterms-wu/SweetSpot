"""Confirm an external source's product is the same Steam app before storing its history (FR-008).

Rules (research R2):
1. Mapping exactly ["app/N"] passes.
2. Every other app/X must resolve (Steam canonical steam_appid) to N — an alias.
3. Every sub/X must contain only N, with the same TWD regular and sale price as N.
4. A sub that is not publicly queryable and not among N's current packages only warns.
5. Anything else rejects with a reason code; nothing is stored for rejected mappings.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

from sweetspot.sources import AppKind, MetadataSource, PriceQuote, VersionPackage


@dataclass(frozen=True)
class VerifyResult:
    verification: str               # verified | rejected
    reason_code: str | None = None
    warnings: list[str] = field(default_factory=list)
    reason_detail: str | None = None    # feature 006: which alias or app caused the rejection


def _reject(reason: str, warnings: list[str] | None = None, detail: str | None = None) -> VerifyResult:
    return VerifyResult("rejected", reason, warnings or [], detail)


def _same_price(a: PriceQuote | None, b: PriceQuote | None) -> bool:
    if a is None or b is None:
        return a is b
    return (a.currency, a.initial_cents, a.final_cents) == (b.currency, b.initial_cents, b.final_cents)


def verify_mapping(app_id: int, aliases: list[str], *, quote: PriceQuote | None, current_packages: list[int],
                   metadata: MetadataSource | None) -> VerifyResult:
    if not aliases:
        return _reject("not-found")
    if f"app/{app_id}" not in aliases:
        return _reject("different-product")
    if aliases == [f"app/{app_id}"]:
        return VerifyResult("verified")

    warnings: list[str] = []
    for alias in aliases:
        kind, _, raw_id = alias.partition("/")
        if kind == "bundle":
            return _reject("bundle")
        if kind not in ("app", "sub") or not raw_id.isdigit():
            return _reject("multiple-candidates")
        other = int(raw_id)
        if kind == "app":
            if other != app_id and metadata.canonical_app_id(other) != app_id:
                return _reject("different-product")
            continue
        package = metadata.package_details(other)
        if package is None:
            if other in current_packages:
                return _reject("package-mismatch")
            warnings.append(f"sub/{other} 無法公開查詢，且不在目前販售的套件中")
            continue
        if len(package.app_ids) > 1:
            return _reject("bundle")
        if package.app_ids != [app_id]:
            return _reject("different-product")
        if not _same_price(package.quote, quote):
            return _reject("price-mismatch")
    return VerifyResult("verified", warnings=warnings)


DLC_TYPE = 4    # GetItems item type of a DLC


def verify_version(app_id: int, aliases: list[str], *, default_package: int,
                   options: Mapping[int, tuple[int, int]], packages: Mapping[int, VersionPackage],
                   kinds: Mapping[int, AppKind], metadata: MetadataSource | None, option: str | None = None,
                   reference_price: tuple[int, int] | None = None) -> VerifyResult:
    """Feature 006 (research R2, spec FR-005): may the history of the ITAD product that tracks the app's default
    package be used? Rules 1, 2 and 5 are 001's; for packages:
    - prices come from the app's own purchase options (`options`: package -> (original, final) cents), since a
      package's own "best purchase option" can be a bundle that contains it;
    - a package still sold must cost the same as the default option, and one that is not sold only warns;
    - contents must be the app plus zero or more of its own DLC.
    Feature 009 (research R2): `option` is the purchase option being verified (`sub/N` or `bundle/N`). A `bundle/N`
    alias equal to it is accepted (its contents were checked before: the app plus its own DLC); any other bundle
    still rejects. `reference_price` is the option's own (original, final) price when it is not one of `options`.
    """
    if not aliases:
        return _reject("not-found")
    warnings: list[str] = []
    default_price = reference_price if reference_price is not None else options.get(default_package)
    for alias in aliases:
        kind, _, raw_id = alias.partition("/")
        if kind == "bundle" and option is not None and alias == option:
            continue
        if kind == "bundle":
            return _reject("bundle", warnings, alias)
        if kind not in ("app", "sub") or not raw_id.isdigit():
            return _reject("multiple-candidates", warnings, alias)
        other = int(raw_id)
        if kind == "app":
            if other != app_id and (metadata is None or metadata.canonical_app_id(other) != app_id):
                return _reject("different-product", warnings, alias)
            continue
        sold = options.get(other)
        package = packages.get(other)
        if package is None or not package.public:
            if sold is not None:
                return _reject("package-mismatch", warnings, alias)
            warnings.append(f"{alias} 無法公開查詢")
            continue
        if sold is not None and sold != default_price:
            return _reject("price-mismatch", warnings, alias)
        if app_id not in package.app_ids:
            return _reject("different-product", warnings, alias)
        others = [a for a in package.app_ids if a != app_id and not (
            (k := kinds.get(a)) is not None and k.type == DLC_TYPE and k.parent_app_id == app_id)]
        if others:
            return _reject("other-games", warnings, ",".join(str(a) for a in others))
        if sold is None:
            warnings.append(f"{alias} 目前不在這款遊戲的購買選項中")
    return VerifyResult("verified", warnings=warnings)

