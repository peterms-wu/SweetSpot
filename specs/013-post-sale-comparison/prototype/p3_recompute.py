"""P3 (spec US5): recompute at the pre-sale record's as_of with today's database — the current model through the
whole decision path, and the baseline model's forecast — and compare with the record. Times each step.

Usage: uv run python specs/013-post-sale-comparison/prototype/p3_recompute.py   (after p1_actual.py)
"""

import json
import time
from pathlib import Path

from steamsage.config import load_config
from steamsage.decision.engine import run_decisions
from steamsage.forecast.contract import LEVELS
from steamsage.forecast.engine import run_forecast
from steamsage.forecast.models import build_model, current_model

from common import MAIN, autumn_2026, load_record, open_store, parse_time, pre_sale_record

OUT = Path(__file__).parent / "out"


def brier(probs_by_app: dict[int, list[float]], actual: dict[int, int]) -> tuple[float, int]:
    per = []
    for app, p in probs_by_app.items():
        if app in actual:
            m = actual[app]
            per.append(sum((p[i] - int(m >= lvl)) ** 2 for i, lvl in enumerate(LEVELS)) / len(LEVELS))
    return sum(per) / len(per), len(per)


def autumn_probs(games) -> dict[int, list[float]]:
    out = {}
    for g in games:
        points = (g.get("curve") or {}).get("points") or []
        if points and points[0].get("label") == "2026 秋特":
            out[g["app_id"]] = g["curve"]["probabilities"][0]
    return out


def main() -> None:
    store = open_store()
    sale = autumn_2026(store)
    _, path = pre_sale_record(sale)
    rec = load_record(path)
    as_of = parse_time(rec["as_of"])
    apps = [d["app_id"] for d in rec["decisions"]]
    config, _ = load_config(MAIN / "steamsage.toml")
    choices = {d["app_id"]: (d["version"]["option"]["kind"], d["version"]["option"]["id"])
               for d in rec["decisions"] if (d.get("version") or {}).get("source") == "user"}
    print("choices from the record:", choices, "| preferences equal:",
          {k: v for k, v in rec["preferences"].items()} == {k: getattr(config.preferences, k) for k in rec["preferences"]})

    t = time.monotonic()
    batch = run_decisions(store, apps, as_of, current_model(), config.preferences, choices=choices, official=False)
    t_dec = time.monotonic() - t
    from steamsage.decision.contract import batch_to_dict
    again = json.loads(json.dumps(batch_to_dict(batch), ensure_ascii=False))
    t = time.monotonic()
    base = run_forecast(store, apps, as_of, build_model("seasonal-freq", {"min_sales": 2, "history": "TW"}))
    t_base = time.monotonic() - t
    from steamsage.forecast.contract import batch_to_dict as fc_to_dict
    base_d = json.loads(json.dumps(fc_to_dict(base), ensure_ascii=False))
    print(f"recompute decisions {t_dec:.1f}s, baseline forecast {t_base:.1f}s")

    old = {d["app_id"]: d for d in rec["decisions"]}
    new = {d["app_id"]: d for d in again["decisions"]}
    diff_group = [(old[a]["name"], old[a]["group"], new[a]["group"]) for a in apps if old[a]["group"] != new[a]["group"]]
    diff_sweet = [(old[a]["name"], old[a].get("sweet_cents"), new[a].get("sweet_cents")) for a in apps
                  if old[a].get("sweet_cents") != new[a].get("sweet_cents")]
    p_old, p_new = autumn_probs(rec["forecast"]["games"]), autumn_probs(again["forecast"]["games"])
    p_base = autumn_probs(base_d["games"])
    maxdiff = {a: max(abs(x - y) for x, y in zip(p_old[a], p_new[a])) for a in p_old if a in p_new}
    print("group differs:", diff_group)
    print("sweet price differs:", diff_sweet)
    print("autumn probabilities: games with max |diff| > 1e-6:", sum(v > 1e-6 for v in maxdiff.values()),
          "of", len(maxdiff), "; largest", sorted(maxdiff.items(), key=lambda kv: -kv[1])[:5])

    rows = json.loads((OUT / "p1_actual.json").read_text(encoding="utf-8"))
    actual = {r["app"]: r["sale_max_cut"] for r in rows if r.get("sale_max_cut") is not None}
    for name, probs in (("record", p_old), ("recomputed current", p_new), ("baseline seasonal-freq", p_base)):
        b, n = brier(probs, actual)
        print(f"Brier (sale max cut, game-weighted) {name}: {b:.4f} over {n} games")


if __name__ == "__main__":
    main()
