"""T050 (quickstart §5, FR-016): wording of choices that cannot be used, on the real database (read-only).

Four settings: an option that does not exist, a bundle with other games, a malformed line, an app outside the
wishlist. The config cases are parsed from a temporary copy of steamsage.toml; steamsage.toml itself is untouched.
"""
from pathlib import Path

from steamsage.config import load_config
from steamsage.decision.engine import run_decisions
from steamsage.forecast.models import current_model
from steamsage.store.query import PriceStore
from steamsage.timeutil import now_utc

OUT = Path(__file__).parent / "out"
CYBERPUNK, DAVE, DYING = 1091500, 1868140, 239140
lines = f'{CYBERPUNK} = "sub/1"\n{DAVE} = "bundle/77855"\n{DYING} = "sub/1265945"\n424242 = "sub/1"\n620 = "package/9"\n'
tmp = OUT / "t050.toml"
text = Path("steamsage.toml").read_text(encoding="utf-8")
tmp.write_text(text + ("\n[purchase_options]\n" if "[purchase_options]" not in text else "\n") + lines, encoding="utf-8")
config, warnings = load_config(tmp)
print("config warnings:", warnings)
print("parsed choices:", dict(config.purchase_options))

store = PriceStore.open(Path("data/steamsage.db"))
base = {d.app_id: d for d in run_decisions(store, store.wishlist_apps(), now_utc(), current_model(),
                                           config.preferences).decisions}
batch = run_decisions(store, store.wishlist_apps(), now_utc(), current_model(), config.preferences,
                      choices=config.purchase_options)
print("report warnings:", batch.warnings)
for d in batch.decisions:
    if d.app_id in config.purchase_options:
        print(f"\n{d.name}: group {d.group} (default {base[d.app_id].group}), sweet {d.sweet_cents} "
              f"(default {base[d.app_id].sweet_cents})")
        print("  version.source:", d.version["source"], "fallback:", d.version["fallback"]["code"])
        print("  reason:", d.version["fallback"]["text"])
others = [d.app_id for d in batch.decisions if d.app_id not in config.purchase_options
          and (d.group, d.sweet_cents) != (base[d.app_id].group, base[d.app_id].sweet_cents)]
print("\nother games changed:", others)
store.close()
