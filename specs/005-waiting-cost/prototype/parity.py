"""Feature 005 tasks T015: the production rule 3.0.0 vs the prototype `decide3`, case by case on the TUNING part.

Usage (after proto_cache.py wrote cache_tuning.pkl):
    uv run python specs/005-waiting-cost/prototype/parity.py [path/to/cache_tuning.pkl] [--cost 20]

Compares the group, the target discount, the deadline and the sweet timing. Prints counts and the first mismatches.
"""

import argparse
import pickle
import sys
from datetime import timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / "src"))

from proto_eval import NL, decide3  # noqa: E402

from steamsage.config import Preferences  # noqa: E402
from steamsage.decision.rule import DecisionError, decide  # noqa: E402
from steamsage.forecast.salepoints import SalePoint  # noqa: E402

MONTH = 365 / 12


def sale_points(as_of, pts):
    return tuple(SalePoint(index=i + 1, season=key[0], year=key[1], label=label,
                           start=as_of + timedelta(days=start * MONTH), end=as_of + timedelta(days=end * MONTH),
                           status="estimated", basis=None)
                 for i, (start, end, _, _, label, key) in enumerate(pts))


def rows(flat, n):
    return tuple(tuple(flat[i * NL:(i + 1) * NL]) for i in range(n))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cache", nargs="?", default=str(HERE / "cache_tuning.pkl"))
    ap.add_argument("--cost", type=int, default=20)
    args = ap.parse_args()
    data = pickle.load(open(args.cache, "rb"))
    cases = data["cases"]
    ptsmap = cases.pop("_points")
    prefs = Preferences(wait_cost_twd=args.cost)
    same = differ = both_error = 0
    examples = []
    for (app, as_of), case in cases.items():
        pts, nh = ptsmap[as_of]
        proto = decide3(case, ptsmap[as_of], nh, args.cost * 100, "regular")
        case.pop("_ex", None)
        points = sale_points(as_of, pts)
        try:
            r = decide(probabilities=rows(case["curve"], case["npts"]), points=points, as_of=as_of,
                       confidence=case["conf"], evidence_max_cut=None, regular_cents=case["regular"],
                       current_price_cents=case["price"], regular_mismatch=False,
                       no_history=rows(nh, case["npts"]) if nh else None, preferences=prefs, rule="3.0.0")
        except DecisionError:
            r = None
        if proto is None or r is None:
            both_error += proto is None and r is None
            if (proto is None) != (r is None):
                differ += 1
                examples.append((app, as_of, proto, r))
            continue
        a = (proto.group, None if proto.group == "now" else (proto.sweet_pct, proto.K, proto.T))
        b = (r.group, None if r.group == "now" else (r.sweet_pct, r.deadline_index, r.sweet_index))
        if a == b:
            same += 1
        else:
            differ += 1
            if len(examples) < 10:
                examples.append((app, as_of, a, b))
    total = same + differ
    print(f"c = {args.cost}: {total} decisions, same {same} ({same / total:.3%}), different {differ}, "
          f"both no decision {both_error}")
    for e in examples:
        print("  ", e)


if __name__ == "__main__":
    main()
