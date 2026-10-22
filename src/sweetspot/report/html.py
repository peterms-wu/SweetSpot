"""Render a `steamsage.decision/1` or `/2` dict as one self-contained HTML page (contracts/report-html.md; research R8).

Presentation only: it reads the contract dict and never imports the analysis core, never computes prices or
probabilities (constitution VII). Formatting is limited to thousands separators, percentages and showing UTC times
in Taipei time. Every string from the contract is HTML-escaped (constitution IX).
"""

from datetime import datetime, timedelta
from html import escape
from typing import Any

GROUPS = (("now", "現在買"), ("soon", "即將到價"), ("wait", "繼續等"), ("low", "低信心"), ("na", "無法預測"))
GROUP_NAMES = dict(GROUPS)
TAGS = {"low-confidence": "低信心", "no-history-curve": "改用整體比例", "regular-mismatch": "原價不一致",
        "stale-price": "現價可能已變", "price-unknown": "現價未知", "tolerance-min": "下限生效",
        "tolerance-max": "上限生效", "below-history": "低於過去最低", "non-seasonal-deeper": "非季節折扣更深",
        "earlier-possible": "可能提早"}
SOURCES = {"steam-current": "Steam 現價", "itad-history": "ITAD 歷史", "legacy-itad": "ITAD 歷史（舊專案匯入）",
           "steam-option": "Steam 購買選項的價格", "itad-option-history": "ITAD 歷史（指定的版本）"}
POINT_STATUS = {"announced": "官方", "estimated": "預估"}
CHANGE_CAUSES = {"user": "（使用者指定）", "unset": "（取消指定）", "fallback": "（指定的版本不能用）"}   # feature 009
BUNDLE_GRADES = {"pure": "只含願望清單遊戲", "mixed": "含其他內容"}                                     # feature 010
BUNDLE_ROLES = {"wishlist": "願望清單遊戲", "wishlist-dlc": "願望清單遊戲的 DLC", "other-game": "其他遊戲",
                "other": "其他內容"}
TAIPEI = timedelta(hours=8)


def _t(text: Any) -> str:
    return escape("" if text is None else str(text), quote=True)


def _local(stamp: str | None) -> str:
    if not stamp:
        return "未知"
    moment = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ") + TAIPEI
    return moment.strftime("%Y-%m-%d %H:%M")


def _money(value: int | None) -> str:
    if value is None:
        return "未知"
    return f"NT${value:,}" if value >= 0 else f"-NT${-value:,}"


def _cost(data: dict) -> int | None:
    """The waiting cost of a rule 3.0.0 contract (feature 005); None for the tolerance rules."""
    return (data.get("preferences") or {}).get("wait_cost_twd")


def _pct(p: float | None) -> str:
    return "—" if p is None else f"{p:.0%}"


def _off(pct: int | None) -> str:
    return "原價" if not pct else f"-{pct}%"


def _probability_title(d: dict) -> str:
    """Hover text of 到價機率 (2026-10-18; the extension's lib.js says the same): the forecast for the sweet point,
    not about the current price, which a buy-now game has already beaten."""
    return (f'到 {d["sweet_point"]["label"]}為止，季節特賣打到 -{int(d["sweet_pct"])}%（{_money(d["sweet_twd"])}）'
            "以上的機率；跟現價無關")


# --- header ------------------------------------------------------------------------------------------------

def lowest_label(data: dict) -> str:
    """P_min's name under the contract's rule: 12 months (sweet-price 2.0.0) or the whole curve (1.0.0)."""
    return "12 個月內最低" if (data.get("rule") or {}).get("constants", {}).get("p_min_months") else "長期最低"


_lowest = lowest_label


def _preferences(p: dict, lowest: str = "長期最低") -> str:
    soon = "下一場季節特賣" if p["soon_sales"] == 1 else f"前 {p['soon_sales']} 場季節特賣"
    if "wait_cost_twd" in p:                            # rule 3.0.0 (feature 005): no tolerance
        c = p["wait_cost_twd"]
        return (f"等待成本 NT${c}／月（使用者偏好）：每多等一個月要多省 NT${c} 才值得；"
                f"即將到價 = 甜蜜時點在{soon}")
    return (f"折扣差距：{lowest}價淺於 -{p['gap_boundary_pct']}% 時 {p['gap_pp_shallow']} 個百分點，"
            f"-{p['gap_boundary_pct']}% 以上 {p['gap_pp_deep']} 個百分點；容許差距 NT${p['tolerance_min_twd']}–"
            f"NT${p['tolerance_max_twd']}；即將到價 = 甜蜜時點在{soon}（使用者偏好）")


def _comparison(data: dict) -> list[str]:
    if data.get("preview"):
        return []                                       # the preview banner already says it (feature 005)
    if not data["official"]:
        return ["以過去時點執行：不保存紀錄，也不和其他紀錄比較"]
    comp = data.get("comparison") or {}
    base = comp.get("baseline")
    if not base:
        lines = ["沒有前一天或更早的紀錄，無法比較"]
    else:
        lines = [f"與 {_local(base['as_of'])} 的紀錄比較：{comp.get('changed_games', 0)} 款有變動"]
    lines += [f"版本或偏好改變：{c}（部分變動可能來自這個改變）" for c in comp.get("version_changes") or []]
    lines += [f"特賣日期更新：{c}（部分變動可能來自這個改變）" for c in comp.get("calendar_changes") or []]
    if comp.get("skipped_records"):
        lines.append("略過無法讀取的紀錄：" + "、".join(comp["skipped_records"]))
    return lines


def _backtest_note(bt: dict | None) -> str:
    if not bt:
        return "甜蜜價規則尚未以現行模型與規則回測：本報告不引用任何準確率。"
    hit = bt["hit_rate"]
    region = {"TW": "台灣區"}.get(bt["region"], bt["region"])
    cost = f"，以等待成本 NT${bt['wait_cost_twd']} 回測" if bt.get("wait_cost_twd") is not None else ""
    return (f"規則回測（{region}、分析時點後 {bt['window_months']} 個月內，{bt['date']}{cost}）："
            f"即將到價 {_pct(hit.get('soon'))}、繼續等 {_pct(hit.get('wait'))}、低信心 {_pct(hit.get('low'))} "
            f"在甜蜜時點前到價；判為現在買之後 12 個月內，{_pct(bt.get('now_deeper_within_12m'))} 出現更深折扣。"
            "願望清單的遊戲比回測資料集的平均更難預測。")


def _group_note(group: str, bt: dict | None) -> str:
    if not bt or group == "na":
        return ""
    if bt.get("wait_cost_twd") is not None:
        return f"{_group_note(group, {**bt, 'wait_cost_twd': None})}（以等待成本 NT${bt['wait_cost_twd']} 回測）"
    if group == "now":
        return f"回測中判為現在買之後 12 個月內，{_pct(bt.get('now_deeper_within_12m'))} 出現更深折扣"
    rate = bt["hit_rate"].get(group)
    if group == "low":
        return f"回測中只有約 {_pct(rate)} 在這個時點前到價，僅供參考"
    return f"回測到價率 {_pct(rate)}"


def _ns_header(data: dict) -> str:
    """Feature 007: which non-seasonal model the report shows; nothing for contracts written before it."""
    block = data.get("non_seasonal")
    if not block:
        return ""
    if block.get("adopted") and block.get("model"):
        return f" · 非季節 {block['model']['name']} {block['model']['version']}"
    return " · 非季節預測：只顯示過去紀錄"


def _ns_section(d: dict) -> str:
    """Feature 007 (contracts/cli-and-report.md): the decision's non-seasonal sentences, printed as they are."""
    lines = (d.get("non_seasonal") or {}).get("reasons") or []
    if not lines:
        return ""
    return f'<div class="ns"><h3>季節特賣以外</h3><ul>{"".join(f"<li>{_t(r)}</li>" for r in lines)}</ul></div>'


def _header(data: dict) -> str:
    fc = data["forecast"]
    rule = data["rule"]
    banners = []
    if data.get("preview"):
        banners.append(f"預覽：非現行規則（{rule['name']} {rule['version']}），不寫紀錄、不和前一天比較")
    note = (data.get("data_refresh") or {}).get("note")
    if note:
        banners.append(note)
    banners += data.get("calendar_notices") or []            # feature 012 (plan D1)
    if data.get("reference_notice"):                         # feature 014 FR-014a
        banners.append(reference_notice_text(data["reference_notice"]))
    record = data.get("record")
    if record and not record.get("saved"):
        banners.append("本次紀錄未保存，下次仍與原比較基準比較" + (f"（{record['error']}）" if record.get("error") else ""))
    counts = data["summary"]
    nav = "".join(f'<a class="chip" href="#group-{g}">{name}（{counts.get(g, 0)}）</a>' for g, name in GROUPS)
    if data.get("bundles"):
        nav += f'<a class="chip" href="#bundles">組合包（{len(data["bundles"])}）</a>'
    notes = [*(f"{n}。" for n in data.get("notes") or []),
             # 006: Steam's default purchase option; 009: an edition the user chose (014 T077)
             "價格指 Steam 商店預設的購買選項（通常是一般版）；在設定檔 [purchase_options] 指定了版本的遊戲，指那個版本。",
             _backtest_note(data.get("rule_backtest"))]
    return f"""
<header>
  <h1>願望清單甜蜜價報告</h1>
  <p class="meta">分析時間 {_t(_local(data['as_of']))}（台北）· 資料截止 {_t(_local(fc.get('data_cutoff')))} ·
    模型 {_t(fc['model']['name'])} {_t(fc['model']['version'])} · 規則 {_t(rule['name'])} {_t(rule['version'])}{_t(_ns_header(data))}</p>
  {''.join(f'<p class="banner">{_t(b)}</p>' for b in banners)}
  <p class="meta">{_t(_preferences(data['preferences'], _lowest(data)))}</p>
  {''.join(f'<p class="meta">{_t(line)}</p>' for line in _comparison(data))}
  <nav>{nav}</nav>
  <ul class="notes">{''.join(f'<li>{_t(n)}</li>' for n in notes)}</ul>
  <input id="filter" type="search" placeholder="依名稱篩選" aria-label="依名稱篩選">
</header>"""


# --- games -------------------------------------------------------------------------------------------------

def _change(change: dict | None) -> str:
    if not change:
        return ""
    parts = []
    if change.get("group"):
        parts.append(f"上次：{GROUP_NAMES.get(change['group']['from'], change['group']['from'])}")
    if change.get("sweet_point"):
        parts.append(f"上次：{change['sweet_point']['from']}")
    if change.get("sweet_twd"):
        parts.append(f"上次：{_money(change['sweet_twd']['from'])}")
    if change.get("version"):
        v = change["version"]
        when = f"（偵測於 {_local(v['detected_at'])[:10]}）" if v.get("detected_at") else ""
        why = CHANGE_CAUSES.get(v.get("cause"), "")
        parts.append(f"版本更換{why}：{v['from']} → {v['to']}{when}")
    return f'<span class="change">變動 · {_t(" · ".join(parts))}</span>'


def _version(d: dict) -> str:
    text = version_text(d)
    return f'<small class="version">{_t(text)}</small>' if text else ""


def version_text(d: dict) -> str | None:
    """Which product's price history the forecast used (feature 006, spec FR-013); read from the decision only.
    Plain text, shared by the report and the extension data file (feature 011)."""
    v = d.get("version")
    if not v:
        return None
    parts = []
    if v.get("source") == "user":                      # 009: a user's choice is always shown (014 T073)
        name = (v.get("option") or {}).get("name") or v.get("package_name")
        parts.append(f"追蹤 {name}（使用者指定）")
        if v.get("basis") != "user":                   # the Steam default itself, or an edition on its product:
            parts.append("和 Steam 預設的價格歷史相同；刪掉設定檔中的這一行即可取消指定")    # its row is not listed
        if v.get("history_start"):
            parts.append(f"歷史從 {_local(v['history_start'])[:10]} 起")
        if v.get("aux_pending"):
            parts.append("美國區歷史下一次更新才會取得")
        if v.get("tracking") == "stopped":
            parts.append(f"價格歷史停止更新（最後確認 {_local(v.get('last_confirmed'))[:10]}）")
        return " · ".join(parts)
    if v.get("source") == "user-fallback" and v.get("fallback"):
        parts.append(v["fallback"]["text"])
    if v["basis"] == "own" and d["group"] != "na":
        parts.append("這個時點沒有版本紀錄，沿用 App 本身的價格歷史" if v.get("basis_reason") == "no-record"
                     else "無法確認 Steam 目前賣的版本，沿用 App 本身的價格歷史")
    if v["basis"] == "version" and v.get("package_name") and v.get("itad_id") != v.get("own_itad_id"):
        parts.append(f"追蹤 {v['package_name']}")
        if v.get("history_start"):
            parts.append(f"歷史從 {_local(v['history_start'])[:10]} 起")
        if v.get("change"):
            parts.append(f"{_local(v['change']['detected_at'])[:10]} 偵測到版本更換")
    if v.get("tracking") == "stopped":
        parts.append(f"價格歷史停止更新（最後確認 {_local(v.get('last_confirmed'))[:10]}）")
    return " · ".join(parts) if parts else None


def _editions_hint(d: dict) -> str:
    """Feature 009 (clarify): the summary row only counts the other editions; the list is in the details."""
    editions = d.get("editions") or []
    return f'<span class="tag editions">另有 {len(editions)} 個版本</span>' if editions else ""


def edition_refusal_text(e: dict) -> str:
    """Why an edition cannot be chosen (feature 009); also the extension's version list (feature 015)."""
    if e.get("verification") == "rejected":
        why = e.get("reason_text") or " ".join(x for x in (e.get("reason_code"), e.get("reason_detail")) if x)
        return f"核對未通過：{why}；不能指定，也不使用它的價格歷史"
    return "沒有 ITAD 的價格歷史，不能指定"


def _edition_row(e: dict) -> str:
    """One row of the other-editions table: prices, the TW low and history start, and how to choose it."""
    rejected = e.get("verification") == "rejected"
    if rejected:
        history = start = "—"
    else:
        history = (f"{_money(e['low_twd'])}（{_local(e['low_at'])[:10]}）" if e.get("low_twd") is not None
                   else "—（還沒有價格歷史）")
        start = _local(e["history_start"])[:10] if e.get("history_start") else "—"
    if e.get("config_line"):
        action = (f'<code>{_t(e["config_line"])}</code> '
                  f'<button type="button" class="copy" data-copy="{_t(e["config_line"])}">複製</button>')
    elif e.get("unset_hint"):
        action = _t("Steam 預設版本：刪掉設定檔中的這一行即可取消指定")
    else:
        action = _t(edition_refusal_text(e))
    name = e["name"] or f"{e['kind']}/{e['id']}"
    return (f"<tr><td>{_t(name)}</td><td>{_t(_money(e['price_twd']))} {_t(_off(e['cut_pct']))}</td>"
            f"<td>{_t(_money(e['regular_twd']))}</td><td>{_t(history)}</td><td>{_t(start)}</td><td>{action}</td></tr>")


def _editions_table(d: dict) -> str:
    editions = d.get("editions") or []
    if not editions:
        return ""
    rows = "".join(_edition_row(e) for e in editions)
    return (f'<p class="caption">其他版本（把設定行加進 sweetspot.toml 的 [purchase_options] 就改追蹤那個版本）</p>'
            f'<div class="table-scroll"><table class="editions"><tr><th>版本</th><th>現價</th><th>原價</th>'
            f'<th>台灣區歷史最低價</th><th>歷史起點</th><th>指定</th></tr>{rows}</table></div>')


def _bundle_hint_parts(d: dict, by_id: dict) -> list[tuple[int, str, str]]:
    """Feature 010 (spec FR-014): (bundle id, sentence, specified-edition note) per bundle holding this game."""
    out = []
    for bundle_id in d.get("bundles") or []:
        b = by_id.get(bundle_id)
        if b is None:
            continue
        others = [c["name"] or f"App {c['app_id']}" for c in b["contents"]
                  if c["role"] == "wishlist" and c["app_id"] != d["app_id"]]
        off = f"組合包 −{b['discount_pct']}%" if b.get("discount_pct") is not None else "組合包"
        text = f"可和 {'、'.join(others)} 一起買：{off}"
        if b["grade"] == "mixed":
            text += "（另含其他內容）"
        mine = next((c for c in b["contents"] if c["app_id"] == d["app_id"]), None)
        note = "；組合包含的是 Steam 預設的版本，不是你指定的版本" if mine and mine.get("specified") else ""
        out.append((bundle_id, text, note))
    return out


def bundle_hint_texts(d: dict, by_id: dict) -> list[dict]:
    """The report's bundle hints as plain text, without the link to the card (feature 011)."""
    return [{"id": bundle_id, "text": text + note} for bundle_id, text, note in _bundle_hint_parts(d, by_id)]


def _bundle_hints(d: dict, by_id: dict) -> str:
    """Feature 010 (spec FR-014): one line per bundle holding this game, linking to its card."""
    return "".join(f'<p class="bundle-hint">{_t(text)}，見<a href="#bundle-{int(bundle_id)}">〈組合包〉</a>'
                   f'{_t(note)}</p>' for bundle_id, text, note in _bundle_hint_parts(d, by_id))


def tag_labels(tags: list[str]) -> list[str]:
    return [TAGS[t] for t in tags if t in TAGS]


def _tags(tags: list[str]) -> str:
    return "".join(f'<span class="tag">{_t(label)}</span>' for label in tag_labels(tags))


def _game(d: dict, lowest: str = "長期最低", bundles: dict | None = None) -> str:
    hints = _bundle_hints(d, bundles or {})
    name = _t(d["name"] or f"App {d['app_id']}")
    link = f'<a href="https://store.steampowered.com/app/{int(d["app_id"])}/">{name}</a>'
    head = f'<details class="game" data-app="{int(d["app_id"])}" data-name="{_t((d["name"] or "").lower())}">'
    if d["group"] == "na":
        table = hints + _editions_table(d)
        return f'{head}<summary><span class="name">{link}{_editions_hint(d)}{_version(d)}</span>' \
               f'<span class="reason">{_t(d["status_reason"])}</span>' \
               f'</summary>{f"<div class=body>{table}</div>" if table else ""}</details>'
    if d.get("wait_options"):
        return _game_wait_cost(d, head, link, hints)
    cur = d["current"] or {}
    point = d["sweet_point"]
    status = POINT_STATUS.get(point["status"], point["status"])
    summary = (
        f'<summary><span class="name">{link}{_tags(d["tags"])}{_editions_hint(d)}{_change(d.get("change"))}'
        f'{_version(d)}</span>'
        f'<span class="cell"><small>現價</small>{_t(_money(cur.get("price_twd")))} {_t(_off(cur.get("cut_pct")))}</span>'
        f'<span class="cell sweet"><small>甜蜜價</small>{_t(_money(d["sweet_twd"]))} -{int(d["sweet_pct"])}%</span>'
        f'<span class="cell"><small>時點</small>{_t(point["label"])}（{_t(status)}）</span>'
        f'<span class="cell" title="{_t(_probability_title(d))}"><small>到價機率</small>{_t(_pct(d["sweet_probability"]))}</span>'
        f'<span class="cell"><small>{lowest}</small>{_t(_money(d["p_min_twd"]))} -{int(d["p_min_pct"])}%</span>'
        f'</summary>')
    ladder = "".join(
        f'<tr><td>{_t(r["label"])}</td><td>{_t(_off(r["pct"]))}</td><td>{_t(_money(r["twd"]))}</td>'
        f'<td>{_t(_pct(r["probability"]))}</td></tr>' for r in d["ladder"])
    source = SOURCES.get(cur.get("source"), cur.get("source") or "未知")
    body = (
        f'<div class="body"><ul>{"".join(f"<li>{_t(r)}</li>" for r in d["reasons"])}</ul>{_ns_section(d)}'
        f'<table><caption>等待對照表：每場累積機率 ≥ 50% 的最深折扣</caption>'
        f'<tr><th>特賣</th><th>折扣</th><th>價格</th><th>機率</th></tr>{ladder}</table>{hints}{_editions_table(d)}'
        f'<p class="meta">現價來源：{_t(source)}，最後確認 {_t(_local(cur.get("confirmed_at")))}（台北）· '
        f'甜蜜時點 {_t(point["label"])}：{_t(_local(point["start"]))} – {_t(_local(point["end"]))}（台北，{_t(status)}）</p>'
        f'</div>')
    return f"{head}{summary}{body}</details>"


def _months(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f} 個月"


def _wait_row(o: dict) -> str:
    if o["deadline_index"] == 0:
        cells = ["現在買", _money(o["target_twd"]), "—", "—", _money(0), _months(0.0), _money(0), _money(0)]
    elif o["target_pct"] is None:
        cells = [o["deadline_label"], "沒有更低的等級", "—", "—", "—", "—", "—", "—"]
    else:
        likely = f"{o['likely_label']}（{_pct(o['likely_probability'])}）"
        cells = [o["deadline_label"], f"{_money(o['target_twd'])} -{o['target_pct']}%", _pct(o["reach_probability"]),
                 likely, _money(o["expected_saving_twd"]), _months(o["expected_wait_months"]),
                 _money(o["wait_cost_twd"]), _money(o["net_twd"])]
    mark = ' <span class="tag pick">建議</span>' if o["chosen"] else ""
    first = f"<td>{_t(cells[0])}{mark}</td>"
    rest = "".join(f"<td>{_t(c)}</td>" for c in cells[1:])
    return f'<tr class="chosen">{first}{rest}</tr>' if o["chosen"] else f"<tr>{first}{rest}</tr>"


def _game_wait_cost(d: dict, head: str, link: str, hints: str = "") -> str:
    """Rule 3.0.0 (feature 005; contracts/report-html-v005.md): expected saving, cost and the waiting table."""
    cur = d["current"] or {}
    point = d["sweet_point"]
    status = POINT_STATUS.get(point["status"], point["status"])
    e = d["expected"] or {}
    now = d["group"] == "now"
    deadline = (d.get("deadline_point") or {}).get("label") or "—"
    saving = "—" if now else _money(e.get("expected_saving_twd"))
    net = "—" if now else _money(e.get("net_twd"))
    summary = (
        f'<summary class="v3"><span class="name">{link}{_tags(d["tags"])}{_editions_hint(d)}'
        f'{_change(d.get("change"))}{_version(d)}</span>'
        f'<span class="cell"><small>現價</small>{_t(_money(cur.get("price_twd")))} {_t(_off(cur.get("cut_pct")))}</span>'
        f'<span class="cell{"" if now else " sweet"}"><small>{"等下去最好" if now else "甜蜜價"}</small>'
        f'{_t(_money(d["sweet_twd"]))} -{int(d["sweet_pct"])}%</span>'
        f'<span class="cell nowrap"><small>時點</small>{_t(point["label"])}<small>{_t(status)}</small></span>'
        f'<span class="cell"><small>到價機率</small>{_t(_pct(d["sweet_probability"]))}</span>'
        f'<span class="cell"><small>最晚等到</small>{_t(deadline)}</span>'
        f'<span class="cell"><small>期望多省</small>{_t(saving)}</span>'
        f'<span class="cell"><small>淨效益</small>{_t(net)}</span>'
        f'</summary>')
    head_row = "".join(f"<th>{h}</th>" for h in ("最晚等到", "目標價", "到期前達到", "最可能到價", "期望多省", "期望等待",
                                                  "等待成本", "淨效益"))
    source = SOURCES.get(cur.get("source"), cur.get("source") or "未知")
    body = (
        f'<div class="body"><ul>{"".join(f"<li>{_t(r)}</li>" for r in d["reasons"])}</ul>{_ns_section(d)}'
        f'<table class="wait"><caption>等待對照表：每一列是「最晚等到這一場」時淨效益最高的選項</caption>'
        f'<tr>{head_row}</tr>{"".join(_wait_row(o) for o in d["wait_options"])}</table>{hints}{_editions_table(d)}'
        f'<p class="meta">12 個月內最低價（參考）{_t(_money(d["p_min_twd"]))} -{int(d["p_min_pct"])}% · '
        f'現價來源：{_t(source)}，最後確認 {_t(_local(cur.get("confirmed_at")))}（台北）· '
        f'甜蜜時點 {_t(point["label"])}：{_t(_local(point["start"]))} – {_t(_local(point["end"]))}（台北，{_t(status)}）</p>'
        f'</div>')
    return f"{head}{summary}{body}</details>"


def sorted_games(group: str, games: list[dict]) -> list[dict]:
    name = lambda d: d["name"] or ""  # noqa: E731
    keys = {
        "now": lambda d: ((d["current"] or {}).get("price_twd") or 0, name(d)),
        "soon": lambda d: (d["sweet_twd"], name(d)),
        "wait": lambda d: (d["sweet_point"]["index"], name(d)),
        "low": name,
        "na": lambda d: (d["status"], name(d)),
    }
    return sorted(games, key=keys[group])


_sorted = sorted_games


def _groups(data: dict) -> str:
    bt = data.get("rule_backtest")
    soon_sales = data["preferences"]["soon_sales"]
    now_desc = "等下去的淨效益都不划算" if _cost(data) is not None else "現價已經不高於甜蜜價"
    desc = {"now": now_desc,
            "soon": "甜蜜時點是下一場季節特賣" if soon_sales == 1 else f"甜蜜時點在前 {soon_sales} 場季節特賣內",
            "wait": "甜蜜時點在更後面的季節特賣", "low": "資料不足或原價不一致，數字僅供參考",
            "na": "無法產生建議，附原因"}
    out = []
    by_id = {b["id"]: b for b in data.get("bundles") or []}
    for group, title in GROUPS:
        games = _sorted(group, [d for d in data["decisions"] if d["group"] == group])
        note = _group_note(group, bt)
        out.append(
            f'<section id="group-{group}"><details class="group" open><summary><h2>{title}（{len(games)}）</h2>'
            f'<span class="desc">{_t(desc[group])}</span>'
            f'{f"<span class=backtest>{_t(note)}</span>" if note else ""}</summary>'
            f'{"".join(_game(d, _lowest(data), by_id) for d in games) or "<p class=empty>沒有遊戲</p>"}'
            f'</details></section>')
    return "\n".join(out)


def bundle_card_texts(b: dict) -> dict:
    """The sentences of one bundle card as plain text (feature 010; shared with the extension data file, feature 011).
    `lines` are the plain lines in card order; the advice sentence and the mismatch text follow them."""
    advice = b.get("advice")
    lines, advice_text, advice_low = [], None, False
    if b["grade"] == "pure":
        plan = b.get("plan")
        parts = [f"現在：組合包 {_money(b['price_twd'])}", f"分開買 {_money(b['separate_twd'])}"]
        if plan:
            latest = plan["latest_point"]["label"] if plan.get("latest_point") else "現在"
            parts.append(f"各自在甜蜜時點買 {_money(plan['twd'])}（最晚 {latest}）")
        lines.append("｜".join(parts))
        if advice and advice["status"] == "ok":
            lines.append(f"任何一場季節特賣（最早 {advice['sale']['label']}）：約 {_money(advice['estimate_twd'])}，"
                         f"同時到價 {_pct(advice['joint_probability'])}")
            advice_text, advice_low = advice["text"], advice.get("confidence") == "low"
        elif advice:
            lines.append(advice["reason_text"])
    else:
        extra = f"多付 {_money(b['extra_twd'])}，多得 {b['extra_games']} 款遊戲"
        if b.get("extra_game_names"):
            extra += "：" + "、".join(n or "名稱未知" for n in b["extra_game_names"])
        if b.get("extra_dlc"):
            extra += f"、{b['extra_dlc']} 個其他內容（DLC、原聲帶等）"
        lines.append(f"組合包 {_money(b['price_twd'])}｜只買願望清單遊戲 {_money(b['wishlist_twd'])}｜{extra}")
    check_text = (b.get("check") or {}).get("text") or None
    if check_text and any(check_text in line for line in lines):    # the no-advice reason already says it (014 T075)
        check_text = None
    return {"grade_text": BUNDLE_GRADES.get(b["grade"], b["grade"]),
            "discount_text": f"組合包 −{b['discount_pct']}%" if b.get("discount_pct") is not None else "組合包折扣未知",
            "lines": lines, "advice_text": advice_text, "advice_low": advice_low, "check_text": check_text}


def _bundle_card(b: dict) -> str:
    """One bundle (feature 010, contracts/cli-and-report.md). Every number and sentence comes from the dict."""
    texts = bundle_card_texts(b)
    title = b["name"] or f"bundle/{b['id']}"
    summary = (f'<summary><span class="name">{_t(title)}'
               f'<small class="version">{_t(texts["grade_text"])}</small></span>'
               f'<span class="cell"><small>折扣</small>{_t(texts["discount_text"])}</span>'
               f'<span class="cell"><small>現價</small>{_t(_money(b["price_twd"]))}</span></summary>')
    lines = [_t(line) for line in texts["lines"]]
    if texts["advice_text"] is not None:
        tag = '<span class="tag">低信心</span>' if texts["advice_low"] else ""
        lines.append(f'<strong>{_t(texts["advice_text"])}</strong>{tag}')
    if texts["check_text"]:
        lines.append(f'<span class="warn">{_t(texts["check_text"])}</span>')
    rows = "".join(f"<tr><td>{_t(c['name'] or 'App ' + str(c['app_id']))}</td>"
                   f"<td>{_t(BUNDLE_ROLES.get(c['role'], c['role']))}</td><td>{_t(_money(c['price_twd']))}</td></tr>"
                   for c in b["contents"])
    table = (f'<div class="table-scroll"><table class="editions"><tr><th>內容</th><th>角色</th><th>現價</th></tr>'
             f'{rows}</table></div>')
    body = "".join(f"<p>{line}</p>" for line in lines)
    opened = " open" if b["grade"] == "pure" else ""          # mixed bundles can be long (OPUS: 18 contents)
    return (f'<details class="bundle" id="bundle-{int(b["id"])}"{opened}>{summary}<div class="body">{body}{table}'
            f'<p class="meta">{_t(b["owned_note"])}</p></div></details>')


def _bundles(data: dict) -> str:
    items = data.get("bundles") or []
    if not items:
        return ""
    cards = "".join(_bundle_card(b) for b in items)
    return (f'<section id="bundles"><details class="group" open><summary><h2>組合包（{len(items)}）</h2>'
            f'<span class="desc">同時含多款願望清單遊戲的組合包</span></summary>{cards}</details></section>')


CSS = """
:root { --bg:#f7f7f5; --card:#fff; --text:#1d1d1f; --muted:#6b6b70; --line:#e2e2e0; --accent:#1a73e8;
  --good:#1e7d32; --warn-bg:#fff4e5; --warn:#8a4b00; --tag:#eef1f6; --change:#fdecea; --change-text:#a1261b; }
@media (prefers-color-scheme: dark) { :root { --bg:#141416; --card:#1e1e21; --text:#ececef; --muted:#a0a0a8;
  --line:#2f2f33; --accent:#8ab4f8; --good:#81c995; --warn-bg:#3a2a12; --warn:#f6c26b; --tag:#2a2d33;
  --change:#3b1f1d; --change-text:#f28b82; } }
* { box-sizing:border-box; }
body { margin:0; padding:0 16px 48px; background:var(--bg); color:var(--text);
  font:15px/1.55 "Segoe UI","Microsoft JhengHei","PingFang TC","Noto Sans TC",sans-serif; }
header, main { max-width:1100px; margin:0 auto; }
h1 { font-size:24px; margin:24px 0 8px; }
h2 { display:inline; font-size:18px; margin:0 8px 0 0; }
a { color:var(--accent); text-decoration:none; } a:hover { text-decoration:underline; }
.meta { color:var(--muted); margin:4px 0; font-size:13px; }
.banner { background:var(--warn-bg); color:var(--warn); padding:8px 12px; border-radius:8px; font-weight:600; }
nav { display:flex; flex-wrap:wrap; gap:8px; margin:12px 0; }
.chip { background:var(--card); border:1px solid var(--line); border-radius:999px; padding:4px 12px; }
.notes { color:var(--muted); font-size:13px; padding-left:20px; }
#filter { width:100%; max-width:360px; padding:8px 12px; border:1px solid var(--line); border-radius:8px;
  background:var(--card); color:var(--text); font:inherit; margin:8px 0 16px; }
section { margin:16px 0; }
details.group > summary { cursor:pointer; padding:8px 0; border-bottom:2px solid var(--line); }
.desc, .backtest { color:var(--muted); font-size:13px; margin-right:12px; }
.backtest { color:var(--warn); }
details.game { background:var(--card); border:1px solid var(--line); border-radius:10px; margin:8px 0; }
details.game > summary { cursor:pointer; list-style:none; padding:10px 14px; display:grid; gap:4px 16px;
  grid-template-columns:minmax(220px,2.2fr) repeat(5,minmax(90px,1fr)); align-items:center; }
details.game > summary::-webkit-details-marker { display:none; }
details.game > summary.v3 { grid-template-columns:minmax(200px,2fr) repeat(7,minmax(76px,1fr)); }
tr.chosen td { font-weight:600; }
.pick { background:var(--good); color:var(--card); }
.nowrap { white-space:nowrap; }
.name { font-weight:600; }
.version { display:block; color:var(--muted); font-size:12px; font-weight:400; }
.cell small { display:block; color:var(--muted); font-size:11px; font-weight:400; }
.sweet { color:var(--good); font-weight:600; }
.tag { display:inline-block; background:var(--tag); color:var(--muted); font-size:11px; font-weight:400;
  border-radius:4px; padding:0 6px; margin-left:6px; }
.change { display:inline-block; background:var(--change); color:var(--change-text); font-size:11px;
  font-weight:600; border-radius:4px; padding:0 6px; margin-left:6px; }
.reason { color:var(--muted); grid-column:2 / -1; }
.body { padding:0 14px 12px; border-top:1px solid var(--line); }
.body ul { padding-left:20px; }
table { border-collapse:collapse; margin:8px 0; font-size:13px; }
.table-scroll { overflow-x:auto; max-width:100%; }
p.caption { color:var(--muted); font-size:13px; margin:8px 0 0; }
table.editions td, table.editions th { white-space:nowrap; }
table.editions td:first-child { white-space:normal; min-width:9em; }
button.copy { font-size:11px; padding:1px 6px; margin-left:4px; cursor:pointer; }
.tag.editions { background:transparent; border:1px solid var(--line); }
caption { text-align:left; color:var(--muted); padding-bottom:4px; white-space:nowrap; }
th, td { border-bottom:1px solid var(--line); padding:4px 12px 4px 0; text-align:left; }
.empty { color:var(--muted); }
.ns h3 { font-size:14px; margin:8px 0 0; }
details.bundle { background:var(--card); border:1px solid var(--line); border-radius:10px; margin:8px 0; }
details.bundle > summary { cursor:pointer; list-style:none; padding:10px 14px; display:grid; gap:4px 16px;
  grid-template-columns:minmax(220px,2.2fr) repeat(2,minmax(90px,1fr)); align-items:center; }
details.bundle > summary::-webkit-details-marker { display:none; }
.warn { color:var(--warn); }
p.bundle-hint { margin:6px 0; font-size:13px; }
.body { overflow-x:auto; }
@media (max-width:720px) { details.game > summary, details.game > summary.v3, details.bundle > summary {
    grid-template-columns:1fr 1fr; }
  .name, .reason { grid-column:1 / -1; } }
"""

SCRIPT = """
document.addEventListener('click', function (e) {
  var b = e.target.closest ? e.target.closest('button.copy') : null;
  if (!b) { return; }
  e.preventDefault();
  if (navigator.clipboard) {
    navigator.clipboard.writeText(b.dataset.copy).then(function () { b.textContent = '已複製'; },
                                                      function () { b.textContent = '請手動選取'; });
  } else { b.textContent = '請手動選取'; }
});
document.getElementById('filter').addEventListener('input', function (e) {
  var q = e.target.value.trim().toLowerCase();
  document.querySelectorAll('details.game').forEach(function (g) {
    g.hidden = q !== '' && g.dataset.name.indexOf(q) === -1;
  });
});
"""


def reference_notice_text(notice: dict) -> str:
    """014 FR-014a, contracts/cli.md §6: the words of the small-dataset notice; the extension shows the same text.

    A complete sampling (014 T048) says so instead of advising a run that would add nothing."""
    if notice.get("sampling") == "complete":
        return (f"參考資料集已補完：共 {notice['dataset_size']:,} 款，少於原作者驗證模型時的 {notice['threshold']:,} 款"
                "（Steam 上符合抽樣條件的遊戲不夠多），預測的依據比較少。")
    text = (f"參考資料集目前 {notice['dataset_size']:,} 款（建議至少 {notice['threshold']:,} 款），預測的依據還不完整。"
            "補完：執行 uv run sweetspot reference（約 2～3 小時，可以中斷，下次接著做），或讓每日更新慢慢累積。")
    if notice.get("broad_sample") == "disabled":
        text += f"沒有設定 STEAM_WEB_API_KEY，廣泛樣本停用，可能到不了 {notice['threshold']:,} 款。"
    return text


def render(data: dict) -> str:
    return (f'<!doctype html>\n<html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>願望清單甜蜜價報告</title><style>{CSS}</style></head><body>'
            f'{_header(data)}\n<main>{_bundles(data)}{_groups(data)}</main><script>{SCRIPT}</script>'
            f'</body></html>\n')
