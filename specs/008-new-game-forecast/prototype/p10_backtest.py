"""008 plan R0.3 (tuning split, cutoff 2026-09-25): the production two-region backtest and comparison (002 FR-029
computation) for seasonal-record 1.0.0 and prototype candidates. Read-only; no result files are written.

uv run --with numpy python p10_backtest.py new_split,0.5,n,pop [more candidates ...]
"""

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(r"〈專案資料夾〉")
sys.path.insert(0, str(ROOT / "src"))
from candidate import Candidate  # noqa: E402

from steamsage.forecast.backtest.compare import compare_results  # noqa: E402
from steamsage.forecast.backtest.dataset import build_dataset  # noqa: E402
from steamsage.forecast.backtest.runner import run_backtest  # noqa: E402
from steamsage.forecast.engine import all_apps, load_games  # noqa: E402
from steamsage.forecast.models import current_model  # noqa: E402
from steamsage.store.query import PriceStore  # noqa: E402

CUTOFF = datetime(2026, 9, 25, tzinfo=UTC)
OUT = Path(__file__).parent / "out"
t0 = time.monotonic()
store = PriceStore.open(ROOT / "data" / "steamsage.db", ROOT / "data" / "steam_sales.toml")
games = load_games(store, all_apps(store), CUTOFF)
events = store.calendar_events()
dataset = build_dataset(store, games, events, cutoff=CUTOFF, split="tuning")
release = {a: store.facts(a, CUTOFF).release_date.value for a in all_apps(store)}
print({r: (rd.dataset_id[:8], len(rd.apps)) for r, rd in dataset.regions.items()}, f"load {time.monotonic() - t0:.0f}s",
      flush=True)


def run(model, label):
    t1 = time.monotonic()
    result, _ = run_backtest(store, dataset, games, events, model)
    print(f"{label}: TW {result['regions']['TW']['brier']:.4f}, US {result['regions']['US']['brier']:.4f}, "
          f"errors {len(result['errors'])}, {time.monotonic() - t1:.0f}s", flush=True)
    return result


base = run(current_model(), "1.0.0")
summary = {"1.0.0": {"TW": base["regions"]["TW"]["brier"], "US": base["regions"]["US"]["brier"],
                     "by_own_sales": base["regions"]["TW"]["by_own_sales"],
                     "us_by_conf": base["regions"]["US"].get("by_confidence")}}
for spec in sys.argv[1:]:
    lb, a, form, target = spec.split(",")
    model = Candidate(release, lb, float(a), form, target)
    res = run(model, model.tag)
    cmp = compare_results(base, res)
    print("  " + " / ".join(cmp.reasons) + f" → {cmp.verdict}")
    print("  TW by_own_sales:", {g["group"]: (round(g["brier"], 4) if g["brier"] is not None else None, g.get("games"))
                                  for g in res["regions"]["TW"]["by_own_sales"]})
    print("  US by_confidence:", res["regions"]["US"].get("by_confidence"))
    summary[model.tag] = {"TW": res["regions"]["TW"]["brier"], "US": res["regions"]["US"]["brier"],
                          "verdict": cmp.verdict, "reasons": cmp.reasons,
                          "by_own_sales": res["regions"]["TW"]["by_own_sales"]}
print("1.0.0 TW by_own_sales:", {g["group"]: round(g["brier"], 4) for g in base["regions"]["TW"]["by_own_sales"]
                                 if g["brier"] is not None})
store.close()
(OUT / "p10_backtest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
print(f"total {time.monotonic() - t0:.0f}s")
