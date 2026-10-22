"""Shared helpers for the 008 first-step prototypes: load the stage-0 cache and summarise calibration."""

import pickle
from pathlib import Path

import numpy as np

OUT = Path(__file__).parent / "out"


def load(name="cache.pkl"):
    with open(OUT / name, "rb") as fh:
        data = pickle.load(fh)
    units = {}
    for k, raw in data["units"].items():
        units[k] = np.frombuffer(raw, dtype={"b": np.int8, "i": np.int32, "h": np.int16, "d": np.float64}[
            data["unit_types"][k]]).copy()
    data["units"] = units
    return data


def summary(p, y):
    n = len(p)
    if n == 0:
        return {"n": 0}
    hi = p >= 0.7
    return {"n": n, "pred": p.mean(), "act": y.mean(), "brier": ((p - y) ** 2).mean(),
            "hi_n": int(hi.sum()), "hi_gap": (p[hi].mean() - y[hi].mean()) if hi.any() else None}


def bins(p, y, width=0.1):
    b = np.minimum((p / width).astype(int), int(round(1 / width)) - 1)
    out = []
    for i in range(int(round(1 / width))):
        m = b == i
        if m.any():
            out.append((i * width, int(m.sum()), p[m].mean(), y[m].mean()))
    return out


def fmt_row(name, s):
    if s["n"] == 0:
        return f"| {name} | 0 | — | — | — | — |"
    hi = "—" if s["hi_gap"] is None else f"{s['hi_gap'] * 100:+.1f}（{s['hi_n']:,}）"
    return (f"| {name} | {s['n']:,} | {s['pred']:.3f} → {s['act']:.3f} | {s['brier']:.4f} | {hi} |")


# ---- past-only isotonic maps (same as p2_iso.py) -------------------------------------------------------------
MIN_FIT = 5000


def pav(x, y, w):
    vals, wts, cnt = [], [], []
    for yi, wi in zip(y, w):
        vals.append(yi); wts.append(wi); cnt.append(1)
        while len(vals) > 1 and vals[-2] > vals[-1]:
            v = (vals[-2] * wts[-2] + vals[-1] * wts[-1]) / (wts[-2] + wts[-1])
            vals[-2:], wts[-2:], cnt[-2:] = [v], [wts[-2] + wts[-1]], [cnt[-2] + cnt[-1]]
    out = []
    for v, c in zip(vals, cnt):
        out.extend([v] * c)
    return np.array(out)


def fit(p, y, nbins=200):
    if len(p) < MIN_FIT:
        return None
    b = np.minimum((p * nbins).astype(int), nbins - 1)
    w = np.bincount(b, minlength=nbins).astype(float)
    sp = np.bincount(b, weights=p, minlength=nbins)
    sy = np.bincount(b, weights=y, minlength=nbins)
    keep = w > 0
    x, yy, ww = sp[keep] / w[keep], sy[keep] / w[keep], w[keep]
    return x, pav(x, yy, ww)


def apply(m, p):
    return p if m is None else np.interp(p, m[0], m[1])


def make_maps(data):
    """At every as_of: fit on units of earlier as_of whose sale ended (and was known) before this as_of."""
    u, schedule = data["units"], data["schedule"]
    maps = {"iso": {}, "iso_conf": {}}
    for ti, t in enumerate(schedule):
        train = (u["t"] < ti) & (u["fin"] >= 0) & (u["end"] > 0) & (u["end"] <= t.timestamp())
        g = fit(u["p"][train], u["fin"][train].astype(float))
        maps["iso"][t] = {"normal": g, "low": g}
        maps["iso_conf"][t] = {c: fit(u["p"][train & (u["conf"] == i)], u["fin"][train & (u["conf"] == i)].astype(float))
                               for i, c in enumerate(("normal", "low"))}
    return maps
