"""008 plan R0.5: the real wishlist now, seasonal-record 1.0.0 vs candidates, rule 2.1.0 (read-only, no record).
Writes out/p12_wishlist.md (contains wishlist names; out/ is git-ignored)."""

import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(r"〈專案資料夾〉")
sys.path.insert(0, str(ROOT / "src"))
from candidate import Candidate  # noqa: E402

from steamsage.config import Preferences  # noqa: E402
from steamsage.decision.engine import run_decisions  # noqa: E402
from steamsage.forecast.engine import all_apps  # noqa: E402
from steamsage.forecast.models import current_model  # noqa: E402
from steamsage.store.query import PriceStore  # noqa: E402
from steamsage.timeutil import now_utc  # noqa: E402

t0 = time.monotonic()
store = PriceStore.open(ROOT / "data" / "steamsage.db", ROOT / "data" / "steam_sales.toml")
now = now_utc()
release = {a: store.facts(a, now).release_date.value for a in all_apps(store)}
apps = store.wishlist_apps()
specs = {"1.0.0": current_model(), "新遊戲": Candidate(release, "new_split", 0, "n", "pop"),
         "新遊戲＋收縮 0.5": Candidate(release, "new_split", 0.5, "n", "pop")}
batches = {k: run_decisions(store, apps, now, m, Preferences(), now=now, rule="2.1.0") for k, m in specs.items()}
store.close()
lines = [f"# 願望清單（{now:%Y-%m-%d %H:%M} UTC，規則 2.1.0）\n"]
base = {d.app_id: d for d in batches["1.0.0"].decisions}
fc = {k: {g.app_id: g for g in b.forecast.games} for k, b in batches.items()}
for k, b in batches.items():
    c = Counter(d.group for d in b.decisions if d.status == "ok")
    lines.append(f"- {k}：現在買 {c['now']}、即將到價 {c['soon']}、繼續等 {c['wait']}、低信心 {c['low']}")
lines.append("\n| 遊戲 | 本身場數 | 信心 | 1.0.0 | 新遊戲 | 新遊戲＋收縮 0.5 |\n|---|---|---|---|---|---|")
for k in ("新遊戲", "新遊戲＋收縮 0.5"):
    pass
changed = 0
for app, d0 in sorted(base.items(), key=lambda x: x[1].name or ""):
    if d0.status != "ok":
        continue
    ds = [next(d for d in batches[k].decisions if d.app_id == app) for k in specs]
    sig = [(d.group, d.sweet_pct, d.sweet_point.label if d.sweet_point else None, d.sweet_probability) for d in ds]
    if len({s[:3] for s in sig}) == 1 and abs((sig[0][3] or 0) - (sig[-1][3] or 0)) < 0.005:
        continue
    changed += 1
    g = fc["1.0.0"][app]
    n = (g.evidence or {}).get("sales_used")
    cell = lambda s: f"{s[0]} -{s[1]}% {s[2]}（{(s[3] or 0):.0%}）"  # noqa: E731
    lines.append(f"| {d0.name[:28]} | {n} | {g.confidence} | " + " | ".join(cell(s) for s in sig) + " |")
lines.append(f"\n改變（分組、甜蜜價、時點或機率 ≥ 0.5 個百分點）：{changed} 款；耗時 {time.monotonic() - t0:.0f} 秒")
out = Path(__file__).parent / "out" / "p12_wishlist.md"
out.write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
