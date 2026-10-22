"""Offline: time-weighted share where bundle price = round((1-b) x sum of item prices); regular values over time."""
import bisect, json
from datetime import datetime, timezone, timedelta
from pathlib import Path
OUT = Path(__file__).parent / "out"
s1 = json.loads((OUT / "s1.json").read_text(encoding="utf-8"))
s3 = json.loads((OUT / "s3.json").read_text(encoding="utf-8"))
s4 = json.loads((OUT / "s4.json").read_text(encoding="utf-8"))
end = datetime(2026, 9, 27, 3, tzinfo=timezone.utc)
P = datetime.fromisoformat
def series(region, g):
    h = s4["hist"].get(f"{region}:{g}") or []
    return [P(x[0]) for x in h], [x[1] for x in h], [x[2] for x in h]
def at(ser, t):
    i = bisect.bisect_right(ser[0], t) - 1
    return ser[1][i] if i >= 0 else None
for region in ("TW", "US"):
    for bid, b in s1["multi"].items():
        k = 1 - s3[bid]["pct"] / 100
        bs = series(region, s4["bprod"][bid])
        regs = []
        for t, r in zip(bs[0], bs[2]):
            if not regs or regs[-1][1] != r: regs.append((t.date().isoformat(), r))
        items = [series(region, s4["aprod"][str(it["app_id"])]) for it in b["items"]]
        start = max([bs[0][0]] + [s[0][0] for s in items])
        pts = sorted({t for s in [bs] + items for t in s[0] if t >= start} | {start, end})
        ok = bad = 0.0; badlong = []
        for t0, t1 in zip(pts, pts[1:]):
            d = (t1 - t0).total_seconds() / 86400
            bp = at(bs, t0); sm = sum(at(s, t0) for s in items)
            exp = sm * k
            if abs(bp - exp) <= max(100 if region == "TW" else 1, 0.01 * exp): ok += d
            else:
                bad += d
                if d >= 2: badlong.append((t0.date().isoformat(), round(d, 1), bp, round(exp)))
        print(f"{region} bundle/{bid} k={k:.2f} days {ok+bad:.0f}: match {ok/(ok+bad)*100:.1f}%  mismatch {bad:.1f} d; long mismatches {badlong[:5]}")
        print(f"     bundle 'regular' changes: {regs}")
