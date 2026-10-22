"""Offline: at every change point and in every past seasonal sale, bundle price vs separate sums (ITAD histories)."""
import bisect, json
from datetime import datetime, timezone
from pathlib import Path
from steamsage.calendar import load_calendar, label
OUT = Path(__file__).parent / "out"
s1 = json.loads((OUT / "s1.json").read_text(encoding="utf-8"))
s3 = json.loads((OUT / "s3.json").read_text(encoding="utf-8"))
s4 = json.loads((OUT / "s4.json").read_text(encoding="utf-8"))
now = datetime(2026, 9, 27, 3, tzinfo=timezone.utc)
events = [e for e in load_calendar(Path("data/steam_sales.toml"), now=now) if e.kind == "seasonal" and e.end <= now]
P = lambda s: datetime.fromisoformat(s)
def series(region, g):
    h = s4["hist"].get(f"{region}:{g}") or []
    return [P(x[0]) for x in h], [x[1] for x in h]
def at(ser, t):
    ts, ps = ser
    i = bisect.bisect_right(ts, t) - 1
    return ps[i] if i >= 0 else None
summary = {}
for region in ("TW", "US"):
    print(f"\n######## {region}")
    for bid, b in s1["multi"].items():
        g = s4["bprod"][bid]; bs = series(region, g)
        if not bs[0]: print(bid, "no history"); continue
        items = [(it["app_id"], it["wishlist"], series(region, s4["aprod"][str(it["app_id"])])) for it in b["items"]]
        start = max([bs[0][0]] + [s[0][0] for _, _, s in items if s[0]])
        # all change points after every series has started
        pts = sorted({t for t in bs[0] if t >= start} | {t for _, _, s in items for t in s[0] if t >= start} | {start})
        ratios = []
        for t in pts:
            bp = at(bs, t); parts = [at(s, t) for _, _, s in items]
            if bp is None or None in parts: continue
            ratios.append(round(bp / sum(parts), 3))
        rset = {}
        for r in ratios: rset[r] = rset.get(r, 0) + 1
        print(f"\nbundle/{bid} {b['name'][:30]} {region} bundle from {bs[0][0].date()} all items from {start.date()}  bundle/sum-all ratios at {len(ratios)} change points: {sorted(rset.items(), key=lambda x:-x[1])[:6]}")
        rows = []
        for e in events:
            if e.end <= start: continue
            # moments inside the sale: sale start (+1h) and every change point in the sale
            ms = [max(e.start, start)] + [t for t in pts if e.start <= t < e.end]
            ms = sorted(set(ms))
            best_b = best_sep = best_wl = None
            for t in ms:
                bp = at(bs, t); parts = [(w, at(s, t)) for _, w, s in items]
                if bp is None or any(p is None for _, p in parts): continue
                sep = sum(p for _, p in parts); wl = sum(p for w, p in parts if w)
                best_b = bp if best_b is None else min(best_b, bp)
                best_sep = sep if best_sep is None else min(best_sep, sep)
                best_wl = wl if best_wl is None else min(best_wl, wl)
            if best_b is None: continue
            rows.append((label(e), best_b, best_sep, best_wl))
            print(f"   {label(e):8} bundle {best_b/100:>7.0f}  all-separately {best_sep/100:>7.0f} ({(best_b/best_sep-1)*100:+.1f}%)  wishlist-only {best_wl/100:>7.0f} ({(best_b/best_wl-1)*100:+.1f}%)")
        summary[f"{region}:{bid}"] = {"ratios": rset, "sales": rows, "start": start.isoformat()}
(OUT / "s5.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
