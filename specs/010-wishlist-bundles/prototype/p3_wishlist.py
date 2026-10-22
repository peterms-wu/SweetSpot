"""P3 (plan, read-only, offline): the candidate bundle-advice rule on today's wishlist (research R0.3).

Inputs: the latest decision record in data/forecasts/ and out/s1.json, out/s2.json (Steam bundle facts).
Per pure bundle: bundle now (Steam), separately now, the separate plan (sweet price per game, or the current price
when the game is "現在買"; the latest sweet point), and the next seasonal sale's estimate: the cheapest level
combination whose joint next-sale probability (M1, independence) is >= 0.5, times (1 - bundle discount).
Advice: now if bundle now <= plan; else the next sale if it is not later than the latest sweet point, the joint
probability is >= 0.5 and the estimate <= plan; else "separately".
"""
import gzip
import itertools
import json
import sys
from pathlib import Path

OUT = Path(__file__).parent / "out"
record = Path(sys.argv[1]) if len(sys.argv) > 1 else sorted(Path("data/forecasts").glob("*.json.gz"))[-1]
batch = json.load(gzip.open(record))
dec = {d["app_id"]: d for d in batch["decisions"]}
fc = {g["app_id"]: g for g in batch["forecast"]["games"]}
levels = batch["forecast"]["levels"]
s1 = json.loads((OUT / "s1.json").read_text(encoding="utf-8"))
s2 = json.loads((OUT / "s2.json").read_text(encoding="utf-8"))
bopt = {it["id"]: it["best_purchase_option"] for it in s2["bundles"]["response"]["store_items"]}
THRESHOLD = 0.5
print("record", record.name, "as_of", batch["as_of"])


def twd(cents):
    return f"NT${cents / 100:,.0f}"


for bid, b in s1["multi"].items():
    wl = [it for it in b["items"] if it["wishlist"]]
    pure = all(it["wishlist"] or it["parent_in_wishlist"] for it in b["items"])
    o = bopt[int(bid)]
    k = 1 - o.get("bundle_discount_pct", 0) / 100
    now = int(o["final_price_in_cents"])
    print(f"\n== bundle/{bid} {b['name']}  ({'純粹' if pure else '混合'}, -{o.get('bundle_discount_pct')}%)  現價 {twd(now)}")
    if not pure:
        wl_now = sum(dec[it["app_id"]]["current"]["price_cents"] for it in wl)
        extra = [it for it in b["items"] if not it["wishlist"]]
        print(f"   只買願望清單遊戲 {twd(wl_now)}；多付 {twd(now - wl_now)}，多得 {len(extra)} 個內容")
        continue
    ds = [dec[it["app_id"]] for it in wl]
    sep_now = sum(d["current"]["price_cents"] for d in ds)
    formula = round(k * sep_now)
    plan = sum(d["current"]["price_cents"] if d["group"] == "now" else d["sweet_cents"] for d in ds)
    points = [d["sweet_point"]["index"] if d["group"] != "now" and d.get("sweet_point") else 0 for d in ds]
    latest = max(points)
    print(f"   分開買現價 {twd(sep_now)}；公式 {twd(formula)}（Steam {twd(now)}，差 {now - formula} 分）")
    for d in ds:
        sp = d.get("sweet_point") or {}
        print(f"   - {d['name']}: {d['group']}, 現價 {twd(d['current']['price_cents'])}, 甜蜜價 {twd(d['sweet_cents'])} "
              f"-{d['sweet_pct']}% @ {sp.get('label')}")
    print(f"   各自在甜蜜時點買 {twd(plan)}，最晚 {'現在' if latest == 0 else 'point ' + str(latest)}")
    nxt = fc[ds[0]["app_id"]]["curve"]["points"][0]
    rows = [[1.0] + fc[d["app_id"]]["curve"]["probabilities"][0] for d in ds]
    regs = [d["regular_cents"] for d in ds]
    best = None
    for combo in itertools.product(range(len(levels) + 1), repeat=len(ds)):
        q = 1.0
        for r, x in zip(rows, combo):
            q *= r[x]
        if q < THRESHOLD:
            continue
        price = sum(reg * (100 - ([0] + levels)[x]) for reg, x in zip(regs, combo)) / 100
        if best is None or price < best[0] or (price == best[0] and q > best[1]):
            best = (price, q, [([0] + levels)[x] for x in combo])
    est = round(k * best[0])
    print(f"   {nxt['label']}：各款 {best[2]}，組合包約 {twd(est)}，同時到價 {best[1]:.0%}")
    if now <= plan:
        advice = f"現在買組合包：{twd(now)}，比各自在甜蜜時點買便宜 {twd(plan - now)}"
    elif latest >= 1 and est <= plan:
        advice = (f"{nxt['label']}買組合包：約 {twd(est)}（同時到價 {best[1]:.0%}），比各自在甜蜜時點買便宜 {twd(plan - est)}"
                  + ("，而且更早" if latest > 1 else ""))
    else:
        advice = f"各自在甜蜜時點分開買較划算；同一場特賣兩款都買時，組合包仍便宜 {o.get('bundle_discount_pct')}%"
    print("   建議：" + advice)
