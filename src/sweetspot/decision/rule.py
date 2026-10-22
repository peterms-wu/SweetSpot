"""Sweet-price rule `sweet-price` (docs/model/model-definition.md, 決策規則; research R1).

A pure function of one forecast curve, the TW regular and current price and the user's preferences. All money is
integer cents and every price comparison is done multiplied out, so boundaries such as "the regular price equals
the target" are exact. The rule never reads the database or the clock.

3.0.0 (feature 005 research R1-R4) replaces the tolerance with a waiting cost: every option "target d, wait at
most until sale K" gets an expected saving and an expected wait from the cumulative curve; the one with the
highest saving - cost x wait wins. Probability-weighted amounts are rounded to whole cents before comparing.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from sweetspot.config import Preferences
from sweetspot.forecast.contract import LEVELS
from sweetspot.forecast.salepoints import SalePoint
from sweetspot.timeutil import add_months

RULE_NAME = "sweet-price"
P_MIN_THRESHOLD = 0.5          # rule constant: P_min = deepest level with cumulative probability >= 0.5
TIMING_THRESHOLD = 0.5         # rule constant: the sweet sale = first sale where P(>= target) >= 0.5
LOW_CONFIDENCE_MONTHS = 12     # rule constant: low confidence only looks at sales ending within 12 months
STALE_HOURS = 24               # rule constant: a current price confirmed longer ago is marked stale
_V1: dict[str, Any] = {"p_min_threshold": P_MIN_THRESHOLD, "timing_threshold": TIMING_THRESHOLD,
                       "low_confidence_months": LOW_CONFIDENCE_MONTHS, "stale_hours": STALE_HOURS}
# 2.0.0 (feature 004 research R5): P_min and the sweet sale only look at sales ending within 12 months, for every
# game. 1.0.0 (normal confidence: the whole curve, up to 5 years) stays runnable for side-by-side backtests only.
P_MIN_MONTHS = 12
# 3.0.0 (feature 005): rule constants of the waiting-cost choice (research R1, R2).
MISS_PRICE = "regular"         # rule constant: a target not reached by the deadline is bought at the regular price
MONTH_DAYS = 365 / 12          # rule constant: months of waiting = days / (365 / 12)
_V2 = {**_V1, "p_min_months": P_MIN_MONTHS}
_V3 = {**_V2, "miss_price": MISS_PRICE, "month_days": MONTH_DAYS}
# 2.1.0 / 3.1.0 (feature 006 spec FR-018): 2.0.0 / 3.0.0 plus one data-quality condition for low confidence, "the
# price history stopped updating" (ITAD no longer tracks the product). The flag never occurs in backtest data, so
# the rule backtest is identical case by case (constitution 1.2.0, principle IV exception).
RULES: dict[str, dict[str, Any]] = {
    "1.0.0": {"constants": _V1, "p_min_months": None, "kind": "tolerance"},
    "2.0.0": {"constants": _V2, "p_min_months": P_MIN_MONTHS, "kind": "tolerance"},
    "2.1.0": {"constants": {**_V2, "history_stopped_low": True}, "p_min_months": P_MIN_MONTHS, "kind": "tolerance"},
    "3.0.0": {"constants": _V3, "p_min_months": P_MIN_MONTHS, "kind": "wait-cost"},
    "3.1.0": {"constants": {**_V3, "history_stopped_low": True}, "p_min_months": P_MIN_MONTHS, "kind": "wait-cost"},
}
CURRENT_RULE = "2.1.0"      # feature 006 (2026-09-26); 2.0.0 was adopted with seasonal-record in feature 004
RULE_VERSION = CURRENT_RULE
CONSTANTS: dict[str, Any] = RULES[CURRENT_RULE]["constants"]


def rule_spec(version: str | None) -> dict[str, Any]:
    version = version or CURRENT_RULE
    if version not in RULES:
        raise ValueError(f"未知的規則版本：{version}（可用：{', '.join(RULES)}）")
    return RULES[version]


# Rule backtest figures quoted by the report (003 FR-026, FR-034), one entry per rule + model combination
# (004 research R9). Copied from `sweetspot backtest-rule` on the full TW dataset and written to
# docs/model/model-definition.md; tests check the two agree.
RULE_BACKTESTS: tuple[dict[str, Any], ...] = (
    {"rule": "1.0.0", "model": {"name": "seasonal-freq", "version": "1.0.0", "params": {"min_sales": 2, "history": "TW"}},
     "date": "2026-09-25", "region": "TW", "window_months": 12,
     "hit_rate": {"soon": 0.936, "wait": 0.875, "low": 0.202},
     "now_deeper_within_12m": 0.486, "wait_cost_twd": None,
     "source": "docs/model/model-definition.md"},
    {"rule": "2.0.0", "model": {"name": "seasonal-record", "version": "1.0.0",
                                "params": {"min_sales": 1, "half_life": 2, "hazard_history": "TW+US"}},
     "date": "2026-09-25", "region": "TW", "window_months": 12,
     "hit_rate": {"soon": 0.923, "wait": 0.625, "low": 0.059},
     "now_deeper_within_12m": 0.432, "wait_cost_twd": None,
     "source": "docs/model/model-definition.md"},
    # feature 006 T043: rerun at the same cutoff, identical to 2.0.0 case by case (82,552 cases)
    {"rule": "2.1.0", "model": {"name": "seasonal-record", "version": "1.0.0",
                                "params": {"min_sales": 1, "half_life": 2, "hazard_history": "TW+US"}},
     "date": "2026-09-25", "region": "TW", "window_months": 12,
     "hit_rate": {"soon": 0.923, "wait": 0.625, "low": 0.059},
     "now_deeper_within_12m": 0.432, "wait_cost_twd": None,
     "source": "docs/model/model-definition.md"},
    # feature 008 T032: the current model since 2026-09-27, full TW dataset d493ac02, cutoff 2026-09-25
    {"rule": "2.1.0", "model": {"name": "seasonal-record", "version": "1.1.0",
                                "params": {"min_sales": 1, "half_life": 2, "hazard_history": "TW+US",
                                           "low_base": "new-split", "shrink": 0.5}},
     "date": "2026-09-25", "region": "TW", "window_months": 12,
     "hit_rate": {"soon": 0.924, "wait": 0.619, "low": 0.579},
     "now_deeper_within_12m": 0.444, "wait_cost_twd": None,
     "source": "docs/model/model-definition.md"},
)


def _same_model(entry: Mapping[str, Any], rule: str, model: Mapping[str, Any]) -> bool:
    m = entry["model"]
    return entry["rule"] == rule and (m["name"], m["version"], dict(m["params"])) == \
        (model["name"], model["version"], dict(model["params"]))


def lookup_backtest(rule: str, model: Mapping[str, Any], wait_cost_twd: int | None = None) -> dict[str, Any] | None:
    """The figures for this exact rule version, model (name, version, params) and, for a waiting-cost rule, c
    (005 research R8); None: no number is quoted."""
    uses_cost = RULES.get(rule, {}).get("kind") == "wait-cost"
    for entry in RULE_BACKTESTS:
        if _same_model(entry, rule, model) and (not uses_cost or entry.get("wait_cost_twd") == wait_cost_twd):
            return dict(entry)
    return None


def backtested_costs(rule: str, model: Mapping[str, Any]) -> list[int]:
    """The waiting costs this rule and model were backtested with (to say which c a figure belongs to)."""
    return sorted(e["wait_cost_twd"] for e in RULE_BACKTESTS
                  if _same_model(e, rule, model) and e.get("wait_cost_twd") is not None)


class DecisionError(ValueError):
    """The rule cannot produce a decision for this game; it becomes a decision-error, others are unaffected."""


@dataclass(frozen=True)
class WaitOption:
    """One row of the 3.0.0 waiting table (005 data-model): buy now (deadline_index 0), or the best target when
    waiting at most until that sale. Money in integer cents; None where the row has no target level."""

    deadline_index: int                  # 0 = buy now; k = wait at most until the k-th sale
    deadline_label: str | None
    target_pct: int | None
    target_cents: int | None             # the target's price; the base price on the buy-now row
    reach_probability: float | None      # F_K(target): reached by the end of the deadline sale
    likely_index: int | None             # first sale with F_i(target) >= 0.5, else the deadline (research R3)
    likely_label: str | None
    likely_probability: float | None
    expected_saving_cents: int | None    # base price - expected price paid; may be negative
    expected_wait_months: float | None
    wait_cost_cents: int | None
    net_cents: int | None                # expected saving - waiting cost
    chosen: bool = False


@dataclass(frozen=True)
class LadderRow:
    index: int                  # sale point index (1 = next seasonal sale)
    label: str
    pct: int                    # deepest level with cumulative probability >= 0.5 by this sale (0 = none)
    cents: int                  # its price, floored to the cent
    probability: float | None   # cumulative probability of that level; None when pct = 0


@dataclass(frozen=True)
class RuleResult:
    group: str                  # now | soon | wait | low
    confidence: str             # normal | low (after the P_min=0 and regular-mismatch adjustments)
    basis: str                  # own | no-history
    horizon_points: int
    p_min_pct: int
    p_min_cents: int
    gap_pp: int | None          # None under 3.0.0 (no tolerance)
    tolerance_cents: int | None
    tolerance_bound: str | None   # None | min | max
    target_cents: int | None
    sweet_pct: int
    sweet_cents: int
    sweet_index: int
    sweet_probability: float | None   # None only when 3.0.0 has no target below the current price
    ladder: tuple[LadderRow, ...]
    tags: tuple[str, ...]
    rule: str = "1.0.0"
    wait_options: tuple[WaitOption, ...] = ()   # 3.0.0: buy now, then one row per sale (research R4)
    deadline_index: int | None = None           # 3.0.0: latest sale of the chosen option; None = buy now
    expected: WaitOption | None = None          # 3.0.0: the chosen row
    wait_cost_twd: int | None = None


def price_cents(regular_cents: int, pct: int) -> int:
    """TW price at a discount level, floored to the cent."""
    return regular_cents * (100 - pct) // 100


def horizon(points: Sequence[SalePoint], as_of: datetime, low: bool, months: int | None = None) -> int:
    """Number of leading points the rule may use: those ending within 12 months when low confidence, or within
    `months` (rule 2.0.0); otherwise all of them."""
    if not low and not months:
        return len(points)
    limit = add_months(as_of, months or LOW_CONFIDENCE_MONTHS)
    return sum(1 for p in points if p.end <= limit)


def deepest_likely(row: Sequence[float]) -> int:
    """Deepest level whose cumulative probability reaches P_MIN_THRESHOLD (0 when none does)."""
    return max((d for d, p in zip(LEVELS, row) if p >= P_MIN_THRESHOLD), default=0)


def _tolerance(regular_cents: int, p_min: int, prefs: Preferences) -> tuple[int, int, str | None]:
    gap = prefs.gap_pp_shallow if p_min < prefs.gap_boundary_pct else prefs.gap_pp_deep
    raw = -(-regular_cents * gap // 100)                   # ceil(regular × gap / 100)
    low, high = prefs.tolerance_min_twd * 100, prefs.tolerance_max_twd * 100
    if raw > high:
        return gap, high, "max"
    if raw < low:
        return gap, low, "min"
    return gap, raw, None


def _path(probabilities, points, as_of, confidence, regular_mismatch, no_history, months):
    """What 2.x and 3.0.0 share (003 research R1, 004 R5): which curve, how many sale points, the confidence."""
    low = confidence == "low" or regular_mismatch
    basis = "own"
    curve = probabilities
    n = horizon(points, as_of, confidence == "low", None if confidence == "low" else months)
    if n == 0:
        raise DecisionError(f"未來 {LOW_CONFIDENCE_MONTHS} 個月內沒有季節特賣，無法估計")
    p_min = deepest_likely(curve[n - 1])
    if p_min == 0 and confidence != "low":
        if no_history is None:
            raise DecisionError("本身的曲線沒有任何折扣達到 50%，也沒有「沒有本身歷史」的曲線可以改用")
        curve, basis, low = no_history, "no-history", True
        n = horizon(points, as_of, True)
        if n == 0:
            raise DecisionError(f"未來 {LOW_CONFIDENCE_MONTHS} 個月內沒有季節特賣，無法估計")
        p_min = deepest_likely(curve[n - 1])
    if p_min == 0:
        raise DecisionError("曲線上沒有任何折扣的累積機率達到 50%，無法估計甜蜜價")
    return curve, basis, low, n, p_min


def _ladder(curve, points, regular_cents, last_index) -> tuple[LadderRow, ...]:
    rows = []
    for i in range(last_index):
        pct = deepest_likely(curve[i])
        rows.append(LadderRow(points[i].index, points[i].label, pct, price_cents(regular_cents, pct),
                              curve[i][LEVELS.index(pct)] if pct else None))
    return tuple(rows)


def _common_tags(low, basis, regular_mismatch, current_price_cents, regular_cents, p_min) -> list[str]:
    tags = []
    if low:
        tags.append("low-confidence")
    if basis == "no-history":
        tags.append("no-history-curve")
    if regular_mismatch:
        tags.append("regular-mismatch")
    if current_price_cents is None:
        tags.append("price-unknown")
    elif current_price_cents * 100 < regular_cents * (100 - p_min):
        tags.append("below-history")
    return tags


def decide(*, probabilities: Sequence[Sequence[float]], points: Sequence[SalePoint], as_of: datetime,
           confidence: str, evidence_max_cut: int | None, regular_cents: int, current_price_cents: int | None,
           regular_mismatch: bool, no_history: Sequence[Sequence[float]] | None,
           preferences: Preferences, rule: str | None = None, months: int | None = None,
           history_stopped: bool = False) -> RuleResult:
    """`months` overrides the rule's 12-month range; only for the longer-horizon counts of `backtest-rule`
    (005 spec FR-017), never for a decision anyone sees."""
    spec = rule_spec(rule)
    rule = rule or CURRENT_RULE
    if not regular_cents or regular_cents <= 0:
        raise DecisionError("原價未知，無法換算台幣")
    stopped = history_stopped and spec["constants"].get("history_stopped_low", False)
    curve, basis, low, n, p_min = _path(probabilities, points, as_of, confidence, regular_mismatch or stopped,
                                        no_history, months or spec["p_min_months"])
    tags = _common_tags(low, basis, regular_mismatch, current_price_cents, regular_cents, p_min)
    if stopped:
        tags.append("history-stopped")
    if spec["kind"] == "wait-cost":
        result = _decide_wait_cost(curve=curve, points=points, as_of=as_of, n=n, low=low,
                                   regular_cents=regular_cents, current_price_cents=current_price_cents,
                                   preferences=preferences)
    else:
        result = _decide_tolerance(curve=curve, points=points, n=n, p_min=p_min, low=low,
                                   regular_cents=regular_cents, current_price_cents=current_price_cents,
                                   preferences=preferences)
        if result.pop("bound"):
            tags.append(f"tolerance-{result['tolerance_bound']}")
    if basis == "own" and evidence_max_cut is not None and p_min == evidence_max_cut // 5 * 5:
        tags.append("deeper-possible")
    return RuleResult(confidence="low" if low else "normal", basis=basis, horizon_points=n, p_min_pct=p_min,
                      p_min_cents=price_cents(regular_cents, p_min), tags=tuple(tags), rule=rule, **result)


def _group(*, now: bool, low: bool, sweet_index: int, soon_sales: int) -> str:
    if now:
        return "now"
    if low:
        return "low"
    return "soon" if sweet_index <= soon_sales else "wait"


def _decide_tolerance(*, curve, points, n, p_min, low, regular_cents, current_price_cents, preferences) -> dict:
    """Rules 1.0.0 and 2.0.0 (feature 003): the shallowest price within the tolerance of P_min."""
    gap, tolerance, bound = _tolerance(regular_cents, p_min, preferences)
    target_x100 = regular_cents * (100 - p_min) + tolerance * 100          # target price × 100, exact
    sweet = min(d for d in LEVELS if regular_cents * (100 - d) <= target_x100)
    j = LEVELS.index(sweet)
    sweet_i = next((i for i in range(n) if curve[i][j] >= TIMING_THRESHOLD), None)
    if sweet_i is None:
        raise DecisionError(f"曲線範圍內「≥ -{sweet}%」的機率沒有達到 50%，曲線不一致")
    now = current_price_cents is not None and current_price_cents * 100 <= regular_cents * (100 - sweet)
    return dict(group=_group(now=now, low=low, sweet_index=points[sweet_i].index, soon_sales=preferences.soon_sales),
                gap_pp=gap, tolerance_cents=tolerance, tolerance_bound=bound, target_cents=target_x100 // 100,
                sweet_pct=sweet, sweet_cents=price_cents(regular_cents, sweet), sweet_index=points[sweet_i].index,
                sweet_probability=curve[sweet_i][j], ladder=_ladder(curve, points, regular_cents, sweet_i + 1),
                bound=bound)


# --- 3.0.0: waiting cost (feature 005) ----------------------------------------------------------------------

def _months(moment: datetime, as_of: datetime) -> float:
    return (moment - as_of).total_seconds() / 86400 / MONTH_DAYS


def _option_rows(curve, points, as_of, regular_cents, base_cents, n, wait_cost_twd, *, every_level=False):
    """rows[K][j] = the WaitOption "target LEVELS[j], wait at most until sale K+1" (research R1), or None when the
    target is not below the base price (unless every_level). One pass over the curve (research R13)."""
    state = [(0.0, 0.0, 0.0)] * len(LEVELS)       # per level: F so far, E[paid when reached], E[wait when reached]
    rows = []
    for k in range(n):
        start, end = _months(points[k].start, as_of), _months(points[k].end, as_of)
        row = []
        for j, pct in enumerate(LEVELS):
            f, paid, wait = state[j]
            target = price_cents(regular_cents, pct)
            step = curve[k][j] - f
            if step > 0:
                f, paid, wait = curve[k][j], paid + step * target, wait + step * start
                state[j] = (f, paid, wait)
            if target >= base_cents and not every_level:
                row.append(None)
                continue
            miss = 1.0 - f                             # not reached by the deadline: regular price at its end
            saving = round(base_cents - (paid + miss * regular_cents))
            months = wait + miss * end
            cost = round(wait_cost_twd * 100 * months)
            likely = next((i for i in range(k + 1) if curve[i][j] >= TIMING_THRESHOLD), k)
            row.append(WaitOption(k + 1, points[k].label, pct, target, f, points[likely].index, points[likely].label,
                                  curve[likely][j], saving, months, cost, saving - cost))
        rows.append(row)
    return rows


def option_value(curve: Sequence[Sequence[float]], points: Sequence[SalePoint], as_of: datetime, *,
                 regular_cents: int, base_cents: int, pct: int, deadline_index: int,
                 wait_cost_twd: int) -> WaitOption:
    """The 3.0.0 value of any one option, e.g. a 2.0.0 recommendation in `compare-rule` (research R7)."""
    rows = _option_rows(curve, points, as_of, regular_cents, base_cents, deadline_index, wait_cost_twd,
                        every_level=True)
    return rows[deadline_index - 1][LEVELS.index(pct)]


def _decide_wait_cost(*, curve, points, as_of, n, low, regular_cents, current_price_cents, preferences) -> dict:
    c = preferences.wait_cost_twd
    known = current_price_cents is not None
    base = current_price_cents if known else regular_cents
    table = []
    for k, row in enumerate(_option_rows(curve, points, as_of, regular_cents, base, n, c)):
        best = None
        for o in row:                                  # shallow to deep: an equal net keeps the shallower target
            if o is not None and (best is None or o.net_cents > best.net_cents):
                best = o
        table.append(best or WaitOption(k + 1, points[k].label, None, None, None, None, None, None, None, None,
                                        None, None))
    waiting = None
    for o in table:                                    # early to late: an equal net keeps the earlier deadline
        if o.net_cents is not None and (waiting is None or o.net_cents > waiting.net_cents):
            waiting = o
    buy_now = WaitOption(0, None, None, base, None, None, None, None, 0, 0.0, 0, 0) if known else None
    chosen = buy_now if known and (waiting is None or waiting.net_cents <= 0) else waiting
    rows = tuple(replace(o, chosen=o is chosen) for o in ((buy_now,) if known else ()) + tuple(table))
    expected = next(o for o in rows if o.chosen)

    if waiting is None:                                # nothing below the current price (data-model.md)
        sweet_pct = (regular_cents - base) * 100 // regular_cents
        sweet_cents, sweet_index, sweet_probability = base, points[0].index, None
    else:                                              # the chosen row, or the best waiting row when buying now
        sweet_pct, sweet_cents = waiting.target_pct, waiting.target_cents
        sweet_index, sweet_probability = waiting.likely_index, waiting.likely_probability
    now = expected.deadline_index == 0
    return dict(group=_group(now=now, low=low, sweet_index=sweet_index, soon_sales=preferences.soon_sales),
                gap_pp=None, tolerance_cents=None, tolerance_bound=None, target_cents=None, sweet_pct=sweet_pct,
                sweet_cents=sweet_cents, sweet_index=sweet_index, sweet_probability=sweet_probability,
                ladder=_ladder(curve, points, regular_cents, sweet_index), wait_options=rows,
                deadline_index=None if now else expected.deadline_index, expected=expected, wait_cost_twd=c)
