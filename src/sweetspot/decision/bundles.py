"""Bundles holding several wishlist games (feature 010; docs/model/model-definition.md「組合包建議」).

The rule `bundle-advice` 1.0.0 never changes a game's decision: it reads the finished decisions and forecasts, the
purchase-option records and Steam's bundle discount, and writes the batch's `bundles` block
(specs/010-wishlist-bundles/contracts/outputs-bundles.md). Presentation layers only show it (constitution VII).
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sweetspot.decision.contract import Decision, twd
from sweetspot.decision.rule import price_cents
from sweetspot.forecast.contract import LEVELS, Forecast, iso
from sweetspot.forecast.salepoints import SalePoint
from sweetspot.store.query import OptionRecord
from sweetspot.timeutil import add_months

RULE = ("bundle-advice", "1.0.0")
JOINT_THRESHOLD = 0.5          # rule constant: same as the sweet point and P_min
CHECK_MIN_CENTS = 200          # rule constant: formula check tolerance max(NT$2, 1%) (research R3)
CHECK_SHARE = 0.01
HORIZON_MONTHS = 12            # the next seasonal sale must end within the rule's 12 months (sweet-price 2.x)
GAME_TYPE = 0
OWNED_NOTE = "價格以全部內容都未擁有計算；已擁有其中的內容時，Steam 的價格會更低"

# Joint-reach hit rates quoted by the report: random pairs, the rule's choice (cheapest combination with joint >= 50%),
# tuning part, cutoff 2026-09-25 (research R0.2). Must equal the model definition (tests/unit/decision/test_bundle_doc).
BUNDLE_BACKTESTS: Mapping[str, Any] = {
    "source": "docs/model/model-definition.md",
    "dataset": "858b3147",
    "cutoff": "2026-09-25",
    "split": "tuning",
    "bins": (
        {"bin": [0.5, 0.6], "mean_forecast": 0.543, "observed": 0.685, "units": 16338},
        {"bin": [0.6, 0.7], "mean_forecast": 0.655, "observed": 0.769, "units": 13423},
        {"bin": [0.7, 0.8], "mean_forecast": 0.750, "observed": 0.830, "units": 13902},
        {"bin": [0.8, 0.9], "mean_forecast": 0.851, "observed": 0.856, "units": 15777},
        {"bin": [0.9, 1.0], "mean_forecast": 0.939, "observed": 0.905, "units": 9259},
    ),
    "overall": {"mean_forecast": 0.731, "observed": 0.800, "units": 68699},
}


def hit_rate(probability: float) -> dict[str, Any] | None:
    """The backtest row of the 0.1 bin holding `probability` (the last bin includes 1.0); None below the threshold."""
    if probability < JOINT_THRESHOLD:
        return None
    for row in BUNDLE_BACKTESTS["bins"]:
        low, high = row["bin"]
        if low <= probability < high or (high == 1.0 and probability <= 1.0):
            return {"bin": list(row["bin"]), "observed": row["observed"], "units": row["units"],
                    "source": "model-definition"}
    return None


# --- pure pieces (research R3, R4) -------------------------------------------------------------------------------

def money(cents: int | None) -> str:
    return "未知" if cents is None else f"NT${twd(cents):,}"


def bundle_price(sum_cents: int, discount_pct: int) -> int:
    """(1 - b) x sum, in cents, 0.5 cent rounds up."""
    return (sum_cents * (100 - discount_pct) + 50) // 100


def check_formula(price: int, discount: int | None, prices: Sequence[int | None]) -> dict[str, Any]:
    """research R3: |Steam - (1 - b) x sum| <= max(NT$2, 1%). Unknown when a price or the discount is unknown."""
    if discount is None or any(p is None for p in prices):
        missing = "組合包折扣" if discount is None else "有內容的現價"
        return {"status": "unknown", "expected_cents": None, "expected_twd": None,
                "text": f"{missing}未知，無法確認組合包價格"}
    expected = bundle_price(sum(prices), discount)
    tolerance = max(CHECK_MIN_CENTS, round(CHECK_SHARE * expected))
    if abs(price - expected) <= tolerance:
        return {"status": "ok", "expected_cents": expected, "expected_twd": twd(expected), "text": None}
    return {"status": "mismatch", "expected_cents": expected, "expected_twd": twd(expected),
            "text": f"組合包現價 {money(price)}，依組合包折扣 −{discount}% 與各內容現價推算為 {money(expected)}："
                    "組合包折扣或內容可能改變"}


@dataclass(frozen=True)
class Combination:
    levels: tuple[int, ...]         # one discount level per game; 0 = not discounted
    probabilities: tuple[float, ...]
    joint: float
    cents: int                      # sum of the games' prices at those levels, before the bundle discount


def cheapest_combination(items: Sequence[tuple[int, Sequence[float]]],
                         threshold: float = JOINT_THRESHOLD) -> Combination | None:
    """research R4 rule 3: among level combinations whose joint next-sale probability is >= threshold, the one with
    the lowest total price; ties go to the higher joint probability. `items` are (regular cents, next-sale
    probabilities per LEVELS). Deeper levels never have a higher probability, so a branch below the threshold stops."""
    options = [[(0, 1.0, regular)] + [(d, p, price_cents(regular, d)) for d, p in zip(LEVELS, row)]
               for regular, row in items]
    best: list[Combination | None] = [None]

    def walk(i: int, levels: tuple, probs: tuple, joint: float, cents: int) -> None:
        if i == len(options):
            b = best[0]
            if b is None or cents < b.cents or (cents == b.cents and joint > b.joint):
                best[0] = Combination(levels, probs, joint, cents)
            return
        for d, p, c in options[i]:
            j = joint * p
            if j < threshold:
                break
            walk(i + 1, levels + (d,), probs + (p,), j, cents + c)

    walk(0, (), (), 1.0, 0)
    return best[0]


def choose(price: int, plan: int, latest_index: int, estimate: int) -> str:
    """research R4 rule 4 (clarify Q1, Q2): now, the next sale (never later than the latest sweet point, no
    tolerance), else separately. The joint probability is >= the threshold by construction of the estimate."""
    if price <= plan:
        return "now"
    if latest_index >= 1 and estimate <= plan:
        return "next-sale"
    return "separately"


def _point(p: SalePoint | None) -> dict[str, Any] | None:
    return None if p is None else {"index": p.index, "label": p.label, "start": iso(p.start), "end": iso(p.end),
                                   "status": p.status}


def _count(n: int) -> str:
    return "兩款" if n == 2 else f"{n} 款"


# --- building the block -----------------------------------------------------------------------------------------

@dataclass(frozen=True)
class BundleBlock:
    bundles: list[dict[str, Any]]
    per_app: dict[int, list[int]]            # every decision's app -> ids of the bundles it is in
    contents_unknown: int = 0
    notes: tuple[str, ...] = field(default=())


def _role(content: Mapping[str, Any], wishlist: Collection[int], inside: Collection[int]) -> str:
    app = content["app_id"]
    if app in wishlist:
        return "wishlist"
    if content.get("parent_app_id") in inside:
        return "wishlist-dlc"
    return "other-game" if content.get("type") == GAME_TYPE else "other"


def build_bundles(records: Mapping[int, Sequence[OptionRecord]], decisions: Sequence[Decision],
                  forecasts: Mapping[int, Forecast], *, as_of: datetime, names: Mapping[int, str | None],
                  specified: Collection[int]) -> BundleBlock:
    """data-model §2: every bundle holding >= 2 wishlist games (the decisions' apps), pure first then by id."""
    by_app = {d.app_id: d for d in decisions}
    seen: dict[int, OptionRecord] = {}
    unknown: set[int] = set()
    for app in sorted(records):
        for r in records[app]:
            if r.kind != "bundle":
                continue
            if r.contents is None:
                unknown.add(r.option_id)
            elif r.option_id not in seen:
                seen[r.option_id] = r
    items = []
    for bundle_id, r in seen.items():
        inside = [c["app_id"] for c in r.contents if c["app_id"] in by_app]
        if len(inside) < 2:
            continue
        item = _describe(r, inside, by_app, names, specified)
        if item["grade"] == "pure":
            try:
                item["advice"] = _advise(item, inside, by_app, forecasts, as_of, specified)
            except Exception as exc:  # noqa: BLE001 - one bundle's failure never hides the others (constitution III)
                item["advice"] = _none("error", f"這個組合包計算出錯：{type(exc).__name__}: {exc}")
        items.append(item)
    items.sort(key=lambda b: (b["grade"] != "pure", b["id"]))
    per_app = {d.app_id: [b["id"] for b in items if d.app_id in b["_wishlist"]] for d in decisions}
    for b in items:
        del b["_wishlist"]
    return BundleBlock(items, per_app, len(unknown - set(seen)))


def _describe(r: OptionRecord, inside: list[int], by_app: Mapping[int, Decision],
              names: Mapping[int, str | None], specified: Collection[int]) -> dict[str, Any]:
    contents = []
    for c in r.contents:
        role = _role(c, by_app, inside)
        app = c["app_id"]
        if role == "wishlist":
            d = by_app[app]
            price = d.current.price_cents if d.current is not None else None
            name = d.name
        else:
            price, name = c.get("final_cents"), c.get("name") or names.get(app)    # recorded (TW store) first
        contents.append({"app_id": app, "name": name, "role": role, "price_cents": price, "price_twd": twd(price),
                         "specified": role == "wishlist" and app in specified})
    prices = [c["price_cents"] for c in contents]
    wishlist_prices = [c["price_cents"] for c in contents if c["role"] == "wishlist"]
    pure = all(c["role"] in ("wishlist", "wishlist-dlc") for c in contents)
    separate = None if any(p is None for p in prices) else sum(prices)
    wishlist = None if any(p is None for p in wishlist_prices) else sum(wishlist_prices)
    extra = [c for c in contents if c["role"] != "wishlist"]
    item: dict[str, Any] = {
        "id": r.option_id, "name": r.name, "checked_at": iso(r.checked_at), "grade": "pure" if pure else "mixed",
        "discount_pct": r.bundle_discount_pct, "price_cents": r.final_cents, "price_twd": twd(r.final_cents),
        "contents": contents, "check": check_formula(r.final_cents, r.bundle_discount_pct, prices),
        "separate_cents": separate, "separate_twd": twd(separate),
        "wishlist_cents": wishlist, "wishlist_twd": twd(wishlist),
        "extra_cents": None, "extra_twd": None, "extra_games": None, "extra_dlc": None, "extra_game_names": None,
        "plan": None, "advice": None, "owned_note": OWNED_NOTE, "_wishlist": set(inside),
    }
    if not pure:
        games = [c for c in extra if c["role"] == "other-game"]
        extra_cents = None if wishlist is None else r.final_cents - wishlist
        item.update({"extra_cents": extra_cents, "extra_twd": twd(extra_cents), "extra_games": len(games),
                     "extra_dlc": len(extra) - len(games), "extra_game_names": [c["name"] for c in games]})
    return item


def _none(code: str, text: str) -> dict[str, Any]:
    return {"status": "none", "reason_code": code, "reason_text": text, "kind": None, "sale": None, "levels": [],
            "estimate_cents": None, "estimate_twd": None, "joint_probability": None, "saving_cents": None,
            "saving_twd": None, "timing": None, "hit_rate": None, "confidence": None, "text": None}


def _advise(item: dict[str, Any], inside: list[int], by_app: Mapping[int, Decision],
            forecasts: Mapping[int, Forecast], as_of: datetime, specified: Collection[int]) -> dict[str, Any]:
    games = [by_app[a] for a in inside]
    for d in games:
        if d.app_id in specified:
            return _none("specified", f"{d.name} 指定了其他版本；組合包含的是 Steam 預設的版本，所以不給組合包建議")
    for d in games:
        f = forecasts.get(d.app_id)
        if d.group == "na" or d.sweet_cents is None or f is None or f.status != "ok" or not f.probabilities:
            why = d.status_reason or (f.status_reason if f is not None else None) or "沒有預測"
            return _none("no-forecast", f"{d.name} 沒有可用的預測（{why}），只給現價比較")
    dlc = [c for c in item["contents"] if c["role"] != "wishlist"]
    if dlc:
        label = dlc[0]["name"] or f"App {dlc[0]['app_id']}"
        return _none("no-forecast", f"內容 {label} 不在願望清單中，沒有預測，只給現價比較")
    for d in games:
        if d.current is None or d.current.price_cents is None or d.current.stale:
            return _none("stale-price", f"{d.name} 的現價超過 24 小時沒有確認，只給現價比較")
    check = item["check"]
    if check["status"] == "unknown":
        return _none("check-unknown", f"{check['text']}，今天不給組合包建議")
    if check["status"] == "mismatch":
        return _none("check-mismatch", f"{check['text']}，今天不給組合包建議")
    sale = forecasts[games[0].app_id].points[0]
    if sale.end > add_months(as_of, HORIZON_MONTHS):
        return _none("no-sale", "12 個月內沒有可推算的季節特賣，只給現價比較")

    plan = sum(d.current.price_cents if d.group == "now" else d.sweet_cents for d in games)
    latest = max((d.sweet_point.index if d.group != "now" else 0) for d in games)
    latest_point = next((d.sweet_point for d in games if d.group != "now" and d.sweet_point.index == latest), None)
    item["plan"] = {"cents": plan, "twd": twd(plan), "latest_point": _point(latest_point)}

    combo = cheapest_combination([(d.regular_cents, forecasts[d.app_id].probabilities[0]) for d in games])
    discount = item["discount_pct"]
    estimate = bundle_price(combo.cents, discount)
    price = item["price_cents"]
    kind = choose(price, plan, latest, estimate)
    low = any(forecasts[d.app_id].confidence == "low" or d.group == "low" for d in games)
    rate = hit_rate(combo.joint) if kind != "now" else None
    saving = plan - price if kind == "now" else plan - estimate if kind == "next-sale" else None
    timing = "now" if kind == "now" else None
    if kind == "next-sale":
        timing = "earlier" if latest > sale.index else "same"
    n = _count(len(games))
    if kind == "now":
        text = f"{n}都要買的話，現在買組合包：{money(price)}，比各自在甜蜜時點買（{money(plan)}）便宜 {money(saving)}"
    elif kind == "next-sale":
        text = (f"{n}都要買的話，{sale.label}買組合包：約 {money(estimate)}（{n}同時到價 {combo.joint:.0%}；"
                f"過去這類說法 {rate['observed']:.0%} 成真），比各自在甜蜜時點買便宜 {money(saving)}")
        if timing == "earlier":
            text += f"，而且早 {latest - sale.index} 場"
    else:
        text = f"各自在甜蜜時點分開買較划算；同一場特賣{n}都買時，組合包仍便宜 {discount}%"
    levels = [{"app_id": d.app_id, "pct": lv, "cents": price_cents(d.regular_cents, lv),
               "twd": twd(price_cents(d.regular_cents, lv)), "probability": round(p, 6)}
              for d, lv, p in zip(games, combo.levels, combo.probabilities)]
    return {"status": "ok", "reason_code": None, "reason_text": None, "kind": kind, "sale": _point(sale),
            "levels": levels, "estimate_cents": estimate, "estimate_twd": twd(estimate),
            "joint_probability": round(combo.joint, 6), "saving_cents": saving, "saving_twd": twd(saving),
            "timing": timing, "hit_rate": rate, "confidence": "low" if low else "normal", "text": text}
