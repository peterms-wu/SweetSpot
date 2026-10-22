"""Side-by-side rule backtests and the wishlist difference (feature 004 research R8; spec FR-015-FR-021).

Two `steamsage.rule-backtest/1` results on the same dataset, cutoff and preferences: every figure the user weighs
(hit rates, timing, buy-now follow-up, following the advice, hindsight) side by side with the difference.
"""

import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from sweetspot.config import Preferences
from sweetspot.decision.rule import RULES, decide, option_value
from sweetspot.forecast.salepoints import SalePoint
from sweetspot.timeutil import add_months, parse_iso

GROUPS = ("now", "soon", "wait", "low", "na")
RESAMPLES = 2000                 # 002 comparison: game-paired resampling, seed from the dataset id
MONTH_DAYS = 365 / 12
DEFAULT_WAIT_COST = Preferences().wait_cost_twd      # the hard gate's c: the program default, not the config (FR-015)
RULE_VALIDATION_TITLE = "規則驗證組比較（sweet-price {rule}）第 {n} 次"
PART = {"all": "全部資料", "tuning": "調參組", "validation": "驗證組"}


class CompareRuleError(ValueError):
    pass


def _label(r: Mapping[str, Any]) -> str:
    m = r["model"]
    params = ", ".join(f"{k}={v}" for k, v in m["params"].items())
    return f"{m['name']} {m['version']} {{{params}}} ＋ {r['rule']['name']} {r['rule']['version']}"


def _rates(r: Mapping[str, Any]) -> dict[str, dict]:
    hit = r["hit_rate"]
    return {**{g["group"]: g for g in hit["by_group"]}, **{g["group"]: g for g in hit.get("by_confidence", [])
                                                            if g["group"] == "normal"}}


# (key, title, getter, format)
def _rows_spec():
    fa = lambda r: r.get("follow_advice", {}).get("overall", {})          # noqa: E731
    rate = lambda g: (lambda r: _rates(r).get(g, {}).get("rate"))          # noqa: E731
    return [
        ("decisions.now", "判為現在買", lambda r: r["decisions"]["now"], "n"),
        ("decisions.soon", "即將到價", lambda r: r["decisions"]["soon"], "n"),
        ("decisions.wait", "繼續等", lambda r: r["decisions"]["wait"], "n"),
        ("decisions.low", "低信心", lambda r: r["decisions"]["low"], "n"),
        ("decisions.beyond_window", "甜蜜時點超過 12 個月（無法評分）", lambda r: r["decisions"]["beyond_window"], "n"),
        ("hit_rate.soon", "到價率：即將到價", rate("soon"), "%"),
        ("hit_rate.wait", "到價率：繼續等", rate("wait"), "%"),
        ("hit_rate.low", "到價率：低信心", rate("low"), "%"),
        ("hit_rate.normal", "到價率：一般信心合計", rate("normal"), "%"),
        ("timing_error.mean_abs", "時間誤差（平均絕對值，場）", lambda r: r["timing_error"]["mean_abs"], "f2"),
        ("sweet_timing.next", "甜蜜時點：下一場", lambda r: r.get("sweet_timing", {}).get("next"), "n"),
        ("sweet_timing.within_1y", "甜蜜時點：1 年內", lambda r: r.get("sweet_timing", {}).get("within_1y"), "n"),
        ("sweet_timing.beyond_1y", "甜蜜時點：1 年以上", lambda r: r.get("sweet_timing", {}).get("beyond_1y"), "n"),
        ("now_followup.rate", "現在買之後 12 個月內又更便宜", lambda r: r["now_followup"]["rate"], "%"),
        ("now_followup.extra_median", "　多省的中位數（NT$）",
         lambda r: r["now_followup"]["extra_saving_twd"]["median"], "n"),
        ("follow_advice.evaluated", "照建議買：評估數", lambda r: fa(r).get("evaluated"), "n"),
        ("follow_advice.saving_mean", "照建議買：比立刻買平均多省（NT$）",
         lambda r: fa(r).get("saving_twd", {}).get("mean"), "f1"),
        ("follow_advice.saving_median", "　多省的中位數（NT$）", lambda r: fa(r).get("saving_twd", {}).get("median"), "n"),
        ("follow_advice.saving_p90", "　多省的 90 百分位（NT$）", lambda r: fa(r).get("saving_twd", {}).get("p90"), "n"),
        ("follow_advice.wait_mean", "照建議買：平均多等（天）", lambda r: fa(r).get("wait_days", {}).get("mean"), "f1"),
        ("follow_advice.wait_median", "　多等的中位數（天）", lambda r: fa(r).get("wait_days", {}).get("median"), "n"),
        ("hindsight.saving_mean", "參照：事後最低價比立刻買平均少（NT$）",
         lambda r: r.get("hindsight", {}).get("saving_twd", {}).get("mean"), "f1"),
    ]


def compare_rule_results(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, Any]:
    """`a` is the current combination, `b` the candidate."""
    if a["dataset"]["dataset_id"] != b["dataset"]["dataset_id"]:
        raise CompareRuleError(f"資料集不同：{a['dataset']['dataset_id'][:12]}… ≠ {b['dataset']['dataset_id'][:12]}…")
    if a["dataset"]["cutoff"] != b["dataset"]["cutoff"]:
        raise CompareRuleError(f"資料截止時間不同：{a['dataset']['cutoff']} ≠ {b['dataset']['cutoff']}")
    keys = shared_preferences_differ(a["preferences"], b["preferences"])
    if keys:
        raise CompareRuleError(f"使用者偏好不同：{', '.join(keys)}")
    rows = []
    for key, title, get, fmt in _rows_spec():
        va, vb = get(a), get(b)
        diff = None if va is None or vb is None else vb - va
        rows.append({"key": key, "title": title, "a": va, "b": vb, "diff": diff, "format": fmt})
    return {"a": {"label": _label(a)}, "b": {"label": _label(b)}, "rows": rows,
            "dataset": {"id": a["dataset"]["dataset_id"], "cutoff": a["dataset"]["cutoff"],
                        "split": (a["dataset"].get("split") or {}).get("name", "all")}}


def shared_preferences_differ(a: Mapping[str, Any], b: Mapping[str, Any]) -> list[str]:
    """Preferences both results use and that differ; a rule's own ones (c, the tolerance) never block (005 R7)."""
    return sorted(k for k in set(a) & set(b) if a[k] != b[k])


# --- feature 005: the net benefit side by side (research R7; spec FR-012, FR-013, FR-015) ----------------------

def _cases(result: Mapping[str, Any], mode: str) -> dict[tuple[int, str], tuple[int, int]]:
    return {(c[0], c[1]): (c[3], c[4]) for c in result.get("cases", []) if c[2] == mode}


def _net(saving_cents: int, days: int, cost: int) -> float:
    return saving_cents / 100 - cost * days / MONTH_DAYS


def _interval(per_game: Sequence[tuple[float, int]], seed: int) -> list[float]:
    """95% interval of the per-decision mean difference, resampling games (002 method)."""
    rng = random.Random(seed)
    means = []
    for _ in range(RESAMPLES):
        sample = rng.choices(per_game, k=len(per_game))
        means.append(sum(s for s, _ in sample) / sum(n for _, n in sample))
    means.sort()
    return [means[round(0.025 * (RESAMPLES - 1))], means[round(0.975 * (RESAMPLES - 1))]]


def net_comparison(a: Mapping[str, Any], b: Mapping[str, Any], *, default_cost: int = DEFAULT_WAIT_COST,
                   cost: int | None = None) -> dict[str, Any] | None:
    """Both results' net benefit at the candidate's waiting cost, on the decisions both could evaluate; None when a
    result has no `cases` (made before feature 005) or there is no waiting cost to evaluate at."""
    if "cases" not in a or "cases" not in b:
        return None
    if cost is None:       # feature 008: two tolerance results (same rule, another model) are valued at a given cost
        cost = b["preferences"].get("wait_cost_twd", a["preferences"].get("wait_cost_twd"))
    if cost is None:
        return None
    seed = int(a["dataset"]["dataset_id"][:8], 16)
    modes = {}
    for mode in ("monthly", "fixed"):
        ca, cb = _cases(a, mode), _cases(b, mode)
        keys = sorted(ca.keys() & cb.keys())
        if not keys:
            modes[mode] = {"n": 0, "a": None, "b": None, "diff": None, "ci": None}
            continue
        per_game: dict[int, list] = defaultdict(lambda: [0.0, 0])
        side = {"a": [0.0, 0.0, 0.0], "b": [0.0, 0.0, 0.0]}
        for key in keys:
            (sa, da), (sb, db) = ca[key], cb[key]
            na, nb = _net(sa, da, cost), _net(sb, db, cost)
            per_game[key[0]][0] += nb - na
            per_game[key[0]][1] += 1
            for name, (sv, dv, nv) in (("a", (sa, da, na)), ("b", (sb, db, nb))):
                side[name][0] += sv / 100
                side[name][1] += dv
                side[name][2] += nv
        n = len(keys)
        stats = {name: {"saving": v[0] / n, "wait_days": v[1] / n, "net": v[2] / n} for name, v in side.items()}
        modes[mode] = {"n": n, **stats, "diff": stats["b"]["net"] - stats["a"]["net"],
                       "ci": _interval([tuple(v) for _, v in sorted(per_game.items())], seed)}
    split = lambda r: (r["dataset"].get("split") or {}).get("name", "all")  # noqa: E731
    verdict = None
    rule_changed = a.get("rule", {}).get("version") != b.get("rule", {}).get("version")
    if rule_changed and split(a) == split(b) == "validation" and cost == default_cost and modes["monthly"]["n"]:
        verdict = "pass" if modes["monthly"]["ci"][0] > 0 else "fail"
    return {"cost_twd": cost, "label": _label(b), "modes": modes, "verdict": verdict}


def net_by_cost(results: Sequence[tuple[str, Mapping[str, Any]]]) -> list[dict[str, Any]]:
    """Mean net benefit (monthly re-evaluation) of every result at every evaluation cost (spec FR-012)."""
    rows = []
    for label, r in results:
        block = (r.get("follow_advice_monthly") or {}).get("overall") or {}
        rows.append({"result": label, "costs": {n["cost_twd"]: n["mean"] for n in block.get("net_twd", [])}})
    return rows


def check_rule_attempt(path: Path, *, split: str, rule: str, attempt: int | None, change: str | None,
                       base_rule: str | None = None) -> None:
    """Validation-part rule comparisons: at most 3 recorded attempts per candidate rule (spec FR-014). The same rule
    with another model is a model side-by-side (004 research R8), not a rule attempt (feature 008 research R7)."""
    if split != "validation" or (base_rule is not None and base_rule == rule):
        return
    if attempt is None:
        raise CompareRuleError("驗證組的比較紀錄必須加上 --attempt（第幾次，1–3）")
    if not 1 <= attempt <= 3:
        raise CompareRuleError("驗證組最多比較 3 次：--attempt 必須是 1–3")
    if attempt >= 2 and not (change or "").strip():
        raise CompareRuleError("第 2、3 次比較必須用 --change 說明這次改了什麼、為什麼改")
    title = RULE_VALIDATION_TITLE.format(rule=rule, n=attempt)
    path = Path(path)
    if path.exists() and any(line.startswith("## ") and line.endswith(title)
                             for line in path.read_text(encoding="utf-8").splitlines()):
        raise CompareRuleError(f"比較文件中已有「{title}」的紀錄")


# --- wishlist: expected net of both sides and the longer-horizon count (research R7; FR-016, FR-017) -----------

def _points(game: Mapping[str, Any]) -> tuple[SalePoint, ...]:
    return tuple(SalePoint(p["index"], p["season"], p["year"], p["label"], parse_iso(p["start"]), parse_iso(p["end"]),
                           p["status"], p.get("basis")) for p in game["curve"]["points"])


def _curve(d: Mapping[str, Any], game: Mapping[str, Any], batch: Mapping[str, Any]):
    if d.get("basis") == "no-history" and batch["forecast"].get("no_history"):
        return batch["forecast"]["no_history"]["probabilities"]
    return game["curve"]["probabilities"]


def decision_net(d: Mapping[str, Any], batch: Mapping[str, Any], cost: int | None) -> int | None:
    """NT$ net benefit of a decision at waiting cost c: 3.0.0 carries it; a 2.0.0 recommendation is valued as the
    option (its sweet price, at most until its sweet sale) with the 3.0.0 formula."""
    if d["status"] != "ok" or cost is None:
        return None
    if d.get("expected"):
        return d["expected"]["net_twd"]
    if d["group"] == "now":
        return 0
    game = next(g for g in batch["forecast"]["games"] if g["app_id"] == d["app_id"])
    base = (d.get("current") or {}).get("price_cents") or d["regular_cents"]
    o = option_value(_curve(d, game, batch), _points(game), parse_iso(batch["as_of"]),
                     regular_cents=d["regular_cents"], base_cents=base, pct=d["sweet_pct"],
                     deadline_index=d["sweet_point"]["index"], wait_cost_twd=cost)
    return (o.net_cents + 50) // 100


def longer_count(batch: Mapping[str, Any], cost: int | None, months: int) -> int | None:
    """Wishlist games whose 3.0.0 option would wait past 12 months if the range were `months` (spec FR-017)."""
    if cost is None or RULES.get(batch["rule"]["version"], {}).get("kind") != "wait-cost":
        return None
    as_of = parse_iso(batch["as_of"])
    twelve = add_months(as_of, 12)
    no_history = (batch["forecast"].get("no_history") or {}).get("probabilities")
    games = {g["app_id"]: g for g in batch["forecast"]["games"]}
    count = 0
    for d in batch["decisions"]:
        if d["status"] != "ok":
            continue
        game, cur = games[d["app_id"]], d.get("current") or {}
        points = _points(game)
        try:
            r = decide(probabilities=game["curve"]["probabilities"], points=points, as_of=as_of,
                       confidence=game["confidence"], evidence_max_cut=None, regular_cents=d["regular_cents"],
                       current_price_cents=cur.get("price_cents"), regular_mismatch=bool(cur.get("regular_mismatch")),
                       no_history=no_history, preferences=Preferences(wait_cost_twd=cost), rule="3.0.0",
                       months=months)
        except ValueError:
            continue
        if r.deadline_index and points[r.deadline_index - 1].end > twelve:
            count += 1
    return count


def _summary(d: Mapping[str, Any]) -> dict[str, Any]:
    return {"group": d["group"], "sweet_twd": d.get("sweet_twd"), "sweet_pct": d.get("sweet_pct"),
            "point": (d.get("sweet_point") or {}).get("label")}


def wishlist_diff(batch_a: Mapping[str, Any], batch_b: Mapping[str, Any], cost: int | None = None) -> dict[str, Any]:
    """Two `steamsage.decision/1` or `/2` dicts for the same wishlist: counts, changed games, the mean sweet-price move;
    with a waiting cost also each game's expected net benefit on both sides (005 research R7)."""
    a = {d["app_id"]: d for d in batch_a["decisions"]}
    b = {d["app_id"]: d for d in batch_b["decisions"]}
    counts = {side: {g: sum(d["group"] == g for d in batch["decisions"]) for g in GROUPS}
              for side, batch in (("a", batch_a), ("b", batch_b))}
    changed, one_side, moves, nets = [], [], [], []
    for app in sorted(set(a) & set(b)):
        da, db = a[app], b[app]
        ok_a, ok_b = da["status"] == "ok", db["status"] == "ok"
        if ok_a and ok_b:
            moves.append(db["sweet_twd"] - da["sweet_twd"])
            if cost is not None:
                nets.append((decision_net(da, batch_a, cost), decision_net(db, batch_b, cost)))
            if _summary(da) != _summary(db):
                before, after = _summary(da), _summary(db)
                if cost is not None:
                    before["net_twd"], after["net_twd"] = nets[-1]
                changed.append({"app_id": app, "name": da["name"], "from": before, "to": after})
        elif ok_a != ok_b:
            one_side.append({"app_id": app, "name": da["name"], "a": da["status"], "b": db["status"]})
    out = {"counts": counts, "changed": changed, "one_side": one_side,
           "mean_sweet_change_twd": sum(moves) / len(moves) if moves else None}
    if cost is not None:
        out["cost_twd"] = cost
        out["mean_net_twd"] = {"a": sum(x for x, _ in nets) / len(nets) if nets else None,
                               "b": sum(y for _, y in nets) / len(nets) if nets else None}
        for months in (24, 60):
            out[f"longer_{months}"] = longer_count(batch_b, cost, months)
    return out


def _fmt(value, fmt: str, signed: bool = False) -> str:
    if value is None:
        return "—"
    sign = "+" if signed else ""
    if fmt == "%":
        return f"{value * 100:{sign}.1f}%" if not signed else f"{value * 100:+.1f} pp"
    if fmt == "f2":
        return f"{value:{sign}.2f}"
    if fmt == "f1":
        return f"{value:{sign}.1f}"
    return f"{value:{sign},}" if isinstance(value, int) else f"{value:{sign}.1f}"


def format_rule_record(*, date: str, comparison: Mapping[str, Any], files: tuple[str, str],
                       wishlist: Mapping[str, Any] | None, decision: str | None = None) -> str:
    ds = comparison["dataset"]
    lines = [f"## {date} · 規則回測並列：{comparison['a']['label']} vs {comparison['b']['label']}", "",
             f"- 資料集：台灣區 `{ds['id'][:8]}…`（{PART.get(ds['split'], ds['split'])}，截止 {ds['cutoff'][:10]}）",
             f"- 結果檔：`{files[0]}`、`{files[1]}`", "",
             "| 指標 | 現行 | 候選 | 差距 |", "|---|---|---|---|"]
    for r in comparison["rows"]:
        lines.append(f"| {r['title']} | {_fmt(r['a'], r['format'])} | {_fmt(r['b'], r['format'])} | "
                     f"{_fmt(r['diff'], r['format'], signed=True)} |")
    lines.append("")
    lines.append("照建議買：判為現在買以現價買；其他分組等到價格第一次進入甜蜜價就買，12 個月內沒到價就以 12 個月時的價格買"
                 "（research R6）。")
    if wishlist:
        c = wishlist["counts"]
        names = {"now": "現在買", "soon": "即將到價", "wait": "繼續等", "low": "低信心", "na": "無法預測"}
        lines += ["", "**願望清單（現在）**：" + "、".join(f"{names[g]} {c['a'][g]} → {c['b'][g]}" for g in GROUPS)]
        if wishlist["mean_sweet_change_twd"] is not None:
            lines.append(f"甜蜜價平均變化 NT${wishlist['mean_sweet_change_twd']:+.0f}。")
        if wishlist["changed"]:
            lines += ["", "| 遊戲 | 現行 | 候選 |", "|---|---|---|"]
            for ch in wishlist["changed"]:
                f, t = ch["from"], ch["to"]
                lines.append(f"| {ch['name']} | {names[f['group']]} NT${f['sweet_twd']}（-{f['sweet_pct']}%）@ {f['point']} | "
                             f"{names[t['group']]} NT${t['sweet_twd']}（-{t['sweet_pct']}%）@ {t['point']} |")
        for o in wishlist["one_side"]:
            lines.append(f"- {o['name']}：現行 {o['a']}、候選 {o['b']}")
    if decision:
        lines += ["", f"**使用者的決定**：{decision}"]
    lines.append("")
    return "\n".join(lines)


NAMES = {"now": "現在買", "soon": "即將到價", "wait": "繼續等", "low": "低信心", "na": "無法預測"}
MODES = {"monthly": "每月重新評估", "fixed": "固定決策"}


def _money(v) -> str:
    return "—" if v is None else f"{v:,.1f}"


def format_rule_records(*, date: str, comparisons: Sequence[Mapping[str, Any]], nets: Sequence[Mapping | None],
                        by_cost: Sequence[Mapping[str, Any]], files: Sequence[str],
                        wishlists: Sequence[Mapping[str, Any] | None], decision: str | None = None,
                        attempt: int | None = None, change: str | None = None, rule: str | None = None) -> str:
    """One record for a base and several candidates with the net benefit (005 research R7; spec FR-018)."""
    ds = comparisons[0]["dataset"]
    if attempt is not None:
        title = RULE_VALIDATION_TITLE.format(rule=rule, n=attempt)
    else:
        cands = list(dict.fromkeys(c["b"]["label"] for c in comparisons))       # one label per distinct candidate
        costs = [n["cost_twd"] for n in nets if n]
        title = f"規則回測並列：{comparisons[0]['a']['label']} vs " + "、".join(cands)
        if costs:
            title += f"（c = {'、'.join(map(str, costs))}）"
    lines = [f"## {date} · {title}", "",
             f"- 資料集：台灣區 `{ds['id'][:8]}…`（{PART.get(ds['split'], ds['split'])}，截止 {ds['cutoff'][:10]}）",
             f"- 基準：{comparisons[0]['a']['label']}",
             f"- 結果檔：" + "、".join(f"`{f}`" for f in files)]
    if change:
        lines.append(f"- 這次改了什麼、為什麼：{change}")
    labels = [f"c = {n['cost_twd']}" if n else f"候選 {i + 1}" for i, n in enumerate(nets)]
    lines += ["", "| 指標 | 基準 | " + " | ".join(labels) + " |", "|---|---|" + "---|" * len(labels)]
    for k, row in enumerate(comparisons[0]["rows"]):
        values = [c["rows"][k]["b"] for c in comparisons]
        lines.append(f"| {row['title']} | {_fmt(row['a'], row['format'])} | "
                     + " | ".join(_fmt(v, row["format"]) for v in values) + " |")
    if any(nets):
        lines += ["", "**淨效益**（多省 − c × 多等月數；兩邊都可評估的決策；差距的 95% 區間依遊戲成對重抽樣）：", "",
                  "| 候選 | 照建議買 | 決策數 | 基準：多省 / 多等（天）/ 淨效益 | 候選：多省 / 多等（天）/ 淨效益 | 差距 [95% 區間] |",
                  "|---|---|---|---|---|---|"]
        for n in nets:
            if not n:
                continue
            for mode in ("monthly", "fixed"):
                m = n["modes"][mode]
                if not m["n"]:
                    continue
                side = lambda x: f"{_money(x['saving'])} / {x['wait_days']:.1f} / {_money(x['net'])}"  # noqa: E731
                lines.append(f"| c = {n['cost_twd']} | {MODES[mode]} | {m['n']:,} | {side(m['a'])} | {side(m['b'])} | "
                             f"{m['diff']:+.1f} [{m['ci'][0]:+.1f}, {m['ci'][1]:+.1f}] |")
        for n in nets:
            if n and n["verdict"]:
                m = n["modes"]["monthly"]
                word = "通過" if n["verdict"] == "pass" else "未通過"
                lines += ["", f"**硬門檻**（驗證組、c = {n['cost_twd']}、每月重新評估；spec FR-015）：{word}，"
                              f"差距 {m['diff']:+.1f} [{m['ci'][0]:+.1f}, {m['ci'][1]:+.1f}]。換版另需使用者同意。"]
    if by_cost and any(r["costs"] for r in by_cost):
        costs = sorted({c for r in by_cost for c in r["costs"]})
        lines += ["", "**各評估成本下的平均淨效益**（每月重新評估，各結果自己的全部決策）：", "",
                  "| 結果 | " + " | ".join(f"c = {c}" for c in costs) + " |", "|---|" + "---|" * len(costs)]
        for r in by_cost:
            lines.append(f"| {r['result']} | " + " | ".join(_money(r["costs"].get(c)) for c in costs) + " |")
    for label, wishlist in zip(labels, wishlists):
        if not wishlist:
            continue
        c = wishlist["counts"]
        lines += ["", f"**願望清單（現在），{label}**：" + "、".join(f"{NAMES[g]} {c['a'][g]} → {c['b'][g]}" for g in GROUPS)]
        if wishlist.get("mean_net_twd"):
            mn = wishlist["mean_net_twd"]
            lines.append(f"期望淨效益平均 NT${_money(mn['a'])} → NT${_money(mn['b'])}；"
                         f"範圍放寬到 24 個月／5 年時，最晚一場在 12 個月以後的款數："
                         f"{wishlist.get('longer_24')}／{wishlist.get('longer_60')}。")
        detailed = len(wishlists) == 1 or wishlist.get("cost_twd") == DEFAULT_WAIT_COST
        if wishlist["changed"] and not detailed:
            lines.append(f"改變的遊戲 {len(wishlist['changed'])} 款（逐款列表只列 c = {DEFAULT_WAIT_COST}）。")
        elif wishlist["changed"]:
            lines += ["", "| 遊戲 | 基準 | 候選 |", "|---|---|---|"]
            for ch in wishlist["changed"]:
                f, t = ch["from"], ch["to"]
                net = lambda x: "" if x.get("net_twd") is None else f"，淨效益 NT${x['net_twd']:,}"  # noqa: E731
                lines.append(f"| {ch['name']} | {NAMES[f['group']]} NT${f['sweet_twd']}（-{f['sweet_pct']}%）@ {f['point']}"
                             f"{net(f)} | {NAMES[t['group']]} NT${t['sweet_twd']}（-{t['sweet_pct']}%）@ {t['point']}"
                             f"{net(t)} |")
        for o in wishlist["one_side"]:
            lines.append(f"- {o['name']}：基準 {o['a']}、候選 {o['b']}")
    if decision:
        lines += ["", f"**使用者的決定**：{decision}"]
    lines.append("")
    return "\n".join(lines)
