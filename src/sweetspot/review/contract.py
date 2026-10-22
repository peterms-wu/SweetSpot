"""steamsage.review/1, its text summary and the comparisons.md draft (feature 013 contracts/review.md).

The text and the draft only read the result dict, so every number they show is in the JSON (SC-009).
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sweetspot.calendar import label
from sweetspot.forecast.contract import write_json_atomic
from sweetspot.review.target import ReviewTarget

SCHEMA = "steamsage.review/1"
DEFINITIONS = {"primary": "sale-max", "secondary": "crossing"}
TAIPEI = timedelta(hours=8)
GROUP_ZH = {"now": "現在買", "soon": "即將到價", "wait": "繼續等", "low": "低信心", "na": "無法預測"}


def iso(moment: datetime | None) -> str | None:
    return None if moment is None else moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def target_dict(t: ReviewTarget) -> dict[str, Any]:
    rec = t.record
    return {
        "sale": {"season": t.sale.season, "year": t.sale.year, "label": label(t.sale), "start": iso(t.sale.start),
                 "end": iso(t.sale.end)},
        "record": {"file": t.record_path.name, "as_of": iso(t.as_of), "schema": rec.get("schema"),
                   "model": (rec.get("forecast") or {}).get("model"), "rule": rec.get("rule"),
                   "bundle_rule": rec.get("bundle_rule"), "hours_before_start": t.hours_before_start},
        "during": {"files": [p.name for p, _ in t.during], "missing_days": list(t.missing_days)},
        "today": iso(t.today), "forced": t.forced, "skipped_records": list(t.skipped_records),
    }


def counts(record: dict, games: list[dict]) -> dict[str, Any]:
    groups: dict[str, int] = {}
    for d in record.get("decisions") or []:
        g = d.get("group") or "na"
        groups[g] = groups.get(g, 0) + 1
    return {"records": len(games), "reviewed": sum(g["status"] == "reviewed" for g in games),
            "no_actual": sum(g["status"] == "no-actual" for g in games),
            "not_scored": sum(g["status"] == "not-scored" for g in games),
            "corrected": sum(bool(g["actual"] and g["actual"]["corrected"]) for g in games), "groups": groups}


def review_dict(target: ReviewTarget, games: list[dict], summary: dict, sources: dict, run: dict) -> dict[str, Any]:
    return {"schema": SCHEMA, "target": target_dict(target), "definitions": dict(DEFINITIONS),
            "games": sorted(games, key=lambda g: g["app_id"]), "summary": summary, "sources": sources, "run": run}


def write_review(path: Path, data: dict) -> Path:
    return write_json_atomic(path, data)


# --- text ---------------------------------------------------------------------------------------------------

def _taipei(text: str) -> str:
    moment = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ") + TAIPEI
    return f"{moment.month}/{moment.day} {moment:%H:%M}"


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def _interval(s: dict, pct: bool = False) -> str:
    if not s.get("interval"):
        return ""
    lo, hi = s["interval"]
    return f" [{_pct(lo)}, {_pct(hi)}]" if pct else f" [{lo:.4f}, {hi:.4f}]"


def _twd(cents: int | None) -> str:
    if cents is None:
        return "—"
    return f"NT${cents / 100:,.0f}" if cents % 100 == 0 else f"NT${cents / 100:,.2f}"


def _names(games: list[dict], apps) -> str:
    by_id = {g["app_id"]: g["name"] for g in games}
    return "、".join(by_id.get(a, str(a)) for a in apps)


def summary_text(data: dict) -> str:
    t, s, games = data["target"], data["summary"], data["games"]
    sale, rec, c = t["sale"], t["record"], s["counts"]
    model, rule = rec.get("model") or {}, rec.get("rule") or {}
    lines = [f"事後對照：{sale['label']}（台北 {_taipei(sale['start'])} – {_taipei(sale['end'])}）",
             f"預測紀錄：{rec['file']}（開賣前 {rec['hours_before_start']} 小時；{model.get('name')} {model.get('version')}、"
             f"{rule.get('name')} {rule.get('version')}）"]
    extra = []
    if c["not_scored"]:
        extra.append(f"{c['not_scored']} 款紀錄中沒有預測")
    if c["no_actual"]:
        extra.append(f"{c['no_actual']} 款無法對照")
    line = f"對照 {c['reviewed']}/{c['records']} 款" + (f"（{'；'.join(extra)}）" if extra else "")
    fixed = s.get("mismatches", {}).get("corrected") or []
    if fixed:
        line += f"；依每日價格紀錄補正 {len(fixed)} 款（{'、'.join(x['name'] for x in fixed)}）"
    lines.append(line)
    if t["forced"]:
        lines.append("注意：特賣結束不到 3 天，價格歷史可能還沒補齊（--force）")
    if t["skipped_records"]:
        lines.append(f"讀不到的紀錄：{'、'.join(t['skipped_records'])}")
    lines.append("")
    se = s["seasonal"]
    sm, cr = se["brier"]["sale_max"], se["brier"]["crossing"]
    if sm["value"] is not None:
        lines.append(f"季節機率  Brier {sm['value']:.4f}{_interval(sm)}（特賣最深折扣，{sm['n']} 款）；"
                     f"回測的定義 {cr['value']:.4f}{_interval(cr)}（回測：只計已結束 {cr['backtest']}"
                     f"{'，在區間外' if cr['differs'] else '，在區間內'}）；兩種定義不同的 {len(se['differs_games'])} 款")
    d = s["decisions"]
    soon = d["on_time"].get("soon")
    if soon:
        missed = [m for m in d["misses"] if m["group"] == "soon"]
        tail = f"；未到：{'、'.join(m['name'] for m in missed)}" if missed else ""
        lines.append(f"即將到價  {soon['hits']}/{soon['n']} 到甜蜜價 {_pct(soon['value'])}{_interval(soon, True)}"
                     f"（規則回測 {_pct(soon['backtest'])}）{tail}")
    e = d["early"]
    lines.append(f"繼續等    提早到價 {e['n']} 款：特賣中改成現在買 {e['first_now']}、錯過 {e['missed']}、無法判斷 {e['unknown']}")
    n = d["now"]
    lines.append(f"現在買    {n['n']} 款：等到特賣 更低 {n['lower']}、相同 {n['same']}、更高 {n['higher']}")
    for b in s.get("bundles") or []:
        lines.append(f"組合包    {_bundle_line(b)}")
    ns = s.get("non_seasonal")
    if ns:
        lines.append(f"非季節    {_ns_line(ns)}")
    rc = s.get("recompute")
    if rc:
        lines.append(f"重算      {_recompute_line(rc)}")
    return "\n".join(lines)


def _recompute_line(rc: dict) -> str:
    line = (f"正式紀錄 {_num(rc['record']['value'])}、重算的現行模型 {_num(rc['current']['value'])}、"
            f"基準模型 {_num(rc['baseline']['value'])}（{rc['record']['n']} 款，特賣最深折扣；不判定優劣）")
    dr = rc["probability_drift"]
    if dr["moved"]:
        line += f"；這一場的機率有 {dr['moved']}/{dr['games']} 款和紀錄不同（最多差 {_num(dr['max'])}）"
    if rc["different"]:
        line += "；決策和紀錄不同：" + "、".join(
            f"{d['name']}（{GROUP_ZH.get(d['record_group'], d['record_group'])} {_twd(d['record_sweet_cents'])}→"
            f"{GROUP_ZH.get(d['current_group'], d['current_group'])} {_twd(d['current_sweet_cents'])}，{d['reason']}）"
            for d in rc["different"])
    if rc.get("note"):
        line += f"；{rc['note']}"
    return line


# --- comparisons.md draft (US6, FR-019) ------------------------------------------------------------------------

def _verdict(s: dict) -> str:
    if s.get("differs") is None:
        return "—"
    return "和回測不同" if s["differs"] else "和回測一致"


def _range(s: dict, pct: bool = False) -> str:
    if not s.get("interval"):
        return "—"
    lo, hi = s["interval"]
    return f"{_pct(lo)}–{_pct(hi)}" if pct else f"{lo:.4f}–{hi:.4f}"


def _num(x: float | None) -> str:
    return "—" if x is None else f"{x:.4f}"


def doc_draft(data: dict) -> str:
    """The 「事後對照」 section for docs/model/comparisons.md. Every figure is read from `data` (SC-009); names, labels
    and dates are copied as they appear in it."""
    t, s, games = data["target"], data["summary"], data["games"]
    sale, rec, c = t["sale"], t["record"], s["counts"]
    model, rule, brule = rec.get("model") or {}, rec.get("rule") or {}, rec.get("bundle_rule") or {}
    se, d = s["seasonal"], s["decisions"]
    out = [f"## {t['today'][:10]} · 事後對照：{sale['label']}（紀錄 {rec['file']}）", ""]
    out.append(f"- 資料截止：{t['today']}；特賣 {sale['start']} – {sale['end']}（UTC）；紀錄的分析時點 {rec['as_of']}，"
               f"開賣前 {rec['hours_before_start']} 小時。")
    out.append(f"- 版本：{model.get('name')} {model.get('version')}、{rule.get('name')} {rule.get('version')}、"
               f"{brule.get('name')} {brule.get('version')}。")
    unknown = [g for g in games if g["status"] == "no-actual"]
    line = (f"- 對照 {c['reviewed']}/{c['records']} 款；紀錄中沒有預測 {c['not_scored']} 款；無法對照 {c['no_actual']} 款"
            + (f"（{'、'.join(g['name'] + '：' + g['reason'] for g in unknown)}）" if unknown else ""))
    fixed = s["mismatches"]["corrected"]
    if fixed:
        line += (f"；依每日價格紀錄補正 {len(fixed)} 款（"
                 + "、".join(f"{m['name']}：價格歷史 {m['history_max_cut']}%、每日紀錄 {m['daily_max_cut']}%" for m in fixed)
                 + "）")
    out.append(line + "。")
    if t["forced"]:
        out.append("- 特賣結束不到 3 天就執行（--force），價格歷史可能還沒補齊。")
    out.append("- 一場特賣、少數遊戲的結果，區間很寬；這是事後對照，不是新的準確率，不取代回測（憲章 IV）。")
    out += ["", "| 項目 | 本次 | 區間 | 回測 | 判斷 |", "|---|---|---|---|---|"]
    sm, cr = se["brier"]["sale_max"], se["brier"]["crossing"]
    out.append(f"| 季節機率 Brier（特賣期間的最深折扣，主要） | {_num(sm['value'])} | {_range(sm)} | — | 定義和回測不同，只並列 |")
    out.append(f"| 季節機率 Brier（回測的定義：分析時點之後首次進入） | {_num(cr['value'])} | {_range(cr)} | "
               f"{cr['backtest']} | {_verdict(cr)} |")
    for group, st in d["on_time"].items():
        out.append(f"| {GROUP_ZH[group]}：甜蜜時點是這一場、到甜蜜價 | {st['hits']}/{st['n']}（{_pct(st['value'])}） | "
                   f"{_range(st, True)} | {_pct(st['backtest'])} | {_verdict(st)} |")
    out.append("")
    names = _names(games, se["differs_games"])
    if se["differs_games"]:
        out.append(f"- 兩種定義結果不同的 {len(se['differs_games'])} 款（{names}）：分析時點已經以特賣的折扣在打，特賣期間沒有更深。"
                   "模型的證據是每場特賣的最深折扣、不看分析時點正在打的折扣，所以給高機率；回測的定義記為沒到價。")
    conf = "；".join(f"{'一般' if k == 'normal' else '低信心' if k == 'low' else k} {v['games']} 款 "
                    f"{_num(v['sale_max'])}／{_num(v['crossing'])}" for k, v in se["by_confidence"].items())
    out.append(f"- 依信心等級（主要／回測的定義）：{conf}。")
    for m in d["misses"]:
        out.append(f"- 未到甜蜜價：{m['name']}（{GROUP_ZH.get(m['group'], m['group'])}，差 {_twd(m['gap_cents'])}）。")
    e = d["early"]
    if e["n"]:
        first = "、".join(f"{g['name']}（{g['switch']['as_of']}）" for g in e["games"] if g["switch"]["state"] == "first_now")
        out.append(f"- 提早到價（甜蜜時點在之後、這一場就到價）{e['n']} 款：特賣中改成現在買 {e['first_now']}"
                   + (f"（{first}）" if first else "") + f"、錯過 {e['missed']}、無法判斷 {e['unknown']}。")
    n = d["now"]
    if n["n"]:
        out.append(f"- 現在買 {n['n']} 款：等到特賣更低 {n['lower']}、相同 {n['same']}、更高 {n['higher']}"
                   f"（規則回測：12 個月內出現更深折扣 {_pct(n['backtest_now_deeper_within_12m'])}）。")
    out += _doc_extras(s, games)
    out += ["", "**之後可以考慮的候選**（只記錄，由使用者決定是否另開 feature）", ""]
    cands = []
    if se["differs_games"]:
        cands.append(f"模型不看分析時點正在打的折扣（本次 {len(se['differs_games'])} 款）。")
    if fixed:
        cands.append(f"每日更新誤隔離 ITAD 的價格事件：{'、'.join(m['name'] for m in fixed)}的價格歷史少了這場折扣"
                     "（每日更新的問題，另開小修補）。")
    for m in d["misses"]:
        cands.append(f"{m['name']} 判為{GROUP_ZH.get(m['group'], m['group'])}卻沒到價。")
    out += [f"- {x}" for x in cands] or ["- （無）"]
    return "\n".join(out)


KIND_ZH = {"next-sale": "下一場買組合包", "now": "現在買組合包", "separately": "分開買"}


def _bundle_line(b: dict) -> str:
    a, adv = b.get("actual"), b.get("advice")
    actual = (f"特賣期間最低 {_twd(a['min_cents'])}（組合包折扣 {'、'.join(f'{x}%' for x in a['discounts']) or '不明'}"
              f"{'，和紀錄當時相同' if a['discount_same'] else '，和紀錄當時不同'}）") if a else b["actual_reason"]
    if not b["scored"] or adv is None:
        return f"{b['name']}（{b['grade']}，只列出）：{actual}"
    if adv["kind"] == "next-sale":
        head = f"{b['name']}：{KIND_ZH[adv['kind']]}，推算 {_twd(adv['estimate_cents'])}（同時到價 {_pct(adv['joint_probability'])}）"
        joint = {True: "；內容都到了推算用的折扣", False: "；有內容沒到推算用的折扣", None: "；內容的到價不明"}[b["joint_hit"]]
    else:
        head = f"{b['name']}：{KIND_ZH.get(adv['kind'], adv['kind'])}，紀錄當時 {_twd(adv['price_cents'])}"
        joint = ""
    g = b["estimate_gap_cents"]
    base = "推算" if adv["kind"] == "next-sale" else "紀錄當時"
    gap = "" if g is None else f"，和{base}相同" if g == 0 else f"，比{base}{'低' if g < 0 else '高'} {_twd(abs(g))}"
    plan = b["separate_plan"]
    sep = f"；分開買到目前 {_twd(plan['cents'])}" + ("" if plan["complete"] else f"（未完成：{len(plan['pending'])} 款的甜蜜時點未到）")
    return f"{head} → {actual}{gap}{joint}{sep}"


def _ns_line(ns: dict) -> str:
    parts = []
    for h, v in ns["horizons"].items():
        b = v["brier"]
        if v["games"]:
            parts.append(f"{h} 天 {v['games']} 款 Brier {_num(b['value'])}（回測 {b.get('backtest')}，{_verdict(b)}）")
        elif v["waiting_history_games"]:
            parts.append(f"{h} 天 0 款可計分（{v['waiting_history_games']} 款已到期、價格歷史還沒到到期日）")
        else:
            parts.append(f"{h} 天 0 款到期")
    line = "；".join(parts)
    if ns.get("next_due"):
        line += f"；下一個到期 {ns['next_due']}"
    for e in ns.get("earlier") or []:
        result = {True: "到價", False: "沒到價", None: "還不能判斷"}[e["hit"]]
        line += (f"；可能更早到價：{e['name']}（{e['horizon_days']} 天，{_pct(e['probability'])}）{result}"
                 f"（回測 {_pct(e['backtest'])}）")
    return line


def _doc_extras(s: dict, games: list[dict]) -> list[str]:
    """Bundles, non-seasonal and recompute lines."""
    out = []
    bundles = s.get("bundles") or []
    if bundles:
        out.append(f"- 組合包（{len(bundles)} 個，逐個列出、不算命中率）：")
        out += [f"  - {_bundle_line(b)}" for b in bundles]
    if s.get("non_seasonal"):
        out.append(f"- 非季節（只計已到期、價格歷史涵蓋整個期間的）：{_ns_line(s['non_seasonal'])}。")
    if s.get("recompute"):
        out.append(f"- 同一時點重算（今天的資料庫、只看分析時點以前）：{_recompute_line(s['recompute'])}。")
    return out
