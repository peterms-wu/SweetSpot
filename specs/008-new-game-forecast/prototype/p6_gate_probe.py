"""008 spec question: would an improvement concentrated in few games pass 002 FR-029 (whole TW Brier, game-equal
weights, game-paired resampling)? Structural probe variants vs raw on the tuning split (002 scoring)."""
import numpy as np
from ulib import load

raw = load()
u0 = raw["units"]
rng = np.random.default_rng(int(raw["dataset_id"][:8], 16))


def per_game(u, key, sel):
    ok = (u[key] >= 0) & sel
    e = (u["p"] - u[key]) ** 2
    apps, inv = np.unique(u["app"][ok], return_inverse=True)
    return apps, np.bincount(inv, weights=e[ok]) / np.bincount(inv)


for name in ("cache_shrink0.5.pkl", "cache_shrink1.pkl", "cache_shrink2.pkl"):
    v = load(name)["units"]
    assert (v["app"] == u0["app"]).all() and (v["off"] == u0["off"]).all()
    for key in ("off", "fin"):
        for label, sel0 in (("全部", np.ones(len(u0["p"]), bool)), ("本身 1 場", (u0["sales"] == 1) & (u0["conf"] == 0))):
            a, b0 = per_game(u0, key, sel0)
            _, b1 = per_game(v, key, sel0)
            d = b1 - b0
            boots = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(2000)]
            lo, hi = np.percentile(boots, [2.5, 97.5])
            print(f"{name:22s} {key} {label:5s} games {len(d):5d}  raw {b0.mean():.4f}  new {b1.mean():.4f}  "
                  f"diff {d.mean():+.4f} [{lo:+.4f}, {hi:+.4f}]")
