"""A small database and hand-written decision records for the post-sale comparison (feature 013, tasks T001).

Seven games around the 2026 autumn sale (2026-10-01T17:00Z – 2026-10-08T17:00Z), regular price NT$500:

  A 1  0% → 60% in the sale              soon, sweet -50% at the autumn sale
  B 2  40% from 9/29, through the sale   now (discount already running at the record's as_of)
  C 3  0% → 50% in the sale; 50% again 10/20–10/27 (outside any seasonal sale)
                                          wait, sweet -50% at the winter sale (an early hit)
  D 4  user edition (option history 75% in the sale); the app's own history stays 0%
  E 5  history known only until 10/05     → no actual
  F 6  history 0% all sale, the option's daily rows show 33% (the Stellar Blade case, D2)
  G 7  no forecast in the record          → not scored

Records are plain dicts shaped like `steamsage.decision/2`, holding only what the comparison reads.
"""

from datetime import timedelta
from pathlib import Path

from sweetspot.decision import records
from sweetspot.forecast.contract import LEVELS
from sweetspot.store.query import OPTION_HISTORY_SOURCE
from tests.forecast_builders import BASIC_CALENDAR, GameSpec, Sale, add_history, add_purchase_options, build_db, dt

AUTUMN = Sale("autumn", 2026, "2026-10-01T17:00", "2026-10-08T17:00")
WINTER = Sale("winter", 2026, "2026-12-17T18:00", "2027-01-04T18:00")
CALENDAR = [*BASIC_CALENDAR, AUTUMN, WINTER]
AS_OF = dt("2026-09-30T18:31:37")
AS_OF_TEXT = "2026-09-30T18:31:37Z"
RECORD = "20260930T183137Z.json.gz"
TODAY = dt("2026-10-12")
REGULAR = 50000

AUTUMN_POINT = {"index": 1, "label": "2026 秋特", "season": "autumn", "year": 2026, "start": "2026-10-01T17:00:00Z",
                "end": "2026-10-08T17:00:00Z", "status": "announced"}
WINTER_POINT = {"index": 2, "label": "2026 冬特", "season": "winter", "year": 2026, "start": "2026-12-17T18:00:00Z",
                "end": "2027-01-04T18:00:00Z", "status": "announced"}
# the record's daily runs during the sale (Taipei 02:31-02:35)
DURING_AS_OF = ["2026-10-01T18:35:01Z", "2026-10-02T18:31:10Z", "2026-10-03T18:31:22Z", "2026-10-04T18:31:05Z",
                "2026-10-05T18:31:44Z", "2026-10-06T18:31:12Z", "2026-10-07T18:31:39Z"]

EDITION = "itad-ed4"
F_OPTION = {"kind": "sub", "id": 6001, "name": "Game 6"}
D_OPTION = {"kind": "sub", "id": 4001, "name": "Game 4 Deluxe"}

HISTORY = {
    1: [("2026-01-01", 0), ("2026-10-01T17:00", 60), ("2026-10-08T17:00", 0)],
    2: [("2026-01-01", 0), ("2026-09-29", 40), ("2026-10-08T17:00", 0)],
    3: [("2026-01-01", 0), ("2026-10-01T17:00", 50), ("2026-10-08T17:00", 0), ("2026-10-20", 50), ("2026-10-27", 0)],
    4: [("2026-01-01", 0)],
    5: [("2026-01-01", 0), ("2026-10-01T17:00", 50)],
    6: [("2026-01-01", 0)],
    7: [("2026-01-01", 0)],
}
KNOWN = {3: "2026-11-02", 4: "2026-10-10", 5: "2026-10-05", 6: "2026-10-10", 7: "2026-10-10"}


def daily_rows(option: dict, cut: int, days=range(7), *, start: str = "2026-10-01T18:30") -> list[tuple[str, dict]]:
    """(checked_at, option row) for one option seen at 02:30 Taipei on consecutive days."""
    first = dt(start)
    final = REGULAR * (100 - cut) // 100
    return [((first + timedelta(days=i)).strftime("%Y-%m-%dT%H:%M"),
             dict(kind=option["kind"], option_id=option["id"], name=option["name"], original_cents=REGULAR,
                  final_cents=final, role="default")) for i in days]


def review_db(path: Path, *, history: dict | None = None, known: dict | None = None, daily: dict | None = None) -> Path:
    """The seven games; `history`/`known` override rows per app; `daily` maps app → [(checked_at, option row)]
    (default: F's 33% rows)."""
    rows = {**HISTORY, **(history or {})}
    until = {**KNOWN, **(known or {})}
    games = [GameSpec(app, tw=tw, name=f"Game {app}", wishlist=True, release_date="2020-01-01",
                      known_until={"TW": until[app]} if app in until else {}) for app, tw in rows.items()]
    build_db(path, games, calendar=CALENDAR)
    add_history(path, 4, EDITION, tw=[("2026-01-01", 0), ("2026-10-01T17:00", 75), ("2026-10-08T17:00", 0)],
                fetched="2026-10-10", source=OPTION_HISTORY_SOURCE, fetch_source="itad-option")
    for app, steps in (daily if daily is not None else {6: daily_rows(F_OPTION, 33)}).items():
        for checked_at, row in steps:
            add_purchase_options(path, app, checked_at, [row])
    return path


def probs(rule: dict[int, float]) -> list[float]:
    """19 probabilities from {upper level: p}: each level takes the p of the smallest listed level >= it."""
    return [rule[min(k for k in rule if k >= d)] for d in LEVELS]


SEASONAL = {1: probs({60: 0.8, 95: 0.2}), 2: probs({40: 0.9, 95: 0.1}), 3: probs({50: 0.5, 95: 0.1}),
            4: probs({75: 0.7, 95: 0.1}), 5: probs({50: 0.6, 95: 0.1}), 6: probs({30: 0.6, 95: 0.1})}


def forecast_game(app: int, probabilities: list[float] | None = None, *, confidence: str = "normal",
                  points: tuple[dict, ...] = (AUTUMN_POINT, WINTER_POINT), status: str = "ok") -> dict:
    if status != "ok":
        return {"app_id": app, "name": f"Game {app}", "status": status, "confidence": None, "curve": None}
    p = probabilities if probabilities is not None else SEASONAL[app]
    rows = [p] + [[min(1.0, x + 0.05) for x in p] for _ in points[1:]]
    return {"app_id": app, "name": f"Game {app}", "status": status, "confidence": confidence,
            "curve": {"points": [dict(pt) for pt in points], "probabilities": rows}}


def decision(app: int, group: str, *, sweet_pct: int | None = 50, sweet_point: dict | None = None,
             current_cents: int | None = REGULAR, status: str = "ok", itad_id: str | None = None,
             source: str = "steam-default", option: dict | None = None, confidence: str = "normal",
             non_seasonal: dict | None = None) -> dict:
    ok = status == "ok"
    point = (sweet_point or AUTUMN_POINT) if ok else None
    return {
        "app_id": app, "name": f"Game {app}", "status": status, "status_reason": None if ok else "無法預測",
        "group": group if ok else "na", "confidence": confidence if ok else None,
        "regular_cents": REGULAR if ok else None,
        "sweet_pct": sweet_pct if ok else None,
        "sweet_cents": REGULAR * (100 - sweet_pct) // 100 if ok and sweet_pct is not None else None,
        "sweet_point": {k: point[k] for k in ("index", "label", "start", "end", "status")} if point else None,
        "sweet_probability": 0.6 if ok else None,
        "current": {"price_cents": current_cents, "regular_cents": REGULAR,
                    "cut_pct": None if current_cents is None else 100 - 100 * current_cents // REGULAR,
                    "source": "steam-current", "observed_at": AS_OF_TEXT} if ok else None,
        "version": {"itad_id": itad_id or f"itad-{app}", "source": source, "basis": "user" if source == "user" else "version",
                    "option": option or {"kind": "sub", "id": app * 1000 + 1, "name": f"Game {app}"}},
        "non_seasonal": non_seasonal,
    }


def default_decisions() -> list[dict]:
    return [decision(1, "soon", non_seasonal=NS[1]),
            decision(2, "now", current_cents=30000),
            decision(3, "wait", sweet_point=WINTER_POINT, non_seasonal=NS[3]),
            decision(4, "soon", sweet_pct=70, itad_id=EDITION, source="user", option=D_OPTION),
            decision(5, "soon"),
            decision(6, "soon", sweet_pct=30, option=F_OPTION),
            decision(7, "na", status="na")]


def ns_block(p30: list[float], p60: list[float] | None = None, p90: list[float] | None = None, *,
             earlier: dict | None = None) -> dict:
    """A decision's non_seasonal part: probabilities for 30/60/90 days × 19 levels."""
    return {"status": "ok", "confidence": "normal", "probabilities": [p30, p60 or p30, p90 or p60 or p30],
            "earlier": earlier}


EARLIER_C = {"horizon_days": 60, "probability": 0.68, "sale_label": "2026 冬特", "threshold": 0.5, "hit_rate": 0.736}
NS = {1: ns_block(probs({95: 0.2})), 3: ns_block(probs({50: 0.5, 95: 0.1}), earlier=EARLIER_C)}


BUNDLE_ID = 9001


def bundle_entry(*, grade: str = "pure", kind: str | None = "next-sale", discount: int = 10,
                 estimate_cents: int = 45000, price_cents: int = 90000) -> dict:
    """A record's bundle holding A (1) and C (3), shaped like decision.bundles: advice to buy it in the autumn sale
    at about NT$450 (A and C both at -50%: (25000 + 25000) × 0.9)."""
    advice = None if kind is None else {
        "status": "ok", "kind": kind, "estimate_cents": estimate_cents, "joint_probability": 0.4,
        "sale": {k: AUTUMN_POINT[k] for k in ("index", "label", "start", "end", "status")},
        "levels": [{"app_id": 1, "pct": 50, "cents": 25000, "probability": 0.8},
                   {"app_id": 3, "pct": 50, "cents": 25000, "probability": 0.5}]}
    return {"id": BUNDLE_ID, "name": "A x C", "grade": grade, "discount_pct": discount, "price_cents": price_cents,
            "contents": [{"app_id": 1, "name": "Game 1", "role": "wishlist", "price_cents": REGULAR},
                         {"app_id": 3, "name": "Game 3", "role": "wishlist", "price_cents": REGULAR}],
            "advice": advice, "plan": {"cents": 50000}}


def bundle_rows(final_cents: int, discount: int | None = 10, days=range(7)) -> list[tuple[str, dict]]:
    """The bundle's own daily rows during the sale (stored under app 1)."""
    first = dt("2026-10-01T18:30")
    return [((first + timedelta(days=i)).strftime("%Y-%m-%dT%H:%M"),
             dict(kind="bundle", option_id=BUNDLE_ID, name="A x C", original_cents=90000, final_cents=final_cents,
                  role="other-games", bundle_discount_pct=discount)) for i in days]


RULE_BACKTEST = {"hit_rate": {"soon": 0.924, "wait": 0.619, "low": 0.579}, "now_deeper_within_12m": 0.444,
                 "source": "docs/model/model-definition.md", "rule": "2.1.0", "date": "2026-09-25"}
NS_BACKTEST = {"brier": 0.1213, "brier_by_horizon": {"30": 0.1082, "60": 0.1338, "90": 0.1271},
               "earlier_hit_rate": 0.736, "source": "docs/model/model-definition.md", "date": "2026-09-25"}


def pre_sale_record(*, decisions: list[dict] | None = None, games: list[dict] | None = None, as_of: str = AS_OF_TEXT,
                    official: bool = True, bundles: list[dict] | None = None, schema: str = records.SCHEMA) -> dict:
    decisions = default_decisions() if decisions is None else decisions
    if games is None:
        games = [forecast_game(d["app_id"]) for d in decisions if d["status"] == "ok"]
        games += [forecast_game(d["app_id"], status=d["status"]) for d in decisions if d["status"] != "ok"]
    return {
        "schema": schema, "official": official, "as_of": as_of, "generated_at": as_of,
        "rule": {"name": "sweet-price", "version": "2.1.0"}, "bundle_rule": {"name": "bundle-advice", "version": "1.0.0"},
        "preferences": {"gap_boundary_pct": 75, "gap_pp_deep": 5, "gap_pp_shallow": 10, "soon_sales": 1,
                        "tolerance_max_twd": 100, "tolerance_min_twd": 30},
        "rule_backtest": RULE_BACKTEST,
        "non_seasonal": {"horizons_days": [30, 60, 90], "threshold": 0.5, "backtest": NS_BACKTEST},
        "forecast": {"model": {"name": "seasonal-record", "version": "1.1.0", "params": {}}, "games": games},
        "decisions": decisions, "bundles": bundles or [],
        "summary": {g: sum(d["group"] == g for d in decisions) for g in ("now", "soon", "wait", "low", "na")},
    }


def during_records(groups: dict[int, list[str | None]], *, days=range(7), official: bool = True) -> list[dict]:
    """One official record per sale day (index into DURING_AS_OF); groups[app][i] is the app's group that day,
    None leaves the app out of that record."""
    out = []
    for i in days:
        decisions = [{"app_id": app, "name": f"Game {app}", "status": "ok", "group": g[i]}
                     for app, g in sorted(groups.items()) if g[i] is not None]
        out.append({"schema": records.SCHEMA, "official": official, "as_of": DURING_AS_OF[i],
                    "generated_at": DURING_AS_OF[i], "decisions": decisions, "forecast": {"games": []}, "bundles": []})
    return out


EARLY = {3: ["wait", "now", "now", "now", "now", "now", "now"]}


def write_records(directory: Path, items: list[dict]) -> list[Path]:
    return [records.write_record(directory, data) for data in items]
