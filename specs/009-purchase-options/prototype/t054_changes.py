"""T054 (SC-005), read-only: the change markers of choose -> same again -> unset -> fallback on real data.

Builds today's decision contracts with and without a choice and feeds them to the production comparison
(decision.changes.compare) in the order the official reports would see them. Writes no record.
"""
from pathlib import Path

from steamsage.config import load_config
from steamsage.decision.changes import compare
from steamsage.decision.contract import batch_to_dict
from steamsage.decision.engine import run_decisions
from steamsage.forecast.models import current_model
from steamsage.store.query import PriceStore
from steamsage.timeutil import now_utc

CYBERPUNK = 1091500
prefs = load_config(Path("steamsage.toml"))[0].preferences
store = PriceStore.open(Path("data/steamsage.db"))
as_of = now_utc()


def contract(choices):
    return batch_to_dict(run_decisions(store, store.wishlist_apps(), as_of, current_model(), prefs, now=as_of,
                                       choices=choices))


default = contract({})
chosen = contract({CYBERPUNK: ("bundle", 32470)})
broken = contract({CYBERPUNK: ("sub", 1)})
steps = [("1 指定（前一份是預設）", default, chosen), ("2 再一次（前一份已指定）", chosen, chosen),
         ("3 取消指定", chosen, default), ("4 指定的版本不能用", chosen, broken)]
for label, baseline, new in steps:
    changes, comparison = compare(new, baseline)
    others = [a for a, c in changes.items() if c and a != CYBERPUNK]
    c = changes[CYBERPUNK]
    print(f"{label}: Cyberpunk {c['version'] if c and c.get('version') else '沒有版本更換'}"
          f"{'; 甜蜜價 ' + str(c['sweet_twd']) if c and c.get('sweet_twd') else ''}; 其他遊戲有變動 {len(others)}")
store.close()
