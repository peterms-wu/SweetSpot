"""Backtest of the sweet-price rule on feature 002's TW dataset (research R10; FR-033; contracts/rule-backtest-result.md).

At every as_of the current model forecasts from the evidence visible then, and the rule decides with the TW price
state in effect at as_of (never the steam-current snapshots). Then we look at what happened: did the price reach the
sweet discount before the sweet sale ended, and, for buy-now decisions, did a deeper discount follow within 12 months.
"""

import hashlib
import json
import math
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from sweetspot import __version__
from sweetspot.calendar import SaleEvent
from sweetspot.config import Preferences
from sweetspot.decision.rule import CURRENT_RULE, RULE_NAME, RuleResult, decide, rule_spec
from sweetspot.forecast.backtest.dataset import BacktestDataset
from sweetspot.forecast.backtest.scoring import actual_sales, unit_outcome, window_points
from sweetspot.forecast.backtest.split import SALT
from sweetspot.forecast.contract import iso, write_json_atomic
from sweetspot.forecast.engine import is_paid_at, no_history_curve, predict_one
from sweetspot.forecast.evidence import GameData, game_evidence, population_view
from sweetspot.forecast.models.base import Model
from sweetspot.forecast.salepoints import SalePoint, sale_points
from sweetspot.forecast.series import PriceSeries
from sweetspot.timeutil import add_months, now_utc

SCHEMA = "steamsage.rule-backtest/1"
FOLLOWUP_MONTHS = 12


def current_state(series: PriceSeries, as_of: datetime):
    """The price state in effect at as_of. A module attribute so the leak test can swap in a peeking version."""
    return series.state_at(as_of)


@dataclass(frozen=True)
class CaseScore:
    outcome: str                          # now | beyond | hit | miss | censored
    timing: int | None                    # predicted sale index - actual crossing sale index
    followup: tuple[bool, int] | None     # buy-now: (deeper within 12 months, extra saving in cents); None = unknown


@dataclass(frozen=True)
class FollowScore:
    """Following the advice vs buying at as_of (004 research R6). Cents; None when unknown."""

    saving_cents: int | None      # price at as_of − price paid (negative: waiting cost money)
    wait_days: int | None
    censored: bool                # data ends before 12 months and the sweet level was not reached
    hindsight_cents: int | None   # price at as_of − lowest price within 12 months (needs the full 12 months)


def _price(state) -> int:
    return state.regular_cents * (100 - state.cut) // 100


def follow_advice(series: PriceSeries, as_of: datetime, result: RuleResult, *, now_price_cents: int) -> FollowScore:
    horizon = add_months(as_of, FOLLOWUP_MONTHS)
    known = series.known_until
    full = known is not None and known >= horizon
    hindsight = None
    if full:
        prices = [_price(st) for st in series.states if as_of < st.start <= horizon and st.regular_cents]
        hindsight = now_price_cents - min([now_price_cents, *prices])
    if result.group == "now":
        return FollowScore(0, 0, False, hindsight)
    first = series.first_crossings(as_of, [result.sweet_pct])[result.sweet_pct]
    if first is not None and first <= horizon:
        state = series.state_at(first)
        return FollowScore(now_price_cents - _price(state), (first - as_of).days, False, hindsight)
    if full:
        return FollowScore(now_price_cents - _price(series.state_at(horizon)), (horizon - as_of).days, False,
                           hindsight)
    return FollowScore(None, None, True, None)


# --- feature 005: monthly re-evaluation and the net benefit (research R6; spec FR-010, FR-011) ---------------------

EVALUATION_COSTS = (0, 10, 20, 30, 50, 80)      # NT$ a month; every rule's net benefit is shown at these costs
MONTH_DAYS = 365 / 12


def evaluation_costs(rule_cost: int | None) -> list[int]:
    """The fixed costs plus the rule's own waiting cost (3.0.0), sorted without duplicates."""
    return sorted(set(EVALUATION_COSTS) | ({rule_cost} if rule_cost is not None else set()))


@dataclass(frozen=True)
class MonthlyScore:
    """Following the latest decision at every analysis time (research R6 point 2). Cents; None when censored."""

    saving_cents: int | None
    wait_days: int | None
    censored: bool
    steps: int                      # how many later analysis times were used (diagnostics)


def follow_advice_monthly(series: PriceSeries, t0: datetime, schedule: Sequence[datetime],
                          decisions: Mapping[datetime, Any], *, now_price_cents: int) -> MonthlyScore:
    """`decisions[as_of]` has `group` and `sweet_pct` (the rule's decision then); a missing one keeps the previous.
    Buy now → the price then; otherwise the first time the price reaches the decision's sweet level; after 12 months
    without buying → the price at t0 + 12 months. Data ending before the next check without a purchase: censored."""
    horizon = add_months(t0, FOLLOWUP_MONTHS)
    known = series.known_until
    later = [t for t in schedule if t0 < t < horizon]
    current = decisions[t0]
    checks = [t0, *later]
    for step, t in enumerate(checks):
        current = decisions.get(t, current) if step else current
        if current.group == "now":
            return MonthlyScore(now_price_cents - _price(series.state_at(t)), (t - t0).days, False, step)
        nxt = checks[step + 1] if step + 1 < len(checks) else horizon
        first = series.first_crossings(t, [current.sweet_pct])[current.sweet_pct]
        if first is not None and first <= nxt and (known is None or first <= known):
            return MonthlyScore(now_price_cents - _price(series.state_at(first)), (first - t0).days, False, step)
        if known is None or known < nxt:
            return MonthlyScore(None, None, True, step)
    return MonthlyScore(now_price_cents - _price(series.state_at(horizon)), (horizon - t0).days, False,
                        len(checks) - 1)


def _net(score, cost_twd: int) -> float:
    return score.saving_cents / 100 - cost_twd * score.wait_days / MONTH_DAYS


def net_summary(scores: Sequence[Any], costs: Sequence[int]) -> list[dict[str, Any]]:
    """Net benefit = saving (NT$) − cost × months waited, per cost: mean, median, 25th and 75th percentile."""
    done = [s for s in scores if not s.censored]
    out = []
    for cost in costs:
        nets = [_net(s, cost) for s in done]
        pick = lambda q: None if not nets else round(_nearest_rank(nets, q), 2)  # noqa: E731
        out.append({"cost_twd": cost, "mean": sum(nets) / len(nets) if nets else None,
                    "median": pick(0.5), "p25": pick(0.25), "p75": pick(0.75)})
    return out


def case_rows(scores: Mapping[tuple[str, int, datetime], Any]) -> list[list[Any]]:
    """`cases` of the result file: [app_id, as_of, mode, saving_cents, wait_days], evaluated only, sorted."""
    rows = [[app, as_of.strftime("%Y-%m-%d"), mode, s.saving_cents, s.wait_days]
            for (mode, app, as_of), s in scores.items() if not s.censored]
    return sorted(rows, key=lambda r: (r[0], r[1], r[2]))


def sweet_timing_bucket(result: RuleResult, points: Sequence[SalePoint], as_of: datetime) -> str:
    if result.sweet_index == 1:
        return "next"
    return "within_1y" if points[result.sweet_index - 1].end <= add_months(as_of, FOLLOWUP_MONTHS) else "beyond_1y"


def _crossing_index(first: datetime, points: Sequence[SalePoint], actual: Mapping) -> int | None:
    for p in points:
        event = actual.get(p.sale_key)
        if event is not None and first < event.end:
            return p.index
    return None


def score_case(series: PriceSeries, as_of: datetime, result: RuleResult, points: Sequence[SalePoint],
               window: Sequence[SalePoint], actual: Mapping[tuple[str, int], SaleEvent], *, regular_cents: int,
               current_cut: int) -> CaseScore:
    """`series` is the full series up to the data cutoff (scoring may look after as_of; deciding may not)."""
    if result.group == "now":
        horizon = add_months(as_of, FOLLOWUP_MONTHS)
        if series.known_until is None or series.known_until < horizon:
            return CaseScore("now", None, None)
        later = max((s.cut for s in series.states if as_of < s.start <= horizon), default=0)
        deeper = later > current_cut
        return CaseScore("now", None, (deeper, regular_cents * (later - current_cut) // 100 if deeper else 0))
    point = points[result.sweet_index - 1]
    if point not in window:
        return CaseScore("beyond", None, None)
    first = series.first_crossings(as_of, [result.sweet_pct])[result.sweet_pct]
    outcome = unit_outcome(first, actual.get(point.sale_key), series.known_until, point.end)
    kind = {"occurred": "hit", "not-occurred": "miss"}.get(outcome, "censored")
    timing = None
    if first is not None and kind != "censored":
        k = _crossing_index(first, points, actual)
        timing = None if k is None else point.index - k
    return CaseScore(kind, timing, None)


def _rate(hits: int, misses: int) -> float | None:
    return hits / (hits + misses) if hits + misses else None


def _nearest_rank(values: list[int], q: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


class RuleMetrics:
    def __init__(self, costs: Sequence[int] = EVALUATION_COSTS):
        self.costs = list(costs)
        self.monthly: dict[tuple[str, str], list[MonthlyScore]] = defaultdict(list)
        self.groups: Counter = Counter()
        self.beyond = 0
        self.by_group: dict[str, Counter] = defaultdict(Counter)
        self.by_conf: dict[str, Counter] = defaultdict(Counter)
        self.timing: Counter = Counter()
        self.follow: dict[str, Counter] = defaultdict(Counter)
        self.extra: list[int] = []
        self.sweet_timing: Counter = Counter()
        self.advice: dict[tuple[str, str], list[FollowScore]] = defaultdict(list)   # (kind, name) → scores

    def add(self, confidence: str, group: str, score: CaseScore, *, follow: FollowScore | None = None,
            timing: str | None = None) -> None:
        self.groups[group] += 1
        if timing:
            self.sweet_timing[timing] += 1
        if follow is not None:
            for key in (("all", "overall"), ("group", group), ("confidence", confidence)):
                self.advice[key].append(follow)
        if score.outcome == "now":
            if score.followup is not None:
                deeper, extra = score.followup
                self.follow[confidence]["evaluated"] += 1
                if deeper:
                    self.follow[confidence]["deeper"] += 1
                    self.extra.append(extra)
            return
        if score.outcome == "beyond":
            self.beyond += 1
            return
        key = {"hit": "hits", "miss": "misses", "censored": "censored"}[score.outcome]
        self.by_group[group][key] += 1
        self.by_conf[confidence][key] += 1
        if score.timing is not None:
            self.timing[score.timing] += 1

    @staticmethod
    def _row(name: str, c: Counter) -> dict[str, Any]:
        return {"group": name, "hits": c["hits"], "misses": c["misses"], "censored": c["censored"],
                "rate": _rate(c["hits"], c["misses"])}

    def add_monthly(self, confidence: str, group: str, score: MonthlyScore) -> None:
        for key in (("all", "overall"), ("group", group), ("confidence", confidence)):
            self.monthly[key].append(score)

    def _advice(self, name: str, scores: list) -> dict[str, Any]:
        done = [f for f in scores if not f.censored]
        twd = [(f.saving_cents + 50) // 100 for f in done]
        days = [f.wait_days for f in done]
        return {"group": name, "evaluated": len(done), "censored": len(scores) - len(done),
                "saving_twd": {"mean": sum(f.saving_cents for f in done) / len(done) / 100 if done else None,
                               "median": _nearest_rank(twd, 0.5), "p75": _nearest_rank(twd, 0.75),
                               "p90": _nearest_rank(twd, 0.9)},
                "wait_days": {"mean": sum(days) / len(days) if days else None, "median": _nearest_rank(days, 0.5)},
                "net_twd": net_summary(scores, self.costs)}

    def _block(self, advice: Mapping[tuple[str, str], list]) -> dict[str, Any]:
        overall = self._advice("overall", advice.get(("all", "overall"), []))
        overall.pop("group")
        return {"overall": overall,
                "by_group": [self._advice(g, advice[("group", g)]) for g in ("now", "soon", "wait", "low")
                             if ("group", g) in advice],
                "by_confidence": [self._advice(c, advice[("confidence", c)]) for c in ("normal", "low")
                                  if ("confidence", c) in advice]}

    def _follow_result(self) -> dict[str, Any]:
        overall = self._advice("overall", self.advice.get(("all", "overall"), []))
        overall.pop("group")
        hind = [f.hindsight_cents for f in self.advice.get(("all", "overall"), []) if f.hindsight_cents is not None]
        return {
            "evaluation_costs_twd": list(self.costs),
            "follow_advice_monthly": self._block(self.monthly),
            "sweet_timing": {k: self.sweet_timing[k] for k in ("next", "within_1y", "beyond_1y")},
            "follow_advice": {
                "overall": overall,
                "by_group": [self._advice(g, self.advice[("group", g)]) for g in ("now", "soon", "wait", "low")
                             if ("group", g) in self.advice],
                "by_confidence": [self._advice(c, self.advice[("confidence", c)]) for c in ("normal", "low")
                                  if ("confidence", c) in self.advice]},
            "hindsight": {"evaluated": len(hind),
                          "saving_twd": {"mean": sum(hind) / len(hind) / 100 if hind else None,
                                         "median": _nearest_rank([(c + 50) // 100 for c in hind], 0.5)}},
        }

    def result(self) -> dict[str, Any]:
        overall = Counter()
        for c in self.by_group.values():
            overall.update(c)
        n = sum(self.timing.values())
        evaluated = sum(c["evaluated"] for c in self.follow.values())
        deeper = sum(c["deeper"] for c in self.follow.values())
        twd = [(cents + 50) // 100 for cents in self.extra]
        return {
            "decisions": {"total": sum(self.groups.values()), **{g: self.groups[g] for g in ("now", "soon", "wait", "low")},
                          "beyond_window": self.beyond},
            "hit_rate": {
                "overall": self._row("overall", overall),
                "by_group": [self._row(g, self.by_group[g]) for g in ("soon", "wait", "low")],
                "by_confidence": [self._row(c, self.by_conf[c]) for c in ("normal", "low") if c in self.by_conf],
            },
            "timing_error": {"n": n, "mean": sum(k * v for k, v in self.timing.items()) / n if n else None,
                             "mean_abs": sum(abs(k) * v for k, v in self.timing.items()) / n if n else None,
                             "distribution": {str(k): v for k, v in sorted(self.timing.items())}},
            "now_followup": {"evaluated": evaluated, "deeper_within_12m": deeper, "rate": _rate(deeper, evaluated - deeper),
                             "by_confidence": [{"group": c, "evaluated": self.follow[c]["evaluated"],
                                                "deeper": self.follow[c]["deeper"]}
                                               for c in ("normal", "low") if self.follow[c]["evaluated"]],
                             "extra_saving_twd": {"median": _nearest_rank(twd, 0.5), "p75": _nearest_rank(twd, 0.75),
                                                  "p90": _nearest_rank(twd, 0.9)}},
            **self._follow_result(),
        }


def decisions_multi(games: Mapping[int, GameData], apps: Sequence[int], as_of: datetime, points: Sequence[SalePoint],
                    model: Model, variants: Sequence[tuple[Preferences, int | None]],
                    rule: str | None = None) -> list[dict[int, RuleResult | str]]:
    """The rule's decision for each app and each (preferences, months) variant at as_of, from what was visible then.
    The forecast is made once per app (model must be prepared); only the rule runs per variant (005 research R6)."""
    no_history = no_history_curve(model, as_of, points)
    out: list[dict[int, RuleResult | str]] = [{} for _ in variants]
    for app in apps:
        forecast = predict_one(model, game_evidence(games[app], as_of, "TW"), points)
        state = current_state(games[app].series["TW"], as_of)
        for k, (preferences, months) in enumerate(variants):
            if isinstance(forecast, str):
                out[k][app] = forecast
                continue
            try:
                out[k][app] = decide(probabilities=forecast.probabilities, points=points, as_of=as_of,
                                     confidence=forecast.confidence, evidence_max_cut=forecast.evidence.get("max_cut"),
                                     regular_cents=state.regular_cents,
                                     current_price_cents=state.regular_cents * (100 - state.cut) // 100,
                                     regular_mismatch=False,
                                     no_history=no_history.probabilities if no_history else None,
                                     preferences=preferences, rule=rule, months=months)
            except Exception as exc:  # noqa: BLE001 - isolated to this game and as_of
                out[k][app] = f"{type(exc).__name__}: {exc}"
    return out


def decisions_at(games: Mapping[int, GameData], apps: Sequence[int], as_of: datetime, points: Sequence[SalePoint],
                 model: Model, preferences: Preferences, rule: str | None = None) -> dict[int, RuleResult | str]:
    """The rule's decision for each app at as_of, from what was visible then (model must be prepared)."""
    return decisions_multi(games, apps, as_of, points, model, [(preferences, None)], rule)[0]


def result_filename(model: Model, dataset_id: str, started: datetime, rule: str = CURRENT_RULE,
                    wait_cost_twd: int | None = None) -> str:
    params = hashlib.sha256(json.dumps(dict(model.params), sort_keys=True).encode()).hexdigest()[:6]
    cost = "" if wait_cost_twd is None else f"-c{wait_cost_twd}"
    return (f"{started.strftime('%Y%m%dT%H%M%SZ')}_{RULE_NAME}-{rule}{cost}_{model.name}-{model.version}_{params}"
            f"_TW_{dataset_id[:8]}.json")


LONGER_HORIZONS = (24, 60)       # 005 spec FR-017: counts only, never scored


@dataclass
class _Variant:
    preferences: Preferences
    cost: int | None
    metrics: RuleMetrics
    errors: list
    compact: dict                              # (app, as_of) -> (group, sweet_pct) for the monthly walk
    fixed: dict                                # ("fixed", app, as_of) -> FollowScore
    longer: dict                               # months -> [decisions, beyond 12 months, sum of expected waits]


def run_rule_backtests(dataset: BacktestDataset, games: Mapping[int, GameData], events: Sequence[SaleEvent],
                       model: Model, preferences: Preferences, *, out_dir: Path | None = None,
                       progress: Callable[[str], None] | None = None, now: datetime | None = None,
                       rule: str | None = None,
                       wait_costs: Sequence[int] | None = None) -> list[tuple[dict[str, Any], Path | None]]:
    """One result per waiting cost (rule 3.0.0) or a single result (tolerance rules); forecasts are made once."""
    rule = rule or CURRENT_RULE
    spec = rule_spec(rule)
    wait_cost_rule = spec.get("kind") == "wait-cost"
    if wait_costs and not wait_cost_rule:
        raise ValueError(f"規則 {rule} 不使用等待成本")
    costs = list(wait_costs or [preferences.wait_cost_twd]) if wait_cost_rule else [None]
    started_at = now or now_utc()
    clock = time.monotonic()
    rd = dataset.regions["TW"]
    actual = actual_sales(events)
    variants = [_Variant(replace(preferences, wait_cost_twd=c) if c is not None else preferences, c,
                         RuleMetrics(evaluation_costs(c)), [], {}, {}, {m: [0, 0, 0.0] for m in LONGER_HORIZONS})
                for c in costs]
    runs = [(v.preferences, None) for v in variants]
    if wait_cost_rule:
        runs += [(v.preferences, m) for v in variants for m in LONGER_HORIZONS]
    for n, as_of in enumerate(rd.schedule, 1):
        if progress:
            progress(f"規則回測 分析時點 {n}/{len(rd.schedule)}（{as_of.strftime('%Y-%m-%d')}）")
        present = [a for a in rd.apps if games[a].series["TW"].first_start <= as_of and is_paid_at(games[a], as_of)]
        points = sale_points([e for e in events if e.start <= as_of], as_of)
        window = window_points(points, as_of, "TW")
        if not present or not window:
            continue
        pool = present if rd.population_apps == rd.apps else \
            [a for a in rd.population_apps if games[a].series["TW"].first_start <= as_of and is_paid_at(games[a], as_of)]
        model.prepare(population_view((games[a] for a in pool), as_of, "TW"))
        results = decisions_multi(games, present, as_of, points, model, runs, rule)
        twelve = add_months(as_of, FOLLOWUP_MONTHS)
        for k, v in enumerate(variants):
            for app, decision in results[k].items():
                if isinstance(decision, str):
                    v.errors.append({"app_id": app, "as_of": as_of.strftime("%Y-%m-%d"), "reason": decision})
                    continue
                series = games[app].series["TW"]
                state = series.state_at(as_of)
                now_price = state.regular_cents * (100 - state.cut) // 100
                follow = follow_advice(series, as_of, decision, now_price_cents=now_price)
                v.metrics.add(decision.confidence, decision.group,
                              score_case(series, as_of, decision, points, window, actual,
                                         regular_cents=state.regular_cents, current_cut=state.cut),
                              follow=follow, timing=sweet_timing_bucket(decision, points, as_of))
                v.compact[(app, as_of)] = (decision.group, decision.sweet_pct, decision.confidence, now_price)
                v.fixed[("fixed", app, as_of)] = follow
            for j, months in enumerate(LONGER_HORIZONS if wait_cost_rule else ()):
                counts = v.longer[months]
                for decision in results[len(variants) + k * len(LONGER_HORIZONS) + j].values():
                    if isinstance(decision, str):
                        continue
                    counts[0] += 1
                    if decision.deadline_index and points[decision.deadline_index - 1].end > twelve:
                        counts[1] += 1
                        counts[2] += decision.expected.expected_wait_months
    out = []
    for v in variants:
        scores = dict(v.fixed)
        by_app: dict[int, dict[datetime, Any]] = defaultdict(dict)
        for (app, as_of), (group, pct, _, _) in v.compact.items():
            by_app[app][as_of] = _Compact(group, pct)
        for (app, as_of), (group, _, confidence, now_price) in v.compact.items():
            score = follow_advice_monthly(games[app].series["TW"], as_of, rd.schedule, by_app[app],
                                          now_price_cents=now_price)
            v.metrics.add_monthly(confidence, group, score)
            scores[("monthly", app, as_of)] = score
        body = v.metrics.result()
        body["decisions"]["decision_error"] = len(v.errors)
        result = {
            "schema": SCHEMA,
            "rule": {"name": RULE_NAME, "version": rule, "constants": dict(spec["constants"])},
            "preferences": v.preferences.for_rule(rule),
            "model": {"name": model.name, "version": model.version, "params": dict(model.params)},
            "dataset": {"region": "TW", "dataset_id": rd.dataset_id, "cutoff": iso(dataset.cutoff),
                        "split": {"name": dataset.split, "salt": SALT},
                        "schedule": [t.strftime("%Y-%m-%d") for t in rd.schedule], "window_months": list(rd.window),
                        "games": len(rd.apps)},
            **body,
            "errors": v.errors,
            "cases": case_rows(scores),
            "run": {"started_at": iso(started_at), "finished_at": iso(now_utc()),
                    "seconds": round(time.monotonic() - clock, 1), "steamsage_version": __version__},
        }
        if wait_cost_rule:
            result["longer_horizon"] = {
                str(m): {"decisions": c[0], "beyond_12m": c[1],
                         "mean_expected_wait_months": round(c[2] / c[1], 2) if c[1] else None}
                for m, c in v.longer.items()}
        path = None
        if out_dir is not None:
            path = write_json_atomic(Path(out_dir) / result_filename(model, rd.dataset_id, started_at, rule, v.cost),
                                     result)
        out.append((result, path))
    return out


@dataclass(frozen=True)
class _Compact:
    group: str
    sweet_pct: int


def run_rule_backtest(dataset: BacktestDataset, games: Mapping[int, GameData], events: Sequence[SaleEvent],
                      model: Model, preferences: Preferences, *, out_dir: Path | None = None,
                      progress: Callable[[str], None] | None = None, now: datetime | None = None,
                      rule: str | None = None) -> tuple[dict[str, Any], Path | None]:
    return run_rule_backtests(dataset, games, events, model, preferences, out_dir=out_dir, progress=progress,
                              now=now, rule=rule)[0]


def report_figures(result: Mapping[str, Any]) -> dict[str, Any]:
    """The figures the report quotes (decision contract `rule_backtest`); copied into rule.RULE_BACKTESTS."""
    rates = {g["group"]: g["rate"] for g in result["hit_rate"]["by_group"]}
    return {"rule": result["rule"]["version"], "model": dict(result["model"]),
            "wait_cost_twd": (result.get("preferences") or {}).get("wait_cost_twd"),"date": result["dataset"]["cutoff"][:10], "region": "TW", "window_months": result["dataset"]["window_months"][1],
            "hit_rate": {g: None if rates.get(g) is None else round(rates[g], 3) for g in ("soon", "wait", "low")},
            "now_deeper_within_12m": None if result["now_followup"]["rate"] is None
            else round(result["now_followup"]["rate"], 3),
            "source": "docs/model/model-definition.md"}
