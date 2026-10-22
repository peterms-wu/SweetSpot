"""Backtest metrics (research R4): Brier with every game weighted equally, grouped Brier, calibration, hit rate,
timing error and a population-share reference score. Accumulates per game; never keeps individual units."""

from collections import Counter
from collections.abc import Sequence
from typing import Any

POINT_THRESHOLD = 0.5      # framework setting: a point forecast is the first sale where P >= 0.5
CALIBRATION_BINS = 10


class _Game:
    __slots__ = ("pool", "n", "sse", "ref_sse", "by_level", "by_horizon", "by_conf", "cal_n", "cal_p", "cal_o",
                 "by_sales", "deep", "deep_cal", "fin")

    def __init__(self, pool: str, n_levels: int):
        self.pool = pool
        self.n = 0
        self.sse = 0.0
        self.ref_sse = 0.0
        self.by_level = [[0, 0.0] for _ in range(n_levels)]
        self.by_horizon: dict[str, list] = {}
        self.by_conf: dict[str, list] = {}
        self.cal_n = [0] * CALIBRATION_BINS
        self.cal_p = [0.0] * CALIBRATION_BINS
        self.cal_o = [0] * CALIBRATION_BINS
        self.by_sales: dict[str, list] = {}
        self.deep = [0, 0.0]                                             # deeper than past (004 research R2)
        self.deep_cal = [[0, 0.0, 0] for _ in range(CALIBRATION_BINS)]
        self.fin: dict[tuple[str, str], list] = {}                       # finished-only (kind, group) → [n, sse]


SALES_GROUPS = ("0", "1", "2", "3+", "3-5", "6+")          # 3-5 and 6+ added by feature 008; 3+ kept
DISTANCE_GROUPS = ("<=M-15", "M-10", "M-5", "M", "M+5", ">=M+10")


def _sales_groups(own_sales: int) -> tuple[str, ...]:
    if own_sales < 3:
        return (str(own_sales),)
    return ("3+", "3-5" if own_sales <= 5 else "6+")


def _distance_group(level: int, record: int) -> str:
    """The level against the game's deepest ended cut M (floored to 5 pp, like seasonal-record)."""
    gap = record - level
    if gap >= 15:
        return "<=M-15"
    if gap >= 10:
        return "M-10"
    if gap >= 5:
        return "M-5"
    if gap >= 0:
        return "M"
    return "M+5" if gap >= -5 else ">=M+10"


def _calibration(games, get) -> list[dict[str, Any]]:
    """Per-bin mean forecast and observed rate, each unit weighted 1 / (its game's units in the scope)."""
    out = []
    for b in range(CALIBRATION_BINS):
        wn = wp = wo = 0.0
        units = 0
        for g in games:
            total, bins = get(g)
            n, p, o = bins[b]
            if total and n:
                w = 1.0 / total
                wn += n * w
                wp += p * w
                wo += o * w
                units += n
        out.append({"bin": [b / CALIBRATION_BINS, (b + 1) / CALIBRATION_BINS],
                    "mean_forecast": wp / wn if wn else None, "observed_rate": wo / wn if wn else None,
                    "units": units})
    return out


def _mean_of_means(pairs: Sequence[tuple[int, float]]) -> float | None:
    means = [sse / n for n, sse in pairs if n]
    return sum(means) / len(means) if means else None


def _group(name: Any, pairs: list[tuple[int, float]]) -> dict[str, Any]:
    pairs = [p for p in pairs if p[0]]
    return {"group": name, "brier": _mean_of_means(pairs), "games": len(pairs), "units": sum(n for n, _ in pairs)}


class RegionMetrics:
    def __init__(self, region: str, levels: Sequence[int]):
        self.region = region
        self.levels = list(levels)
        self.games: dict[int, _Game] = {}
        self.censored = 0
        self.not_held = 0
        self.hits = self.misses = self.point_censored = 0
        self.never = self.never_but_occurred = 0
        self.timing = Counter()
        self.not_occurred_in_window = 0
        self.fin_bins = [[0, 0.0, 0] for _ in range(CALIBRATION_BINS)]     # finished-only, unit level: n, Σp, Σo
        self.fin_groups: dict[tuple[str, str], list] = {}                  # (kind, group) → [n, Σp, Σo]

    def add(self, *, app: int, pool: str, confidence: str, horizons: Sequence[str], indexes: Sequence[int],
            probs: Sequence[Sequence[float]], ref: Sequence[Sequence[float]], outcomes: Sequence[Sequence[str]],
            own_sales: int | None = None, past_max: int | None = None,
            finished: Sequence[Sequence[int] | None] | None = None) -> None:
        """One game at one as_of: rows are the window's sale points, columns the levels. `own_sales` and `past_max`
        are the game's ended seasonal sales at as_of and their deepest cut (None = no own sale). `finished[w]` is
        None when point w's sale did not end inside the known history, else the 0/1 outcome of every level judged
        at the actual end (feature 008 FR-011; never touches the 002 score)."""
        g = self.games.get(app)
        if g is None:
            g = self.games[app] = _Game(pool, len(self.levels))
        conf = g.by_conf.setdefault(confidence, [0, 0.0])
        sales = [g.by_sales.setdefault(name, [0, 0.0]) for name in _sales_groups(own_sales)]             if own_sales is not None else []
        deeper_from = len(self.levels) if past_max is None or not own_sales else             next((j for j, d in enumerate(self.levels) if d > past_max), len(self.levels))
        for w, row in enumerate(outcomes):
            hz = g.by_horizon.setdefault(horizons[w], [0, 0.0])
            prow, rrow = probs[w], ref[w]
            for j, outcome in enumerate(row):
                if outcome == "censored":
                    self.censored += 1
                    continue
                if outcome == "not-held":
                    self.not_held += 1
                    continue
                o = 1 if outcome == "occurred" else 0
                p = prow[j]
                err = (p - o) ** 2
                g.n += 1
                g.sse += err
                g.ref_sse += (rrow[j] - o) ** 2
                lv = g.by_level[j]
                lv[0] += 1
                lv[1] += err
                hz[0] += 1
                hz[1] += err
                conf[0] += 1
                conf[1] += err
                b = min(int(p * CALIBRATION_BINS), CALIBRATION_BINS - 1)
                g.cal_n[b] += 1
                g.cal_p[b] += p
                g.cal_o[b] += o
                for cell in sales:
                    cell[0] += 1
                    cell[1] += err
                if j >= deeper_from:
                    g.deep[0] += 1
                    g.deep[1] += err
                    cell = g.deep_cal[b]
                    cell[0] += 1
                    cell[1] += p
                    cell[2] += o
        if finished is not None:
            self._finished(g, confidence, probs, finished, own_sales, past_max)
        for j in range(len(self.levels)):
            self._point_forecast([probs[w][j] for w in range(len(outcomes))],
                                 [outcomes[w][j] for w in range(len(outcomes))], indexes)

    def _finished(self, g: _Game, confidence: str, probs, finished, own_sales, past_max) -> None:
        record = None if not own_sales or past_max is None else past_max - past_max % 5
        base = [("all", "all"), ("confidence", confidence)]
        if own_sales is not None:
            base += [("own_sales", name) for name in _sales_groups(own_sales) if name != "3+"]
        # the groups of a unit depend only on its level: resolve every level's cells once per call
        cells = []
        for d in self.levels:
            keys = list(base)
            if record is not None:
                keys += [("seen", "seen" if d <= record else "deeper"), ("distance", _distance_group(d, record))]
            cells.append([(self.fin_groups.setdefault(k, [0, 0.0, 0]), g.fin.setdefault(k, [0, 0.0])) for k in keys])
        bins = self.fin_bins
        n_levels = len(self.levels)
        sums = [[0, 0.0, 0, 0.0] for _ in range(n_levels)]       # per level: n, Σp, Σo, Σerr within this call
        for w, row in enumerate(finished):
            if row is None:
                continue
            prow = probs[w]
            for j, o in enumerate(row):
                p = prow[j]
                cell = bins[min(int(p * CALIBRATION_BINS), CALIBRATION_BINS - 1)]
                cell[0] += 1
                cell[1] += p
                cell[2] += o
                acc = sums[j]
                acc[0] += 1
                acc[1] += p
                acc[2] += o
                acc[3] += (p - o) * (p - o)
        for j in range(n_levels):
            n, sp, so, se = sums[j]
            if not n:
                continue
            for unit, game in cells[j]:
                unit[0] += n
                unit[1] += sp
                unit[2] += so
                game[0] += n
                game[1] += se
        for key in [k for k, v in g.fin.items() if not v[0]]:        # levels never finished leave no empty cells
            del g.fin[key]

    def _finished_result(self) -> dict[str, Any]:
        def brier(key):
            return _mean_of_means([tuple(g.fin[key]) for g in self.games.values() if key in g.fin])

        def row(kind, name):
            n, sp, so = self.fin_groups[(kind, name)]
            return {"group": name, "n": n, "predicted": sp / n, "actual": so / n, "brier": brier((kind, name))}

        order = {"confidence": ("normal", "low"), "own_sales": ("0", "1", "2", "3-5", "6+"),
                 "seen": ("seen", "deeper"), "distance": DISTANCE_GROUPS}
        total = self.fin_groups.get(("all", "all"), [0])[0]
        return {"units": total, "brier": brier(("all", "all")) if total else None,
                "bins": [{"lo": b / CALIBRATION_BINS, "n": n, "predicted": sp / n, "actual": so / n}
                         for b, (n, sp, so) in enumerate(self.fin_bins) if n],
                "groups": {kind: [row(kind, name) for name in names if self.fin_groups.get((kind, name), [0])[0]]
                           for kind, names in order.items()}}

    def _point_forecast(self, column: list[float], results: list[str], indexes: Sequence[int]) -> None:
        predicted = next((w for w, p in enumerate(column) if p >= POINT_THRESHOLD), None)
        actual = next((w for w, r in enumerate(results) if r == "occurred"), None)
        if predicted is None:
            self.never += 1
            self.never_but_occurred += actual is not None
        else:
            result = results[predicted]
            if result == "occurred":
                self.hits += 1
            elif result == "not-occurred":
                self.misses += 1
            else:
                self.point_censored += 1
            if actual is not None:
                self.timing[indexes[predicted] - indexes[actual]] += 1
        if actual is None and results and results[-1] == "not-occurred":
            self.not_occurred_in_window += 1

    def result(self) -> dict[str, Any]:
        games = self.games
        overall = [(g.n, g.sse) for g in games.values() if g.n]
        by_level = [_group(d, [(g.by_level[j][0], g.by_level[j][1]) for g in games.values()])
                    for j, d in enumerate(self.levels)]
        horizon_names = sorted({h for g in games.values() for h in g.by_horizon}, key=lambda h: int(h.split("-")[0]))
        by_horizon = [_group(h, [tuple(g.by_horizon[h]) for g in games.values() if h in g.by_horizon])
                      for h in horizon_names]
        by_conf = [_group(c, [tuple(g.by_conf[c]) for g in games.values() if c in g.by_conf])
                   for c in ("normal", "low") if any(c in g.by_conf for g in games.values())]
        pools = sorted({g.pool for g in games.values()})
        by_pool = [_group(p, [(g.n, g.sse) for g in games.values() if g.pool == p]) for p in pools]
        calibration = _calibration([g for g in games.values() if g.n],
                                   lambda g: (g.n, list(zip(g.cal_n, g.cal_p, g.cal_o))))
        by_sales = [_group(name, [tuple(g.by_sales[name]) for g in games.values() if name in g.by_sales])
                    for name in SALES_GROUPS if any(name in g.by_sales for g in games.values())]
        deep_games = [g for g in games.values() if g.deep[0]]
        deeper = {**_group("deeper_than_past", [tuple(g.deep) for g in deep_games]),
                  "calibration": _calibration(deep_games, lambda g: (g.deep[0], g.deep_cal))}
        deeper.pop("group")
        point_forecasts = self.hits + self.misses
        timing_n = sum(self.timing.values())
        return {
            "brier": _mean_of_means(overall),
            "reference_brier": _mean_of_means([(g.n, g.ref_sse) for g in games.values() if g.n]),
            "games": len(overall),
            "units": {"scored": sum(n for n, _ in overall), "censored": self.censored, "not_held": self.not_held},
            "by_horizon": by_horizon, "by_level": by_level, "by_confidence": by_conf, "by_pool": by_pool,
            "calibration": calibration,
            "deeper_than_past": deeper, "by_own_sales": by_sales,
            "hit_rate": {"point_forecasts": point_forecasts, "hits": self.hits,
                         "rate": self.hits / point_forecasts if point_forecasts else None,
                         "never_predicted": self.never, "never_predicted_but_occurred": self.never_but_occurred,
                         "censored": self.point_censored},
            "timing_error": {"n": timing_n,
                             "mean": sum(k * v for k, v in self.timing.items()) / timing_n if timing_n else None,
                             "mean_abs": sum(abs(k) * v for k, v in self.timing.items()) / timing_n if timing_n else None,
                             "distribution": {str(k): v for k, v in sorted(self.timing.items())},
                             "not_occurred_in_window": self.not_occurred_in_window},
            "finished_calibration": self._finished_result(),
            "per_game": {str(app): [g.n, g.sse] for app, g in sorted(games.items()) if g.n},
            "per_game_by_own_sales": {str(app): {k: list(v) for k, v in g.by_sales.items() if v[0]}
                                      for app, g in sorted(games.items()) if g.n},
        }
