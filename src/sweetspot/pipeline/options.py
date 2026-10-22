"""The daily purchase-option step (feature 009; spec FR-001–FR-004, FR-009, FR-017; research R1, R2, R8).

After the version step, for every tracked app with purchase options (the same GetItems answer, not asked again):
1. Contents of each option other than the Steam default: packages via GetItems packageid, bundles via bundleid.
   The kinds of the other apps inside (DLC and its parent) are static facts: values recorded in the last
   `kinds_age` are reused with their original time; they are never written to products / product_facts.
2. Role: `edition` (the app plus zero or more of its own DLC), `other-games`, `without-app` or `unknown`.
3. Editions only: ITAD product (`sub/N`, `bundle/N`), verification (006 rule, the option verified against itself;
   a verification of the same product within `max_age` is reused), ITAD's Steam price count.
4. One purchase_options row per option. A source error writes nothing; readers keep the last recorded step.
Returns the verified editions whose history the daily run fetches (TW for all, the aux region only for the user's
chosen edition, plan D2).
"""

import json
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sweetspot.choices import ignored_warning, option_ref, rejection_text, requested_label, resolve_choice
from sweetspot.pipeline.verify import DLC_TYPE, VerifyResult, verify_version
from sweetspot.pipeline.versions import AppVersion, _names
from sweetspot.decision.bundles import check_formula
from sweetspot.sources import ContentPriceSource, MetadataSource, PurchaseOption
from sweetspot.sources.errors import SourceError
from sweetspot.store.writer import NewPurchaseOption, StoreWriter
from sweetspot.timeutil import from_db, to_db


@dataclass(frozen=True)
class EditionFetch:
    app_id: int
    external_id: str
    kind: str
    option_id: int
    aux: bool                       # also fetch the aux-region history: the user's chosen edition (plan D2)


@dataclass
class OptionRun:
    fetch: list[EditionFetch]
    summary: dict[str, Any]
    alerts: list[str] = field(default_factory=list)


def _latest_rows(writer: StoreWriter, apps: Sequence[int], before: datetime) -> dict[int, list[dict]]:
    """Each app's rows of its latest step before `before`."""
    out: dict[int, list[dict]] = {}
    for app in apps:
        cur = writer.conn.execute(
            "SELECT * FROM purchase_options WHERE app_id = ? AND checked_at = (SELECT MAX(checked_at) FROM "
            "purchase_options WHERE app_id = ? AND checked_at < ?) ORDER BY position", (app, app, to_db(before)))
        names = [d[0] for d in cur.description]
        rows = [dict(zip(names, r)) for r in cur.fetchall()]
        if rows:
            out[app] = rows
    return out


def _known_kinds(previous: Mapping[int, list[dict]], now: datetime, max_age: timedelta) -> dict[int, tuple]:
    """app id -> (type, parent_app_id, checked_at) from recent rows' contents (research R8)."""
    known: dict[int, tuple] = {}
    for rows in previous.values():
        for row in rows:
            if not row["contents_json"] or not row["contents_checked_at"]:
                continue
            checked = from_db(row["contents_checked_at"])
            if now - checked > max_age:
                continue
            for item in json.loads(row["contents_json"]):
                if item.get("type") is None:
                    continue
                current = known.get(item["app_id"])
                if current is None or checked < current[2]:
                    known[item["app_id"]] = (item["type"], item.get("parent_app_id"), checked)
    return known


def _role(app: int, contents: list[int] | None, kinds: Mapping[int, tuple]) -> str:
    if contents is None:
        return "unknown"
    if app not in contents:
        return "without-app"
    others = [a for a in contents if a != app]
    if any(a not in kinds for a in others):
        return "unknown"
    return "edition" if all(kinds[a][0] == DLC_TYPE and kinds[a][1] == app for a in others) else "other-games"


def _key(option: PurchaseOption) -> tuple[str, int]:
    return ("sub", option.package_id) if option.package_id else ("bundle", option.bundle_id)


def resolve_options(writer: StoreWriter, steam, itad, metadata: MetadataSource | None, apps: list[int],
                    options: Mapping[int, list[PurchaseOption]], versions: Mapping[int, AppVersion],
                    chosen: Mapping[int, tuple[str, int]], *, run_id: str, now: datetime, max_age: timedelta,
                    kinds_age: timedelta, region: str = "TW") -> OptionRun:
    started = time.monotonic()
    names = _names(writer, apps)
    previous = _latest_rows(writer, apps, now)
    per_app = {a: [o for o in options.get(a) or [] if o.package_id or o.bundle_id] for a in apps}
    per_app = {a: opts for a, opts in per_app.items() if opts}
    defaults = {a: v.package_id for a, v in versions.items() if v.status == "ok" and v.package_id}
    summary: dict[str, Any] = {"apps": len(per_app), "options": 0, "editions": 0, "editions_verified": 0,
                               "rejected": [], "specified": {"active": [], "fallback": [], "ignored": []},
                               "source_error": False}
    alerts: list[str] = []
    try:
        subs = sorted({o.package_id for a, opts in per_app.items() for o in opts
                       if o.package_id and o.package_id != defaults.get(a)})
        bundles = sorted({o.bundle_id for opts in per_app.values() for o in opts if o.bundle_id})
        packages = steam.version_packages(subs) if subs else {}
        bundle_items = steam.bundle_contents(bundles) if bundles else {}

        def contents(option: PurchaseOption) -> list[int] | None:
            if option.package_id:
                package = packages.get(option.package_id)
                return list(package.app_ids) if package and package.public else None
            bundle = bundle_items.get(option.bundle_id)
            return list(bundle.app_ids) if bundle and bundle.found else None

        known = _known_kinds(previous, now, kinds_age)
        inside = {x for a, opts in per_app.items() for o in opts if _key(o) != ("sub", defaults.get(a))
                  for x in contents(o) or [] if x != a}
        missing = sorted(inside - set(known))
        fresh = steam.app_kinds(missing) if missing else {}
        kinds = {**known, **{a: (k.type, k.parent_app_id, now) for a, k in fresh.items()}}

        plan: list[tuple[int, int, PurchaseOption, str, list[int] | None]] = []
        for app, opts in per_app.items():
            for position, option in enumerate(opts):
                if option.package_id and option.package_id == defaults.get(app):
                    plan.append((app, position, option, "default", None))
                    continue
                items = contents(option)
                plan.append((app, position, option, _role(app, items, kinds), items))

        editions = [(app, option) for app, _, option, role, _ in plan if role == "edition"]
        products = itad.lookup_ids(sorted({_key(o) for _, o in editions})) if editions else {}
        verdicts = _verify(writer, steam, itad, metadata, editions, products, per_app, previous, now, max_age)
        exts = sorted({e for e in products.values() if e})
        try:
            deals = {k: v.steam_deals for k, v in itad.price_summaries(exts, region).items()} if exts else {}
        except SourceError:
            deals = {}                              # unknown, not zero (constitution I)
    except SourceError as exc:
        summary["source_error"] = True
        summary["seconds"] = round(time.monotonic() - started, 1)
        return OptionRun([], summary, [f"購買選項步驟的來源錯誤，沿用上一次的紀錄：{exc}"])

    rows: list[NewPurchaseOption] = []
    for app, position, option, role, items in plan:
        kind, option_id = _key(option)
        ext = products.get((kind, option_id)) if role == "edition" else None
        verdict, verified_by, verified_at, aliases = verdicts.get((app, kind, option_id), (None, None, None, None))
        others = [a for a in items or [] if a != app]
        rows.append(NewPurchaseOption(
            app_id=app, kind=kind, option_id=option_id, name=option.name, original_cents=option.original_cents,
            final_cents=option.final_cents, position=position, is_default=role == "default", role=role,
            contents=([{"app_id": app, "type": None, "parent_app_id": None}] if app in (items or []) else [])
            + [{"app_id": a, "type": kinds[a][0], "parent_app_id": kinds[a][1]} for a in others if a in kinds]
            if items is not None else None,
            contents_checked_at=min((kinds[a][2] for a in others if a in kinds), default=None),
            external_id=ext, verification=verdict.verification if verdict else None, verified_by=verified_by,
            verified_at=verified_at, reason_code=verdict.reason_code if verdict else None,
            reason_detail=verdict.reason_detail if verdict else None,
            warnings=list(verdict.warnings) if verdict else None, aliases=aliases,
            itad_steam_deals=deals.get(ext) if ext else None,
            bundle_discount_pct=option.bundle_discount_pct, before_bundle_cents=option.before_bundle_cents))
    summary["bundles"] = _bundle_prices(writer, steam, rows, alerts)
    writer.add_purchase_options(run_id, rows, checked_at=now)

    fetch: list[EditionFetch] = []
    for row in rows:
        summary["options"] += 1
        if row.role != "edition":
            continue
        summary["editions"] += 1
        if row.verification == "verified":
            summary["editions_verified"] += 1
            version = versions.get(row.app_id)
            default_ids = {version.history_id, version.external_id} if version else set()
            if row.external_id not in default_ids:
                fetch.append(EditionFetch(row.app_id, row.external_id, row.kind, row.option_id,
                                          chosen.get(row.app_id) == (row.kind, row.option_id)))
        elif row.verification == "rejected":
            ref = option_ref(row.kind, row.option_id)
            summary["rejected"].append({"app_id": row.app_id, "name": names[row.app_id], "option": ref,
                                        "reason": row.reason_code, "detail": row.reason_detail})
            before = next((r for r in previous.get(row.app_id, []) if (r["kind"], r["option_id"]) == (
                row.kind, row.option_id)), None)
            if before is None or before["verification"] != "rejected":
                alerts.append(f"{names[row.app_id]}：購買選項 {row.name or ref}（{ref}）核對未通過："
                              f"{rejection_text(row.reason_code, row.reason_detail)}；不能指定")
    tracked = {a for (a,) in writer.conn.execute(
        "SELECT app_id FROM wishlist_membership WHERE state IN ('in_wishlist', 'removed_tracking')")} | set(apps)
    _specified(summary, alerts, chosen, rows, tracked, names)
    summary["seconds"] = round(time.monotonic() - started, 1)
    return OptionRun(fetch, summary, alerts)


def _verify(writer, steam, itad, metadata, editions, products, per_app, previous, now, max_age):
    """(app, kind, id) -> (VerifyResult, verified_by, verified_at, aliases) for editions with an ITAD product."""
    results: dict[tuple, tuple] = {}
    pending = []
    for app, option in editions:
        kind, option_id = _key(option)
        ext = products.get((kind, option_id))
        if not ext:
            continue
        before = next((r for r in previous.get(app, []) if (r["kind"], r["option_id"]) == (kind, option_id)), None)
        if (before and before["external_id"] == ext and before["verification"] and before["verified_at"]
                and now - from_db(before["verified_at"]) <= max_age):
            verdict = VerifyResult(before["verification"], before["reason_code"],
                                   json.loads(before["warnings_json"]) if before["warnings_json"] else [],
                                   before["reason_detail"])
            results[(app, kind, option_id)] = (verdict, "cached", from_db(before["verified_at"]),
                                               json.loads(before["aliases_json"]) if before["aliases_json"] else None)
        else:
            pending.append((app, option, ext))
    if not pending:
        return results
    aliases = itad.reverse_lookup(sorted({ext for _, _, ext in pending}))
    subs = sorted({int(x[4:]) for _, _, ext in pending for x in aliases.get(ext) or []
                   if x.startswith("sub/") and x[4:].isdigit()})
    packages = steam.version_packages(subs) if subs else {}
    extra = sorted({a for p in packages.values() for a in p.app_ids} - {app for app, _, _ in pending})
    kinds = steam.app_kinds(extra) if extra else {}
    for app, option, ext in pending:
        kind, option_id = _key(option)
        prices = {o.package_id: (o.original_cents, o.final_cents) for o in per_app[app] if o.package_id}
        alias_list = aliases.get(ext) or []
        verdict = verify_version(app, alias_list, default_package=option.package_id or -1, options=prices,
                                 packages=packages, kinds=kinds, metadata=metadata, option=option_ref(kind, option_id),
                                 reference_price=None if option.package_id else (option.original_cents,
                                                                                 option.final_cents))
        results[(app, kind, option_id)] = (verdict, "version-check", now, alias_list)
    return results


def _bundle_prices(writer: StoreWriter, steam, rows: list[NewPurchaseOption], alerts: list[str]) -> dict[str, Any]:
    """Feature 010 (research R3, R6): bundles holding >= 2 wishlist games get each content's current price and name
    (one GetItems for all of them), written into their rows' contents. A failed request leaves the prices unknown
    (None); the rest of the step goes on (constitution III). The formula check uses these prices for every content."""
    started = time.monotonic()
    wishlist = {a for (a,) in writer.conn.execute("SELECT app_id FROM wishlist_membership WHERE state = 'in_wishlist'")}
    unknown = {r.option_id for r in rows if r.kind == "bundle" and r.contents is None}
    chosen = {r.option_id: r for r in rows if r.kind == "bundle" and r.contents is not None
              and sum(c["app_id"] in wishlist for c in r.contents) >= 2}
    apps = sorted({c["app_id"] for r in chosen.values() for c in r.contents})
    prices: dict = {}
    failed = False
    if apps:
        try:
            if not isinstance(steam, ContentPriceSource):
                raise SourceError("來源不支援查詢組合包內容的現價")
            prices = steam.content_prices(apps)
        except SourceError as exc:
            failed = True
            alerts.append(f"組合包內容的現價無法取得，組合包比較今天為未知：{exc}")
    for r in rows:
        if r.kind == "bundle" and r.option_id in chosen:
            for c in r.contents:
                quote = prices.get(c["app_id"])
                c["final_cents"] = quote.final_cents if quote else None
                if quote and quote.name:
                    c["name"] = quote.name
    mismatch, prices_unknown, pure = [], 0, 0
    for bundle_id, r in chosen.items():
        inside = [c["app_id"] for c in r.contents if c["app_id"] in wishlist]
        pure += all(c["app_id"] in wishlist or c.get("parent_app_id") in inside for c in r.contents)
        check = check_formula(r.final_cents, r.bundle_discount_pct, [c["final_cents"] for c in r.contents])
        if any(c["final_cents"] is None for c in r.contents):
            prices_unknown += 1
        if check["status"] == "mismatch":
            mismatch.append({"id": bundle_id, "name": r.name, "price_cents": r.final_cents,
                             "expected_cents": check["expected_cents"]})
            alerts.append(f"組合包 {r.name or bundle_id}（bundle/{bundle_id}）：{check['text']}，今天不給組合包建議")
    if failed:
        prices_unknown = len(chosen)
    return {"wishlist_bundles": len(chosen), "pure": pure, "mixed": len(chosen) - pure,
            "contents_unknown": len(unknown - set(chosen)), "prices_unknown": prices_unknown,
            "check_mismatch": mismatch, "seconds": round(time.monotonic() - started, 1)}


def _specified(summary: dict, alerts: list[str], chosen: Mapping[int, tuple[str, int]],
               rows: list[NewPurchaseOption], tracked: set[int], names: Mapping[int, str]) -> None:
    """Update summary of the user's choices (FR-017), resolved with the same rule as the forecast core. A tracked
    app without purchase options today (unreleased, free) has nothing to choose from: not-offered."""
    by_app: dict[int, list[NewPurchaseOption]] = {}
    for row in rows:
        by_app.setdefault(row.app_id, []).append(row)
    for app, choice in sorted(chosen.items()):
        ref = option_ref(*choice)
        if app not in tracked:
            summary["specified"]["ignored"].append({"app_id": app, "option": ref})
            alerts.append(ignored_warning(app))
            continue
        result = resolve_choice(by_app.get(app, []), choice)
        entry = {"app_id": app, "name": names.get(app, str(app)), "option": ref}
        if result.active:
            summary["specified"]["active"].append(entry)
        else:
            summary["specified"]["fallback"].append({**entry, "reason": result.code, "detail": result.detail})
            alerts.append(f"{names.get(app, app)}：{result.fallback_text(requested_label(by_app.get(app), choice))}")
