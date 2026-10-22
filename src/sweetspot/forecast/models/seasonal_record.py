"""Model `seasonal-record` (docs/model/model-definition.md; feature 004 research R1).

Levels the game has already reached (d ≤ M, M = its deepest ended seasonal cut, floored to 5):
    per-sale share p_w(d) with recency weights 0.5^((n−1−i)/half_life), and a new record also reaches d, so
    P(≥ d by sale k) = 1 − (1 − p_w(d))^k × Π_j (1 − h(M, s + j)).
Deeper levels (d > M): a "new record" chain over the state (M, s), s = sales since M was first reached (≤ 4).
    Each sale sets a record with probability h(M, s), looked up in a table of what happened to all games before
    as_of, and then deepens by J steps of 5 pp; P(≥ d by sale k) = P(running max after k sales ≥ d).
With fewer than `min_sales` own sales the model is `seasonal-freq` (population share, low confidence).
"""

from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Any

from sweetspot.forecast.evidence import GameEvidence, PopulationView
from sweetspot.forecast.models import register
from sweetspot.forecast.models.base import ModelOutput
from sweetspot.forecast.models.seasonal_freq import SeasonalFreq
from sweetspot.forecast.salepoints import SalePoint

# Structure constants (model definition; research R0.1, R0.2), not tuned by the grid.
S_CAP = 4                 # sales since the record: 0, 1, 2, 3, 4 (= 4 or more)
SMOOTHING = 20            # additive smoothing: cell → its M group → overall
JUMP_CAP = 5              # a record deepens by at most 5 steps of 5 pp
JUMP_MIN_RECORDS = 20     # fewer records in an M group: use the jump distribution of all groups
SMALL_CELL = 20           # reasons say a cell with fewer sales leans on its M group (contracts/model-api.md)
M_GROUP_LABELS = ("淺於 -50%", "-50%～-70%", "-75%～-85%", "-90% 以上")
M_GROUP_PHRASES = ("最深折扣淺於 -50%", "最深折扣在 -50%～-70%", "最深折扣在 -75%～-85%", "最深折扣達 -90% 以上")
HAZARD_HISTORIES = ("TW", "TW+US")
DIRECTION_ZH = {"deeper": "加深", "flat": "持平", "shallower": "變淺"}


def f5(cut: int) -> int:
    return cut - cut % 5


def m_group(m5: int) -> int:
    return 0 if m5 < 50 else 1 if m5 <= 70 else 2 if m5 <= 85 else 3


def s_group(s: int) -> int:
    return 0 if s == 0 else 1 if s == 1 else 2 if s <= 3 else 3


def record_state(cuts: Sequence[int]) -> tuple[int, int, int]:
    """(M floored to 5, sales since M was first reached capped at S_CAP, index of that sale)."""
    m5 = f5(max(cuts))
    first = next(i for i, c in enumerate(cuts) if f5(c) == m5)
    return m5, min(len(cuts) - 1 - first, S_CAP), first


@dataclass(frozen=True)
class HazardTable:
    """Record counts by state before as_of: cells[(m_group, s_group)] = (sales, records)."""

    cells: Mapping[tuple[int, int], tuple[int, int]]
    m_counts: Mapping[int, tuple[int, int]]
    overall: tuple[int, int]
    jumps: Mapping[int, Mapping[int, float]]
    regions: tuple[str, ...]

    def _m_rate(self, group: int) -> float:
        n, r = self.overall
        overall = r / n if n else 0.0
        mn, mr = self.m_counts.get(group, (0, 0))
        return (mr + SMOOTHING * overall) / (mn + SMOOTHING)

    def rate(self, m5: int, s: int) -> float:
        if m5 >= 95:
            return 0.0
        g = m_group(m5)
        n, r = self.cells.get((g, s_group(s)), (0, 0))
        return (r + SMOOTHING * self._m_rate(g)) / (n + SMOOTHING)

    def basis(self, m5: int, s: int) -> dict[str, int] | str:
        if not self.overall[0]:
            return "none"
        g = m_group(m5)
        return {"cell_sales": self.cells.get((g, s_group(s)), (0, 0))[0],
                "cell_records": self.cells.get((g, s_group(s)), (0, 0))[1],
                "m_group_sales": self.m_counts.get(g, (0, 0))[0], "overall_sales": self.overall[0]}

    def jump(self, m5: int) -> Mapping[int, float]:
        return self.jumps.get(m_group(m5)) or {1: 1.0}


def build_hazard_table(sequences: Iterable[tuple[str, Sequence[int]]], min_sales: int) -> HazardTable:
    """`sequences` are (region, max cuts of ended seasonal sales, oldest first). A unit is a sale with at least
    `min_sales` earlier ones, grouped by the state before it."""
    cells: dict[tuple[int, int], list[int]] = defaultdict(lambda: [0, 0])
    m_counts: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    total = [0, 0]
    jumps: dict[int, Counter] = defaultdict(Counter)
    regions = set()
    for region, cuts in sequences:
        for i in range(max(min_sales, 1), len(cuts)):
            m5, s, _ = record_state(cuts[:i])
            if m5 >= 95:
                continue
            record = f5(cuts[i]) > m5
            g = m_group(m5)
            for acc in (cells[(g, s_group(s))], m_counts[g], total):
                acc[0] += 1
                acc[1] += record
            regions.add(region)
            if record:
                jumps[g][min((f5(cuts[i]) - m5) // 5, JUMP_CAP)] += 1
    everything = sum(jumps.values(), Counter())
    distributions = {}
    for g in range(4):
        source = jumps[g] if sum(jumps[g].values()) >= JUMP_MIN_RECORDS else everything
        n = sum(source.values())
        if n:
            distributions[g] = {j: c / n for j, c in sorted(source.items())}
    return HazardTable({k: tuple(v) for k, v in cells.items()}, {k: tuple(v) for k, v in m_counts.items()},
                       tuple(total), distributions, tuple(sorted(regions, key=["TW", "US"].index)))


def chain_tables(hazard: Callable[[int, int], float], jumps: Callable[[int], Mapping[int, float]],
                 k_max: int) -> list[dict[tuple[int, int, int], float]]:
    """tables[k−1][(M, s, d)] = P(running max after k sales ≥ d | state (M, s)), for every d > M (backward
    recursion over all states at once: one table serves every game of an as_of)."""
    states = [(m, t) for m in range(0, 100, 5) for t in range(S_CAP + 1)]
    previous: dict[tuple[int, int, int], float] = {}
    tables = []
    for _ in range(k_max):
        current = {}
        for m, t in states:
            h = hazard(m, t) if m < 95 else 0.0
            q = jumps(m)
            nxt = min(t + 1, S_CAP)
            for d in range(m + 5, 100, 5):
                v = 0.0
                for j, pj in q.items():
                    new = min(m + 5 * j, 95)
                    v += pj * (1.0 if new >= d else previous.get((new, 0, d), 0.0))
                current[(m, t, d)] = h * v + (1.0 - h) * previous.get((m, nxt, d), 0.0)
        tables.append(current)
        previous = current
    return tables


def _number(value: float) -> int | float:
    return int(value) if float(value).is_integer() else float(value)


@register
class SeasonalRecord:
    name = "seasonal-record"
    version = "1.0.0"
    tw_only_params = frozenset({"hazard_history"})
    predicts_deeper = True
    deeper_caveat = ("12 個月內最低價可能更低：回測中判為現在買之後 12 個月內，"
                     "仍有 {now_deeper_within_12m} 出現更深折扣")

    def __init__(self, min_sales: int = 1, half_life: float = 2, hazard_history: str = "TW+US"):
        if not isinstance(min_sales, int) or isinstance(min_sales, bool) or min_sales < 1:
            raise ValueError(f"min_sales 必須是 ≥ 1 的整數：{min_sales!r}")
        if isinstance(half_life, bool) or not isinstance(half_life, (int, float)) or half_life < 0:
            raise ValueError(f"half_life 必須是 ≥ 0 的數字：{half_life!r}")
        if hazard_history not in HAZARD_HISTORIES:
            raise ValueError(f"hazard_history 必須是 {HAZARD_HISTORIES} 之一：{hazard_history!r}")
        self.min_sales = min_sales
        self.half_life = _number(half_life)
        self.hazard_history = hazard_history
        self._freq = SeasonalFreq(min_sales=min_sales, history="TW")
        self.table: HazardTable | None = None
        self._target = "TW"
        self._chain: list[dict] = []

    @classmethod
    def from_params(cls, raw: Mapping[str, Any]) -> "SeasonalRecord":
        unknown = set(raw) - {"min_sales", "half_life", "hazard_history"}
        if unknown:
            raise ValueError(f"seasonal-record 沒有這些參數：{', '.join(sorted(unknown))}")
        kwargs: dict[str, Any] = {}
        try:
            if "min_sales" in raw:
                kwargs["min_sales"] = int(raw["min_sales"])
            if "half_life" in raw:
                kwargs["half_life"] = float(raw["half_life"])
        except (TypeError, ValueError):
            raise ValueError(f"參數必須是數字：{dict(raw)!r}") from None
        if "hazard_history" in raw:
            kwargs["hazard_history"] = str(raw["hazard_history"])
        return cls(**kwargs)

    @property
    def params(self) -> dict[str, Any]:
        return {"min_sales": self.min_sales, "half_life": self.half_life, "hazard_history": self.hazard_history}

    def confidence_levels(self) -> dict[str, str]:
        n = self.min_sales
        return {
            "normal": f"本身至少有 {n} 場已結束的季節特賣紀錄：見過的折扣用本身的頻率（近期加權），"
                      "更深的折扣用參考資料集的創新低機率",
            "low": f"本身已結束的季節特賣紀錄少於 {n} 場，改用參考資料集的整體比例",
        }

    # --- model interface ---------------------------------------------------------------------

    def _sequences(self, population: PopulationView) -> Iterable[tuple[str, Sequence[int]]]:
        regions = ("US",) if population.target_region == "US" else \
            ("TW", "US") if self.hazard_history == "TW+US" else ("TW",)
        for history in population.sale_history.values():
            for region in regions:
                cuts = [o.max_cut for o in history.get(region, ())]
                if cuts:
                    yield region, cuts

    def prepare(self, population: PopulationView) -> None:
        self._freq.prepare(population)
        self.table = build_hazard_table(self._sequences(population), self.min_sales)
        self._target = population.target_region
        self._chain = []

    def _tables(self, k_max: int) -> list[dict]:
        if len(self._chain) < k_max:
            self._chain = chain_tables(self.table.rate, self.table.jump, k_max)
        return self._chain

    def predict(self, game: GameEvidence, points: Sequence[SalePoint], levels: Sequence[int]) -> ModelOutput:
        own = self._freq._history(game.sale_history, game.target_region)
        if len(own) < self.min_sales:
            return self._freq.predict(game, points, levels)
        if self.table is None:
            raise ValueError("prepare() 必須在 predict() 之前呼叫")
        if any(d % 5 for d in levels):
            raise ValueError("折扣等級必須是 5 的倍數")
        cuts = [o.max_cut for o in own]
        n = len(cuts)
        weights = [0.5 ** ((n - 1 - i) / self.half_life) if self.half_life else 1.0 for i in range(n)]
        total = sum(weights)
        m5, s, first = record_state(cuts)
        k_max = len(points)
        tables = self._tables(k_max) if k_max else []
        survive, acc = [], 1.0
        for j in range(k_max):
            acc *= 1.0 - self.table.rate(m5, min(s + j, S_CAP))
            survive.append(acc)
        shares = {d: sum(w for w, c in zip(weights, cuts) if c >= d) / total for d in levels if d <= m5}
        probabilities = tuple(
            tuple(1.0 - (1.0 - shares[d]) ** k * survive[k - 1] if d <= m5 else tables[k - 1].get((m5, s, d), 0.0)
                  for d in levels)
            for k in range(1, k_max + 1))
        base = self._freq.predict(game, points, levels)        # evidence and the first two reasons
        tail = cuts[-4:]
        direction = None if n == 1 else "deeper" if tail[-1] > tail[0] else "flat" if tail[-1] == tail[0] \
            else "shallower"
        evidence = {**base.evidence, "record_sale": own[first].label, "since_record": s,
                    "hazard": self.table.rate(m5, s), "hazard_basis": self.table.basis(m5, s),
                    "hazard_regions": list(self.table.regions), "half_life": self.half_life,
                    "recent_direction": direction}
        reasons = self._reasons(base.reasons, own, cuts, m5, s, first, tail, direction)
        return ModelOutput(probabilities, "normal", reasons, evidence)

    def _reasons(self, base: Sequence[str], own, cuts, m5, s, first, tail, direction) -> tuple[str, ...]:
        never = max(cuts) == 0
        out = [base[0], f"過去 {len(cuts)} 場季節特賣都沒打折" if never else base[1]]
        trend = []
        if direction and not never:
            trend.append(f"最近 {len(tail)} 場折扣{DIRECTION_ZH[direction]}（-{tail[0]}% → -{tail[-1]}%）")
        if self.half_life:
            trend.append(f"近期的特賣權重較高：每早 {self.half_life} 場，權重減半")
        if trend:
            out.append("；".join(trend))
        basis = self.table.basis(m5, s)
        if m5 >= 95:
            out.append("過去最大折扣已達 -95%，沒有更深的等級")
        elif basis == "none":
            out.append("參考資料集中沒有足夠的樣本估計創新低機率，比過去更深的折扣給 0")
        else:
            gap = f"{s} 場以上" if s == S_CAP else f"{s} 場"
            gap_group = "1 場" if s == 1 else "2–3 場" if s <= 3 else "4 場以上"
            if never:        # nothing was ever "a new low": say what the cell's games have in common
                state = "剛開始有紀錄" if s == 0 else f"已經 {gap_group}沒有更深折扣"
            else:
                state = ("上一場剛創新低" if s == 0 else "1 場以前創新低" if s == 1 else "2–3 場以前創新低"
                         if s <= 3 else "4 場以上沒有創新低")
            where = ("美國區" if self._target == "US"
                     else "含美國區折扣百分比" if "US" in self.table.regions else "")
            sample = f"{basis['cell_sales']} 場" + (f"，{where}" if where else "")
            head = "" if never else f"上一次創新低是 {own[first].label}（-{cuts[first]}%，{gap}以前）；"
            line = (f"{head}參考資料集中，{M_GROUP_PHRASES[m_group(m5)]}、{state}的遊戲，"
                    f"下一場打出比過去更深的折扣的比例為 {self.table.rate(m5, s):.0%}（{sample}）")
            if basis["cell_sales"] < SMALL_CELL:
                line += "；樣本少，向同一折扣範圍的整體比例靠攏"
            out.append(line)
            deeper = f"比 -{m5}% 更深的折扣" if m5 else "-5% 以上的折扣"
            out.append(f"{deeper}：依上一行的機率逐場推算；創新低之後再創新低的機率較高，停在同一個低點越久越低")
        out.append("假設在同樣的狀態下，各場特賣彼此獨立")
        return tuple(out)


# --- feature 008: seasonal-record 1.1.0 (research R1, R2; contracts/model-api.md) --------------------------------

LOW_BASES = ("population", "new", "new-split")
NEW_GAME_DAYS = 365           # a "new game": its first ended seasonal record started ≤ 365 days after release
MIN_SEQUENCES = 30            # fewer sequences with ≥ k records: carry k − 1 (none at k = 1: population share)
SHRINK_REASON_MAX_SALES = 3   # the shrink line is written for games with at most this many own records
SEQUENCE_PHRASES = {"all-new": " {n} 款新遊戲（發行 1 年內開始有紀錄，含發售前）",     # follows "參考資料集中"
                    "released": " {n} 款新遊戲（發行 1 年內開始有紀錄）",
                    "pre-release": "發售前就有季節特賣紀錄的 {n} 款遊戲"}


def empirical_cumulative(sequences: Sequence[Sequence[int]], k_max: int,
                         levels: Sequence[int]) -> list[list[float]] | None:
    """F[k−1][j] = share of sequences with ≥ k records whose max over the first k reaches levels[j]; thin k carry
    k − 1; monotone in k (running max) and in d (running min). None when even k = 1 is too thin."""
    out, previous = [], None
    for k in range(1, k_max + 1):
        maxima = [max(seq[:k]) for seq in sequences if len(seq) >= k]
        if len(maxima) >= MIN_SEQUENCES:
            row = [sum(m >= d for m in maxima) / len(maxima) for d in levels]
            previous = row if previous is None else [max(a, b) for a, b in zip(previous, row)]
        if previous is None:
            return None
        low, row = 1.0, []
        for v in previous:
            low = min(low, v)
            row.append(low)
        out.append(row)
    return out


@register
class SeasonalRecordV110(SeasonalRecord):
    """1.0.0 plus a new-game base for games without own records (low_base) and seen levels shrunk toward the
    population share (shrink, in sales). low_base = population with shrink = 0 is 1.0.0 bit for bit."""

    version = "1.1.0"

    def __init__(self, min_sales: int = 1, half_life: float = 2, hazard_history: str = "TW+US",
                 low_base: str = "population", shrink: float = 0):
        super().__init__(min_sales, half_life, hazard_history)
        if low_base not in LOW_BASES:
            raise ValueError(f"low_base 必須是 {LOW_BASES} 之一：{low_base!r}")
        if isinstance(shrink, bool) or not isinstance(shrink, (int, float)) or shrink < 0:
            raise ValueError(f"shrink 必須是 ≥ 0 的數字：{shrink!r}")
        self.low_base = low_base
        self.shrink = _number(shrink)
        self._new_sequences: dict[str, list[list[int]]] = {}
        self._cumulative: dict[tuple, list[list[float]] | None] = {}
        self._as_of: date | None = None

    @classmethod
    def from_params(cls, raw: Mapping[str, Any]) -> "SeasonalRecordV110":
        unknown = set(raw) - {"min_sales", "half_life", "hazard_history", "low_base", "shrink"}
        if unknown:
            raise ValueError(f"seasonal-record 1.1.0 沒有這些參數：{', '.join(sorted(unknown))}")
        base = SeasonalRecord.from_params({k: v for k, v in raw.items() if k not in ("low_base", "shrink")})
        kwargs: dict[str, Any] = {"min_sales": base.min_sales, "half_life": base.half_life,
                                  "hazard_history": base.hazard_history}
        if "low_base" in raw:
            kwargs["low_base"] = str(raw["low_base"])
        if "shrink" in raw:
            try:
                kwargs["shrink"] = float(raw["shrink"])
            except (TypeError, ValueError):
                raise ValueError(f"shrink 必須是數字：{raw['shrink']!r}") from None
        return cls(**kwargs)

    @property
    def params(self) -> dict[str, Any]:
        return {**super().params, "low_base": self.low_base, "shrink": self.shrink}

    @staticmethod
    def grid_exclusion(params: Mapping[str, Any]) -> str | None:
        """spec FR-003: a setting that leaves the seen levels unshrunk is shown in the grid but never chosen."""
        return "fr-003" if float(params.get("shrink", 0)) == 0 else None

    def confidence_levels(self) -> dict[str, str]:
        levels = super().confidence_levels()
        if self.low_base == "population":
            return levels
        low = (f"本身已結束的季節特賣紀錄少於 {self.min_sales} 場（多半是新遊戲）：改用參考資料集中新遊戲"
               "（發行 1 年內開始有紀錄）前幾場的實際比例")
        if self.low_base == "new-split":
            low += "；尚未發行的遊戲改用發售前就有季節特賣紀錄的遊戲"
        return {**levels, "low": low}

    # --- preparation ---------------------------------------------------------------------------------------------

    def prepare(self, population: PopulationView) -> None:
        super().prepare(population)
        self._as_of = population.as_of.date()
        self._cumulative = {}
        groups: dict[str, list[list[int]]] = {"all-new": [], "pre-release": [], "released": []}
        for app, history in population.sale_history.items():
            own = history.get(population.target_region, ())      # a US target sees only US records
            release = population.release_dates.get(app)
            if not own or release is None or own[0].start.date() - release > timedelta(days=NEW_GAME_DAYS):
                continue
            cuts = [o.max_cut for o in own]
            groups["all-new"].append(cuts)
            groups["pre-release" if own[0].start.date() < release else "released"].append(cuts)
        self._new_sequences = groups

    def _table(self, key: str, k_max: int, levels: Sequence[int]) -> list[list[float]] | None:
        cache = (key, k_max, tuple(levels))
        if cache not in self._cumulative:
            self._cumulative[cache] = empirical_cumulative(self._new_sequences.get(key, ()), k_max, levels)
        return self._cumulative[cache]

    # --- prediction ----------------------------------------------------------------------------------------------

    def predict(self, game: GameEvidence, points: Sequence[SalePoint], levels: Sequence[int]) -> ModelOutput:
        out = super().predict(game, points, levels)
        if out.confidence == "low":
            return out if self.low_base == "population" else self._low(game, points, levels, out)
        return self._shrunk(game, points, levels, out) if self.shrink else out

    def _low(self, game, points, levels, base: ModelOutput) -> ModelOutput:
        release = game.release_date
        unreleased = release is not None and self._as_of is not None and release > self._as_of
        key = "all-new" if self.low_base == "new" else "pre-release" if unreleased else "released"
        n = len(self._new_sequences.get(key, ()))
        if unreleased:
            first = f"尚未發行（預定 {release.isoformat()}），本身沒有季節特賣紀錄"
        elif release is not None:
            first = f"本身沒有已結束的季節特賣紀錄（發行於 {release.isoformat()}）"
        else:
            first = "本身沒有已結束的季節特賣紀錄（發行日未知，視為已發行）"
        evidence = {**base.evidence, "low_sequences": key, "new_games": n,
                    "release_date": release.isoformat() if release else None}
        table = self._table(key, len(points), levels) if points else None
        if table is None:
            thin = (f"參考資料集中{SEQUENCE_PHRASES[key].format(n=n)}，樣本不足 {MIN_SEQUENCES} 款，"
                    "改用全體遊戲每場季節特賣的比例")
            return replace(base, reasons=(first, thin, *base.reasons), evidence=evidence)
        reasons = (first, self._table_reason(key, n, table, levels),
                   "新遊戲前幾場的折扣通常比老遊戲淺，所以不用全體遊戲的比例")
        return ModelOutput(tuple(tuple(row) for row in table), "low", reasons, evidence)

    @staticmethod
    def _table_reason(key: str, n: int, table: list[list[float]], levels: Sequence[int]) -> str:
        head = f"參考資料集中{SEQUENCE_PHRASES[key].format(n=n)}："
        firsts = table[0]
        j = max((i for i, v in enumerate(firsts) if v >= 0.5), default=None)
        if j is None:
            text = f"第 1 場有打折的比例只有 {firsts[0]:.0%}"
            j = 0
        else:
            text = f"第 1 場達到 -{levels[j]}% 的比例 {firsts[j]:.0%}"
        k = min(len(table), 4)
        if k > 1:
            text += f"、前 {k} 場 {table[k - 1][j]:.0%}"
        return head + text

    def _shrunk(self, game, points, levels, base: ModelOutput) -> ModelOutput:
        own = self._freq._history(game.sale_history, game.target_region)
        cuts = [o.max_cut for o in own]
        n = len(cuts)
        weights = [0.5 ** ((n - 1 - i) / self.half_life) if self.half_life else 1.0 for i in range(n)]
        total = sum(weights)
        m5, s, _ = record_state(cuts)
        pool_total, at_least = self._freq._pool
        a = self.shrink
        raw = {d: sum(w for w, c in zip(weights, cuts) if c >= d) / total for d in levels if d <= m5}
        shares = {d: (n * p + a * at_least[d] / pool_total) / (n + a) for d, p in raw.items()}
        survive, acc = [], 1.0
        for j in range(len(points)):
            acc *= 1.0 - self.table.rate(m5, min(s + j, S_CAP))
            survive.append(acc)
        rows = []
        for k in range(1, len(points) + 1):
            row, low = [], 1.0
            for j, d in enumerate(levels):
                v = 1.0 - (1.0 - shares[d]) ** k * survive[k - 1] if d <= m5 else base.probabilities[k - 1][j]
                low = min(low, v)                     # a shrunk seen level may fall below the deeper chain
                row.append(low)
            rows.append(tuple(row))
        evidence = {**base.evidence, "shrink": a, "own_share_raw": raw.get(m5)}
        reasons = base.reasons
        if n <= SHRINK_REASON_MAX_SALES and m5 in raw and points:
            j = list(levels).index(m5)
            before, after = base.probabilities[0][j], rows[0][j]
            if round(before, 2) != round(after, 2):
                line = (f"本身只有 {n} 場紀錄，見過的折扣向參考資料集的比例靠攏（等同多看 {a} 場整體的特賣）："
                        f"下一場 ≥ -{m5}% 為 {after:.0%}，不是 {before:.0%}")
                reasons = (*reasons[:-1], line, reasons[-1])
        return ModelOutput(tuple(rows), "normal", reasons, evidence)
