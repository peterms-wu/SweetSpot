"""P3: what adopting an official sale does on real data (read-only on the main folder's database).

(a) Value: for every seasonal sale 2019-2027, the estimate the program would have made from the earlier official
    sales (calendar.estimate_sale) vs the official dates.
(b) Adoption: live decisions with the calendar as today vs with an extra official 2027 autumn sale, for two dates:
    A = the same dates as the stored estimate (only the label changes), B = one week earlier than the estimate.
(c) Leakage: PriceStore.sales(as_of) for past moments is identical with and without the adopted sale, and a backtest
    dataset's calendar hash changes only through calendar_events() (what scoring uses).

Usage: uv run python specs/012-sale-calendar-sync/prototype/p3_adopt.py
"""

import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from steamsage import calendar
from steamsage.config import load_config
from steamsage.decision.contract import batch_to_dict
from steamsage.decision.engine import run_decisions
from steamsage.forecast.models import current_model
from steamsage.store import query
from steamsage.store.query import PriceStore

from p1_parse import SOURCE

MAIN = Path(r"〈專案資料夾〉")


def value_of_official_dates(events: list[calendar.SaleEvent]) -> None:
    print("(a) estimate (last year's sale, weekday-aligned) vs official, seasonal sales 2019-2027:")
    official = [e for e in events if e.kind == "seasonal" and e.year >= 2019]
    exact = 0
    for e in official:
        est = calendar.estimate_sale([x for x in events if x.start < e.start], e.season, e.year)
        if est is None:
            continue
        ds, de = (e.start - est.start).days, (e.end - est.end).days
        exact += ds == 0 and de == 0
        if ds or de:
            print(f"    {calendar.label(e):<9} official {e.start:%Y-%m-%d}..{e.end:%m-%d}  estimate "
                  f"{est.start:%Y-%m-%d}..{est.end:%m-%d}  start {ds:+d} d, end {de:+d} d")
    print(f"    exact: {exact}/{len(official)}")


def decisions(store: PriceStore, config, now: datetime) -> dict[int, dict]:
    batch = run_decisions(store, store.wishlist_apps(), now, current_model(), config.preferences, now=now,
                          official=False, choices=config.purchase_options)
    return {d["app_id"]: d for d in batch_to_dict(batch)["decisions"]}


def adopt(events, sale: calendar.SaleEvent):
    """Toml events + an adopted official sale; estimates for the same season/year are hidden (the real flow
    supersedes them in refresh_estimates)."""
    merged = sorted(events + [sale], key=lambda e: e.start)
    original = query.current_estimates

    def estimates(conn):
        return [e for e in original(conn) if (e.year, e.season) != (sale.year, sale.season)]
    return merged, estimates


def diff(base: dict, other: dict) -> dict:
    out = {"group": 0, "sweet_label": 0, "sweet_status": 0, "sweet_dates": 0, "sweet_twd": 0, "any": 0}
    for app_id, d in base.items():
        o = other[app_id]
        sp, op = d.get("sweet_point") or {}, o.get("sweet_point") or {}
        flags = {"group": d["group"] != o["group"], "sweet_label": sp.get("label") != op.get("label"),
                 "sweet_status": sp.get("status") != op.get("status"),
                 "sweet_dates": (sp.get("start"), sp.get("end")) != (op.get("start"), op.get("end")),
                 "sweet_twd": d.get("sweet_twd") != o.get("sweet_twd")}
        for k, v in flags.items():
            out[k] += v
        out["any"] += any(flags.values())
    return out


def main() -> None:
    now = datetime.now(UTC)
    config, _ = load_config(MAIN / "steamsage.toml")
    store = PriceStore.open(config.db_path, MAIN / "data" / "steam_sales.toml")
    try:
        events = list(store.calendar_events())
        value_of_official_dates(events)

        started = time.monotonic()
        today = decisions(store, config, now)
        print(f"\n(b) {len(today)} decisions with today's calendar ({time.monotonic() - started:.1f} s)")
        saved = query.current_estimates
        past = [datetime(2019, 1, 1, tzinfo=UTC) + timedelta(days=30 * i) for i in range(94)]
        for year, season in ((2026, "winter"), (2027, "spring"), (2027, "summer")):
            official = next(e for e in events if (e.year, e.season) == (year, season))
            without = [e for e in events if e is not official]
            est = calendar.estimate_sale(without, season, year)
            label = calendar.label(official)
            # before: the sale is not in the file yet, only estimated (what users see until someone edits the toml)
            store._calendar = without
            query.current_estimates = lambda conn, est=est: [e for e in saved(conn)
                                                             if (e.year, e.season) != (year, season)] + [est]
            before = decisions(store, config, now)
            before_sales = {m: store.sales(m) for m in past}
            on_sale = [a for a, d in before.items() if (d.get("sweet_point") or {}).get("label") == label]
            print(f"  {label}: official {official.start:%Y-%m-%d}..{official.end:%m-%d}, estimate "
                  f"{est.start:%Y-%m-%d}..{est.end:%m-%d}; games whose sweet point is {label}: {len(on_sale)}")
            variants = {"A official = today's file": official.start,
                        "B official one week later": official.start + timedelta(days=7)}
            for name, start in variants.items():
                sale = replace(official, source=SOURCE, start=start, end=start + (official.end - official.start))
                merged, estimates = adopt(without, sale)
                store._calendar = merged
                query.current_estimates = estimates
                after = decisions(store, config, now)
                leaks = sum(before_sales[m] != store.sales(m) for m in past)
                statuses = sorted({str((after[a].get("sweet_point") or {}).get("status")) for a in on_sale})
                print(f"    {name}: changed vs estimate-only {diff(before, after)}; status now {statuses}; "
                      f"past moments with a different sales list {leaks}/{len(past)}")
            store._calendar = events
            query.current_estimates = saved
    finally:
        store.close()


if __name__ == "__main__":
    main()
