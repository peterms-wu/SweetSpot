"""T017: production seasonal-record 1.1.0 vs the prototype candidate.py, tuning split, cutoff 2026-09-25.
Errors first (both must be 0), then every scoring unit's probability."""
import sys
import numpy as np
from ulib import load

PAIRS = [("prod_new-split_0.5.pkl", "cand_new_split_a0.5npop.pkl"), ("prod_new_0.pkl", "cand_new_a0npop.pkl")]
for prod_name, cand_name in PAIRS:
    prod, cand = load(prod_name), load(cand_name)
    print(f"{prod_name} vs {cand_name}: model errors {prod['errors']} / {cand['errors']}")
    up, uc = prod["units"], cand["units"]
    same_units = all((up[k] == uc[k]).all() for k in ("t", "app", "k", "j", "off", "fin"))
    d = np.abs(up["p"] - uc["p"])
    print(f"  units {len(up['p']):,}, same units {same_units}, max |diff| {d.max():.3e}, over 1e-12: {(d > 1e-12).sum()}")
    bad = np.nonzero(d > 1e-12)[0][:5]
    for i in bad:
        print("   ", up["app"][i], up["t"][i], up["k"][i], up["j"][i], up["p"][i], uc["p"][i], up["conf"][i])
    if prod["errors"] or cand["errors"] or not same_units or (d > 1e-12).any():
        sys.exit(1)
print("parity OK")
