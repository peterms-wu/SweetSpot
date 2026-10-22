"""Prototype candidate (not registered): seasonal-record 1.0.0 plus the two 008 changes.

low_base   "pop"        1.0.0: population per-sale share
           "new"        empirical cumulative of new-game sequences (first record <= 365 days after release): among
                        sequences with >= k records, the share whose max of the first k >= d (p8 B5)
           "new_split"  like "new", separate sequences for targets not yet released at as_of (p8 B6)
shrink_a   prior weight toward a target share for the seen levels (0 = 1.0.0)
shrink_form "w": p = (Σ w·[c ≥ d] + a·t(d)) / (Σ w + a)   (weights = recency weights)
            "n": p = (n·p_w(d) + a·t(d)) / (n + a)        (n = number of own records)
shrink_target "pop": population per-sale share; "mgroup": share of records reaching d among records whose game's
            previous deepest cut was in the same M group as this game
Release dates come from a dict given at construction (static facts).
"""

from dataclasses import replace
from datetime import timedelta

import numpy as np

from steamsage.forecast.models.seasonal_record import S_CAP, SeasonalRecord, f5, m_group, record_state

NEW_DAYS = 365
MIN_SEQ = 30


def cumulative(seqs, K, levels):
    L = np.array(levels)
    out = np.zeros((K, len(L)))
    prev = None
    for k in range(1, K + 1):
        ms = [max(s[:k]) for s in seqs if len(s) >= k]
        if len(ms) >= MIN_SEQ:
            row = (np.array(ms)[:, None] >= L[None, :]).mean(axis=0)
            prev = row if prev is None else np.maximum(prev, row)
        out[k - 1] = prev if prev is not None else 0
    return out


class Candidate(SeasonalRecord):
    def __init__(self, release, low_base="new_split", shrink_a=0.0, shrink_form="n", shrink_target="pop"):
        super().__init__(min_sales=1, half_life=2, hazard_history="TW+US")
        self.release, self.low_base = release, low_base
        self.shrink_a, self.shrink_form, self.shrink_target = shrink_a, shrink_form, shrink_target

    @property
    def tag(self):
        return f"{self.low_base}_a{self.shrink_a:g}{self.shrink_form}{self.shrink_target}"

    def prepare(self, population):
        super().prepare(population)
        self._as_of = population.as_of
        new, pre, post = [], [], []
        mg = {g: [0, np.zeros(101)] for g in range(4)}
        region = population.target_region            # a US target sees only US records
        for app, h in population.sale_history.items():
            tw = h.get(region, ())
            if not tw:
                continue
            cuts = [o.max_cut for o in tw]
            for i in range(1, len(cuts)):
                g = m_group(f5(max(cuts[:i])))
                mg[g][0] += 1
                mg[g][1][cuts[i]] += 1
            r = self.release.get(app)
            if r is None or tw[0].start.date() - r > timedelta(days=NEW_DAYS):
                continue
            new.append(cuts)
            (pre if tw[0].start.date() < r else post).append(cuts)
        self._seqs = {"new": new, "pre": pre, "post": post}
        self._mg = {g: (n, np.cumsum(c[::-1])[::-1]) for g, (n, c) in mg.items()}
        self._cum = {}

    def _low_curve(self, key, K, levels):
        if (key, K) not in self._cum:
            self._cum[(key, K)] = cumulative(self._seqs[key], K, levels)
        return self._cum[(key, K)]

    def predict(self, game, points, levels):
        out = super().predict(game, points, levels)
        K = len(points)
        if out.confidence == "low":
            if self.low_base == "pop":
                return out
            key = "new"
            if self.low_base == "new_split":
                r = self.release.get(game.app_id)
                key = "pre" if r is not None and r > self._as_of.date() else "post"
            curve = self._low_curve(key, K, levels)
            return replace(out, probabilities=tuple(tuple(float(v) for v in row) for row in curve))
        if not self.shrink_a:
            return out
        own = self._freq._history(game.sale_history, game.target_region)
        cuts = [o.max_cut for o in own]
        n = len(cuts)
        weights = [0.5 ** ((n - 1 - i) / self.half_life) for i in range(n)]
        total = sum(weights)
        m5, s, _ = record_state(cuts)
        pool_total, at_least = self._freq._pool
        if self.shrink_target == "mgroup" and self._mg[m_group(m5)][0] >= 20:
            cnt, ge = self._mg[m_group(m5)]
            target = {d: ge[d] / cnt for d in levels}
        else:
            target = {d: at_least[d] / pool_total for d in levels}
        survive, acc = [], 1.0
        for j in range(K):
            acc *= 1.0 - self.table.rate(m5, min(s + j, S_CAP))
            survive.append(acc)
        a = self.shrink_a
        shares = {}
        for d in levels:
            if d > m5:
                continue
            pw = sum(w for w, c in zip(weights, cuts) if c >= d)
            shares[d] = (pw + a * target[d]) / (total + a) if self.shrink_form == "w" \
                else (n * pw / total + a * target[d]) / (n + a)
        rows = []
        for k in range(1, K + 1):
            r, lo = [], 1.0
            for j, d in enumerate(levels):
                v = 1.0 - (1.0 - shares[d]) ** k * survive[k - 1] if d <= m5 else out.probabilities[k - 1][j]
                lo = min(lo, v)
                r.append(lo)
            rows.append(tuple(r))
        return replace(out, probabilities=tuple(rows))
