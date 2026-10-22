"""Why do low-group decisions change group under the new-game base? (p11: 971 -> 859)"""
import sys
from collections import Counter
from pathlib import Path
from ulib import load
sys.path.insert(0, r"〈專案資料夾〉\src")
from steamsage.config import Preferences
from steamsage.decision.rule import decide

raw, new = load(), load("cand_new_split_a0npop.pkl")
def dec(data, key):
    app, as_of = key
    c, info = data["cases"][key], data["per_as_of"][as_of]
    return decide(probabilities=c["curve"], points=info["points"], as_of=as_of, confidence=c["conf"],
                  evidence_max_cut=c["max_cut"], regular_cents=c["regular"],
                  current_price_cents=c["regular"] * (100 - c["cut"]) // 100, regular_mismatch=False,
                  no_history=info["no_history"], preferences=Preferences(), rule="2.1.0")
moves = Counter()
ex = []
for key, c in raw["cases"].items():
    a, b = dec(raw, key), dec(new, key)
    if a.group != b.group:
        moves[(a.group, b.group, c["conf"], a.basis, a.p_min_pct, b.p_min_pct, c["cut"] > 0)] += 1
        if len(ex) < 5:
            ex.append((key[0], f"{key[1]:%Y-%m}", c["conf"], c["cut"], a.group, a.sweet_pct, b.group, b.sweet_pct, b.tags))
for k, v in moves.most_common(15):
    print(v, "from/to/conf/basis/pmin_old/pmin_new/discounted:", k)
for e in ex:
    print(e)
