"""Synthetic curves, sale points and forecasts for feature 003 decision tests (tasks T002).

Curves follow the baseline model's shape: a per-sale share p(d) per level, cumulative 1 - (1 - p)^k at the k-th
sale. Shares are given as {level: p}; levels not listed inherit the share of the next deeper listed level, or 0
beyond the deepest one, so the curve is always non-increasing with deeper discounts.
"""

from collections.abc import Mapping
from datetime import datetime, timedelta

from sweetspot.forecast.contract import LEVELS, Forecast
from sweetspot.forecast.salepoints import SalePoint
from sweetspot.store.writer import NewObservation
from tests.forecast_builders import dt

AS_OF = dt("2026-09-25")
SEASON_CYCLE = (("autumn", "秋特", (9, 29)), ("winter", "冬特", (12, 17)), ("spring", "春特", (3, 18)),
                ("summer", "夏特", (6, 24)))


def shares(spec: Mapping[int, float]) -> list[float]:
    """Per-level share list from {level: p}; e.g. {50: 1.0, 80: 1/7} → 1.0 up to -50%, 1/7 for -55..-80%."""
    out = []
    for d in LEVELS:
        deeper = [lv for lv in spec if lv >= d]
        out.append(spec[min(deeper)] if deeper else 0.0)
    return out


def curve_from_shares(spec: Mapping[int, float], n_points: int) -> tuple[tuple[float, ...], ...]:
    per_sale = shares(spec)
    return tuple(tuple(1.0 - (1.0 - p) ** k for p in per_sale) for k in range(1, n_points + 1))


def points(n: int, first_year: int = 2026) -> tuple[SalePoint, ...]:
    """n seasonal sales starting with the 2026 autumn sale, one per season (roughly every 3 months)."""
    out = []
    year = first_year
    for i in range(n):
        season, zh, (month, day) = SEASON_CYCLE[i % 4]
        if i and season == "spring":
            year += 1
        start = datetime(year, month, day, 17, tzinfo=AS_OF.tzinfo)
        end = start + timedelta(days=7 if season in ("autumn", "spring") else 14)
        out.append(SalePoint(index=i + 1, season=season, year=year, label=f"{year} {zh}", start=start, end=end,
                             status="announced" if i < 4 else "estimated", basis=None))
    return tuple(out)


def make_forecast(app_id: int = 1, *, spec: Mapping[int, float] | None = None, n_points: int = 20,
                  confidence: str = "normal", regular_cents: int | None = 50000, max_cut: int | None = None,
                  name: str | None = None, reasons: tuple[str, ...] = ("理由",)) -> Forecast:
    spec = {50: 1.0} if spec is None else spec
    pts = points(n_points)
    if max_cut is None:
        max_cut = max((lv for lv, p in spec.items() if p > 0), default=0)
    return Forecast(app_id=app_id, name=name or f"Game {app_id}", status="ok", confidence=confidence, reasons=reasons,
                    evidence={"regions": ["TW"], "sales_used": 7, "max_cut": max_cut, "population_sales": None},
                    regular_price_cents=regular_cents, points=pts, probabilities=curve_from_shares(spec, n_points))


def steam_current(app_id: int, when: str, price_cents: int, regular_cents: int) -> NewObservation:
    """A steam-current snapshot row (for GameSpec.extra_tw)."""
    moment = dt(when)
    cut = round(100 * (regular_cents - price_cents) / regular_cents) if regular_cents else 0
    return NewObservation(app_id=app_id, source="steam-current", region="TW", currency="TWD",
                          regular_cents=regular_cents, price_cents=price_cents, cut_pct=cut, observed_at=moment,
                          raw_observed_at=None, retrieved_at=moment, is_tracking_start=False)


# --- decision contract dicts for report tests (tasks T017) -------------------------------------------------

def decision(app_id: int, group: str = "soon", *, name: str | None = None, regular: int = 50000,
             current: int | None = 50000, sweet_pct: int = 50, p_min_pct: int = 60, sweet_index: int = 1,
             confidence: str = "normal", tags: tuple[str, ...] = (), change=None, source: str = "steam-current"):
    """A Decision whose numbers are consistent with its own fields (not with any rule run)."""
    from sweetspot.decision.contract import Decision
    from sweetspot.decision.prices import CurrentPrice
    from sweetspot.decision.rule import LadderRow, price_cents

    pts = points(max(sweet_index, 1) + 1)
    ladder = tuple(LadderRow(p.index, p.label, sweet_pct if p.index == sweet_index else sweet_pct - 10,
                             price_cents(regular, sweet_pct if p.index == sweet_index else sweet_pct - 10),
                             0.537 if p.index == sweet_index else 1.0) for p in pts[:sweet_index])
    cur = CurrentPrice(current, regular, None if current is None else round(100 - 100 * current / regular), source,
                       AS_OF, AS_OF, False, regular, False)
    return Decision(app_id=app_id, name=name or f"Game {app_id}", group=group, status="ok", status_reason=None,
                    confidence=confidence, basis="own", horizon_points=len(pts), regular_cents=regular, current=cur,
                    p_min_pct=p_min_pct, p_min_cents=price_cents(regular, p_min_pct), gap_pp=10,
                    tolerance_cents=5000, tolerance_bound=None, target_cents=price_cents(regular, sweet_pct),
                    sweet_pct=sweet_pct, sweet_cents=price_cents(regular, sweet_pct), sweet_point=pts[sweet_index - 1],
                    sweet_probability=0.537, ladder=ladder, tags=tags, reasons=("第一個原因", "第二個原因"), change=change)


def contract_dict(decisions, *, official: bool = True, comparison=None, rule_backtest=None, data_refresh=None,
                  preferences=None, rule: str = "1.0.0") -> dict:
    from sweetspot.config import Preferences
    from sweetspot.decision.contract import DecisionBatch, batch_to_dict
    from sweetspot.decision.rule import RULE_NAME, RULES
    from sweetspot.forecast.contract import ForecastBatch, ModelInfo

    forecast = ForecastBatch(model=ModelInfo("seasonal-freq", "1.0.0", {"min_sales": 2, "history": "TW"}),
                             as_of=AS_OF, data_cutoff=AS_OF, generated_at=AS_OF, levels=LEVELS,
                             confidence_levels={"normal": "a", "low": "b"}, games=())
    batch = DecisionBatch(official=official, as_of=AS_OF, generated_at=AS_OF,
                          rule={"name": RULE_NAME, "version": rule, "constants": dict(RULES[rule]["constants"])},
                          preferences=preferences or Preferences().for_rule(rule),
                          data_refresh=data_refresh or {"update_exit": None, "note": None},
                          rule_backtest=rule_backtest, comparison=comparison, decisions=tuple(decisions),
                          forecast=forecast)
    return batch_to_dict(batch)


# --- feature 005: waiting-cost rule (tasks T001) ------------------------------------------------------------

MONTH = timedelta(days=365 / 12)


def timed_points(as_of: datetime, spans) -> tuple[SalePoint, ...]:
    """Sale points whose start/end lie `(start_months, end_months)` after as_of (months of 365/12 days)."""
    out = []
    year = as_of.year
    for i, (start, end) in enumerate(spans):
        season, zh, _ = SEASON_CYCLE[i % 4]
        if i and season == "spring":
            year += 1
        out.append(SalePoint(index=i + 1, season=season, year=year, label=f"{year} {zh}",
                             start=as_of + start * MONTH, end=as_of + end * MONTH, status="estimated", basis=None))
    return tuple(out)


def step_curve(rows) -> tuple[tuple[float, ...], ...]:
    """A curve from one {level: cumulative probability} per sale point; unlisted levels take the value of the next
    deeper listed level (0 beyond the deepest), so every row is non-increasing with depth."""
    curve = tuple(tuple(shares(row)) for row in rows)
    for before, after in zip(curve, curve[1:]):
        assert all(a >= b for a, b in zip(after, before)), "cumulative probabilities must not decrease over time"
    return curve


def prefs(**kw):
    from sweetspot.config import Preferences
    return Preferences(**{"wait_cost_twd": 20, **kw})


def v3_decision(app_id: int, *, rows=None, regular: int = 100000, current: int | None = 100000, c: int = 20,
                name: str | None = None, tags: tuple[str, ...] = (), change=None, spans=None):
    """A rule 3.0.0 Decision made by the real rule from a step curve (tasks T017)."""
    from sweetspot.decision.contract import Decision
    from sweetspot.decision.prices import CurrentPrice
    from sweetspot.decision.rule import decide

    pts = timed_points(AS_OF, spans or [(1.0, 1.5), (4.0, 4.5)])
    curve = step_curve(rows or [{50: 0.6}, {50: 0.9}])
    r = decide(probabilities=curve, points=pts, as_of=AS_OF, confidence="normal", evidence_max_cut=None,
               regular_cents=regular, current_price_cents=current, regular_mismatch=False, no_history=None,
               preferences=prefs(wait_cost_twd=c), rule="3.0.0")
    cut = None if current is None else (regular - current) * 100 // regular
    cur = CurrentPrice(current, regular, cut, "steam-current", AS_OF, AS_OF, False, regular, False)
    return Decision(app_id=app_id, name=name or f"Game {app_id}", group=r.group, status="ok", status_reason=None,
                    confidence=r.confidence, basis=r.basis, horizon_points=r.horizon_points, regular_cents=regular,
                    current=cur, p_min_pct=r.p_min_pct, p_min_cents=r.p_min_cents, gap_pp=None,
                    tolerance_cents=None, tolerance_bound=None, target_cents=None, sweet_pct=r.sweet_pct,
                    sweet_cents=r.sweet_cents, sweet_point=pts[r.sweet_index - 1],
                    sweet_probability=r.sweet_probability, ladder=r.ladder, tags=tags + r.tags,
                    reasons=("第一個原因",), change=change, wait_options=r.wait_options,
                    deadline_point=pts[r.deadline_index - 1] if r.deadline_index else None, expected=r.expected)


# --- feature 010: bundles holding several wishlist games (tasks T002) ----------------------------------------

def bundle_record(app_id: int, option_id: int, contents, *, final_cents: int, discount: int | None = 10,
                  name: str | None = None, before_cents: int | None = None, checked_at: datetime = AS_OF):
    """A purchase-option row of a bundle as `PriceStore.purchase_options` returns it. `contents` lists
    (app_id, type, parent_app_id) or (app_id, type, parent_app_id, final_cents); the app itself has type None."""
    from sweetspot.store.query import OptionRecord

    rows = []
    for c in contents:
        row = {"app_id": c[0], "type": c[1], "parent_app_id": c[2]}
        if len(c) > 3:
            row["final_cents"] = c[3]
        rows.append(row)
    return OptionRecord(app_id=app_id, checked_at=checked_at, kind="bundle", option_id=option_id,
                        name=name or f"Bundle {option_id}", original_cents=final_cents, final_cents=final_cents,
                        position=1, is_default=False, role="other-games", external_id=None, verification=None,
                        verified_at=None, reason_code=None, reason_detail=None, itad_steam_deals=None,
                        bundle_discount_pct=discount, before_bundle_cents=before_cents, contents=rows)


def e33_dispatch():
    """research R0.3 (2026-09-27): E33 is 現在買 at NT$790 (-20%), Dispatch waits for -30% in the 2026 winter sale."""
    e33 = decision(1903340, "now", name="光與影：33號遠征隊", regular=98800, current=79000, sweet_pct=20,
                   p_min_pct=30, sweet_index=1)
    dispatch = decision(2592160, "wait", name="Dispatch", regular=48800, current=48800, sweet_pct=30, p_min_pct=40,
                        sweet_index=2)
    forecasts = {1903340: make_forecast(1903340, spec={20: 0.826, 25: 0.3}, regular_cents=98800),
                 2592160: make_forecast(2592160, spec={20: 0.881, 25: 0.441}, regular_cents=48800)}
    record = bundle_record(1903340, 74895, [(1903340, None, None), (2592160, 0, None)], final_cents=115000,
                           name="Clair Obscur: Expedition 33 x Dispatch", before_cents=147600)
    return [e33, dispatch], forecasts, record


def dave_miside():
    """research R0.3: both sweet points are the 2026 autumn sale; the joint probability is just over 50%."""
    dave = decision(1868140, "soon", name="DAVE THE DIVER", regular=35000, current=35000, sweet_pct=45, p_min_pct=55,
                    sweet_index=1)
    miside = decision(2527500, "soon", name="MiSide", regular=26800, current=26800, sweet_pct=20, p_min_pct=30,
                      sweet_index=1)
    forecasts = {1868140: make_forecast(1868140, spec={45: 0.778, 50: 0.506}, regular_cents=35000),
                 2527500: make_forecast(2527500, spec={20: 0.659, 25: 0.3}, regular_cents=26800)}
    record = bundle_record(1868140, 77855, [(1868140, None, None), (2527500, 0, None)], final_cents=55600,
                           name="DAVE THE DIVER x MiSide", before_cents=61800)
    return [dave, miside], forecasts, record
