"""Structural probe (not a registered model): seasonal-record 1.0.0 with the seen-level per-sale share shrunk toward
the population share, p_w(d) = (Σ w·[cut ≥ d] + a·b(d)) / (Σ w + a), b(d) = seasonal-freq's population share.
With 1 own sale at -50% and a = 1, "next sale ≥ -50%" is no longer 100%. Deeper levels (the record chain) unchanged."""

from dataclasses import replace

from steamsage.forecast.models.seasonal_record import S_CAP, SeasonalRecord, record_state


class Shrunk(SeasonalRecord):
    def __init__(self, a: float):
        super().__init__(min_sales=1, half_life=2, hazard_history="TW+US")
        self.a = a

    def predict(self, game, points, levels):
        out = super().predict(game, points, levels)
        if out.confidence != "normal":
            return out
        own = self._freq._history(game.sale_history, game.target_region)
        cuts = [o.max_cut for o in own]
        n = len(cuts)
        weights = [0.5 ** ((n - 1 - i) / self.half_life) for i in range(n)]
        total = sum(weights)
        m5, s, _ = record_state(cuts)
        pool_total, at_least = self._freq._pool
        survive, acc = [], 1.0
        for j in range(len(points)):
            acc *= 1.0 - self.table.rate(m5, min(s + j, S_CAP))
            survive.append(acc)
        shares = {d: (sum(w for w, c in zip(weights, cuts) if c >= d) + self.a * at_least[d] / pool_total)
                  / (total + self.a) for d in levels if d <= m5}
        probs = tuple(
            tuple(1.0 - (1.0 - shares[d]) ** k * survive[k - 1] if d <= m5 else out.probabilities[k - 1][j]
                  for j, d in enumerate(levels))
            for k in range(1, len(points) + 1))
        # the deeper chain can exceed a shrunk seen level; keep the curve monotone in d (deeper never more likely)
        fixed = []
        for row in probs:
            r, lo = list(row), 1.0
            for j in range(len(r)):
                lo = min(lo, r[j])
                r[j] = lo
            fixed.append(tuple(r))
        return replace(out, probabilities=tuple(fixed))
