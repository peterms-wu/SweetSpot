"""The daily version step (feature 006; spec FR-001–FR-006, FR-011, FR-015; research R1, R2; data-model §1).

For every tracked app with a Taiwan store price:
1. The default purchase option is the package whose (original, final) price equals the store's price_overview
   (exactly one match; bundles never count). No price: `no-option`; zero or several matches: `ambiguous`.
2. ITAD's product of that package (`sub/<id>`). Unknown to ITAD: `not-in-itad`.
3. Verification: the app's own verified 001 mapping when it is the same product; else a verification of the same
   product within `max_age` (keeping its original time, constitution II); else verify_version now.
4. ITAD's Steam price count for the product (0 = ITAD no longer tracks it on Steam).
One app_versions row per app. A source error writes nothing: every app keeps its last recorded version.
"""

import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sweetspot.pipeline.mapping import Mapping as OwnMapping
from sweetspot.pipeline.mapping import latest_mapping
from sweetspot.pipeline.verify import VerifyResult, verify_version
from sweetspot.sources import HistorySource, ItadPriceSource, MetadataSource, PriceLookup, VersionSource
from sweetspot.sources.errors import SourceError
from sweetspot.store.writer import StoreWriter
from sweetspot.timeutil import from_db, to_db

VERIFIED_OWN = ("verified", "verified-legacy")


@dataclass(frozen=True)
class AppVersion:
    app_id: int
    status: str                         # ok | no-option | ambiguous | not-in-itad
    checked_at: datetime
    package_id: int | None = None
    package_name: str | None = None
    external_id: str | None = None      # ITAD product of the default package
    verification: str | None = None     # verified | rejected (status ok only)
    verified_by: str | None = None
    reason_code: str | None = None
    reason_detail: str | None = None
    itad_steam_deals: int | None = None
    history_id: str | None = None       # ITAD product whose history to fetch; None when the version is rejected


@dataclass
class VersionRun:
    versions: dict[int, AppVersion]
    summary: dict[str, Any]
    alerts: list[str] = field(default_factory=list)
    options: dict[int, list] = field(default_factory=dict)   # the GetItems purchase options (reused by feature 009)


def _names(writer: StoreWriter, apps: Sequence[int]) -> dict[int, str]:
    out: dict[int, str] = {}
    for app in apps:
        row = writer.conn.execute("SELECT value_json FROM product_facts WHERE app_id = ? AND field = 'name' "
                                  "ORDER BY retrieved_at DESC, fact_id DESC LIMIT 1", (app,)).fetchone()
        out[app] = json.loads(row[0]) if row and row[0] else str(app)
    return out


def _previous(writer: StoreWriter, app_id: int, before: datetime) -> dict | None:
    cur = writer.conn.execute(
        "SELECT * FROM app_versions WHERE app_id = ? AND checked_at < ? ORDER BY checked_at DESC, version_row_id DESC "
        "LIMIT 1", (app_id, to_db(before)))
    row = cur.fetchone()
    return dict(zip([d[0] for d in cur.description], row)) if row else None


def _history_id(status: str, verification: str | None, external_id: str | None, own: OwnMapping | None) -> str | None:
    if status == "ok" and verification == "verified":
        return external_id
    if status == "ok" and verification == "rejected":
        return None
    return own.external_id if own and own.verification in VERIFIED_OWN else None


def _from_previous(row: dict, own: OwnMapping | None) -> AppVersion:
    return AppVersion(row["app_id"], row["status"], from_db(row["checked_at"]), row["package_id"], row["package_name"],
                      row["external_id"], row["verification"], row["verified_by"], row["reason_code"],
                      row["reason_detail"], row["itad_steam_deals"],
                      _history_id(row["status"], row["verification"], row["external_id"], own))


def default_package(lookup: PriceLookup | None, options) -> tuple[str, Any]:
    """('ok', option) | ('no-option', None) | ('ambiguous', None) (research R1)."""
    if lookup is None or not lookup.found or lookup.quote is None:
        return "no-option", None
    target = (lookup.quote.initial_cents, lookup.quote.final_cents)
    matches = [o for o in options or [] if o.package_id and (o.original_cents, o.final_cents) == target]
    return ("ok", matches[0]) if len(matches) == 1 else ("ambiguous", None)


def resolve_versions(writer: StoreWriter, steam: VersionSource, itad: HistorySource | ItadPriceSource,
                     metadata: MetadataSource | None, apps: list[int], lookups: Mapping[int, PriceLookup],
                     own: Mapping[int, OwnMapping], *, run_id: str, now: datetime, max_age: timedelta,
                     region: str = "TW") -> VersionRun:
    started = time.monotonic()
    names = _names(writer, apps)
    previous = {a: _previous(writer, a, now) for a in apps}
    summary: dict[str, Any] = {"checked": 0, "unchanged": 0, "changed": [], "rejected": [], "stopped": [],
                               "fallback_own": {"ambiguous": 0, "not-in-itad": 0}, "no_option": 0,
                               "source_error": False}
    try:
        priced = [a for a in apps if (lk := lookups.get(a)) is not None and lk.found and lk.quote is not None]
        options = steam.purchase_options(priced) if priced else {}
        defaults = {a: default_package(lookups.get(a), options.get(a)) for a in apps}
        packages = sorted({o.package_id for status, o in defaults.values() if status == "ok"})
        products = itad.lookup_packages(packages) if packages else {}
        plan = {}
        for app in apps:
            status, option = defaults[app]
            ext = products.get(option.package_id) if status == "ok" else None
            if status == "ok" and ext is None:
                status = "not-in-itad"
            plan[app] = (status, option, ext)
        results = _verify_all(writer, steam, itad, metadata, plan, options, own, previous, now, max_age)
        exts = sorted({ext for status, _, ext in plan.values() if ext})
        try:
            deals = {k: v.steam_deals for k, v in itad.price_summaries(exts, region).items()} if exts else {}
        except SourceError:
            deals = {}                   # unknown, not zero (constitution I)
    except SourceError as exc:
        summary["source_error"] = True
        kept = {a: _from_previous(row, own.get(a)) for a, row in previous.items() if row}
        summary["seconds"] = round(time.monotonic() - started, 1)
        return VersionRun(kept, summary, [f"版本步驟的來源錯誤，沿用上一次的版本：{exc}"])

    out: dict[int, AppVersion] = {}
    alerts: list[str] = []
    with writer.transaction():
        for app in apps:
            status, option, ext = plan[app]
            verdict, verified_by, verified_at, aliases = results.get(app, (None, None, None, None))
            version = AppVersion(
                app, status, now, option.package_id if option else None, option.name if option else None, ext,
                verdict.verification if verdict else None, verified_by, verdict.reason_code if verdict else None,
                verdict.reason_detail if verdict else None, deals.get(ext) if ext else None,
                _history_id(status, verdict.verification if verdict else None, ext, own.get(app)))
            quote = lookups[app].quote if status != "no-option" else None
            writer.add_version(run_id, app, checked_at=now, status=status, package_id=version.package_id,
                               package_name=version.package_name,
                               regular_cents=quote.initial_cents if quote else None,
                               price_cents=quote.final_cents if quote else None, external_id=ext,
                               verification=version.verification, verified_by=verified_by, verified_at=verified_at,
                               reason_code=version.reason_code, reason_detail=version.reason_detail,
                               warnings=verdict.warnings if verdict else None, aliases=aliases,
                               itad_steam_deals=version.itad_steam_deals)
            out[app] = version
            _count(summary, alerts, version, previous.get(app), own.get(app), names[app])
    summary["seconds"] = round(time.monotonic() - started, 1)
    return VersionRun(out, summary, alerts, options)


def _verify_all(writer, steam, itad, metadata, plan, options, own, previous, now, max_age):
    """app -> (VerifyResult, verified_by, verified_at, aliases) for apps whose status is ok."""
    results: dict[int, tuple] = {}
    pending = []
    for app, (status, option, ext) in plan.items():
        if status != "ok":
            continue
        mine = own.get(app)
        prev = previous.get(app)
        if mine and mine.external_id == ext and mine.verification in VERIFIED_OWN:
            checked = latest_mapping(writer, app)
            results[app] = (VerifyResult("verified"), "own-mapping", from_db(checked[3]) if checked else now, None)
        elif (prev and prev["external_id"] == ext and prev["verification"] and prev["verified_at"]
              and now - from_db(prev["verified_at"]) <= max_age):
            verdict = VerifyResult(prev["verification"], prev["reason_code"],
                                   json.loads(prev["warnings_json"]) if prev["warnings_json"] else [],
                                   prev["reason_detail"])
            results[app] = (verdict, "cached", from_db(prev["verified_at"]),
                            json.loads(prev["aliases_json"]) if prev["aliases_json"] else None)
        else:
            pending.append(app)
    if not pending:
        return results
    exts = sorted({plan[a][2] for a in pending})
    aliases = itad.reverse_lookup(exts)
    subs = sorted({int(x[4:]) for e in exts for x in aliases.get(e) or [] if x.startswith("sub/") and x[4:].isdigit()})
    packages = steam.version_packages(subs) if subs else {}
    extra = sorted({a for p in packages.values() for a in p.app_ids} - set(pending))
    kinds = steam.app_kinds(extra) if extra else {}
    for app in pending:
        status, option, ext = plan[app]
        prices = {o.package_id: (o.original_cents, o.final_cents) for o in options.get(app) or [] if o.package_id}
        alias_list = aliases.get(ext) or []
        verdict = verify_version(app, alias_list, default_package=option.package_id, options=prices,
                                 packages=packages, kinds=kinds, metadata=metadata)
        results[app] = (verdict, "version-check", now, alias_list)
    return results


def _label(row: dict | None, own: OwnMapping | None, app_name: str) -> tuple[str | None, str | None]:
    """(ITAD product, display name) the app used before this run."""
    if row and row["status"] == "ok" and row["external_id"]:
        return row["external_id"], row["package_name"] or app_name
    return (own.external_id if own else None), app_name


def _count(summary: dict, alerts: list[str], version: AppVersion, prev: dict | None, own: OwnMapping | None,
           name: str) -> None:
    if version.status == "no-option":
        summary["no_option"] += 1
        return
    if version.status in ("ambiguous", "not-in-itad"):
        summary["fallback_own"][version.status] += 1
        return
    summary["checked"] += 1
    before, before_name = _label(prev, own, name)
    if version.verification == "rejected":
        summary["rejected"].append({"app_id": version.app_id, "name": name, "reason": version.reason_code,
                                    "detail": version.reason_detail})
        if before != version.external_id:
            alerts.append(f"{name}：Steam 目前的購買選項（{version.package_name}）在 ITAD 的商品核對未通過"
                          f"（{version.reason_code} {version.reason_detail or ''}），不使用它的價格歷史")
        return
    if before != version.external_id:
        summary["changed"].append({"app_id": version.app_id, "name": name, "from": before_name,
                                   "to": version.package_name})
        alerts.append(f"{name}：Steam 換了預設購買選項，改用 {version.package_name} 的價格歷史")
    else:
        summary["unchanged"] += 1
    if version.itad_steam_deals == 0:
        summary["stopped"].append({"app_id": version.app_id, "name": name})
        alerts.append(f"{name}：ITAD 已沒有這個商品在 Steam 的價格，價格歷史停止更新")
