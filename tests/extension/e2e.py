"""End-to-end checks of the Chrome extension (feature 011; tasks T017, T021, T022, T026, T030, T033).

uv run --with playwright python tests/extension/e2e.py            # fixture pages only, no network
uv run --with playwright python tests/extension/e2e.py --live     # plus real Steam pages (not logged in)

Runs Playwright's Chromium (branded Chrome 137+ ignores --load-extension) with a temporary COPY of extension/ in which
the local program's name is a test name and the panel's wait is 2 seconds (feature 015 tasks T021). The manifest key
gives the copy the real extension's id, and this Chromium also reads HKCU\\Software\\Google\\Chrome, so loading
extension/ itself could reach the real local program and change the real sweetspot.toml: the copy never can. Only a
fake local program (tests/extension/fake_host.py) is registered, under HKCU\\Software\\Chromium, and removed at the end.
The real extension/data/ is never touched. Offline, store.steampowered.com pages are served from
tests/extension/fixtures/ and every other request is aborted and logged. Every request started by extension code
(CDP initiator) is counted and must be 0 (SC-005). Not part of pytest: it needs a browser, and --live needs Steam.
Screenshots of --live go to specs/011-chrome-extension/prototype/out/ (ignored by git).
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
import winreg
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

os.environ.setdefault("PW_EXPERIMENTAL_SERVICE_WORKER_NETWORK_EVENTS", "1")
from playwright.sync_api import sync_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "extension"
REAL_DATA = SOURCE / "data" / "sweetspot-extension.json"
EXT = SOURCE                                      # replaced by the temporary copy in main()
DATA = EXT / "data" / "sweetspot-extension.json"
HOST_TEST = "com.sweetspot.edition.test"
HOST_PARENT = "Software\\Chromium\\NativeMessagingHosts"
PATCHES = [("const HOST_NAME = 'com.sweetspot.edition';", f"const HOST_NAME = '{HOST_TEST}';"),
           ("const WAIT_MS = 60000;", "const WAIT_MS = 2000;")]
FIX = Path(__file__).resolve().parent / "fixtures"
SHOTS = ROOT / "specs" / "011-chrome-extension" / "prototype" / "out"
STORE = "https://store.steampowered.com"
AGE = [{"name": n, "value": v, "domain": "store.steampowered.com", "path": "/"}
       for n, v in (("birthtime", "0"), ("lastagecheckage", "1-0-1990"), ("wants_mature_content", "1"))]


def stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def fixture_data(**over) -> dict:
    data = json.loads((FIX / "data.json").read_text(encoding="utf-8"))
    data["data_time"] = stamp(datetime.now(UTC) - timedelta(hours=1))
    data.update(over)
    return data


def write_data(payload: dict | str):
    DATA.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA.with_name(DATA.name + ".tmp")
    tmp.write_text(payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, DATA)


class Run:
    def __init__(self, ctx):
        self.ctx = ctx
        self.results: list[tuple[str, bool, str]] = []
        self.ext_requests: list[str] = []
        self.page_errors: list[str] = []
        self.sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
        self.ext_id = self.sw.url.split("/")[2]

    def check(self, label: str, ok: bool, detail: str = ""):
        self.results.append((label, bool(ok), detail))
        print(f"{'OK ' if ok else 'BAD'} {label}" + (f": {detail}" if detail else ""))

    def page(self):
        page = self.ctx.new_page()
        cdp = self.ctx.new_cdp_session(page)
        cdp.send("Network.enable")

        def seen(ev):
            ini = ev.get("initiator") or {}
            frames = [f.get("url", "") for f in ((ini.get("stack") or {}).get("callFrames") or [])]
            if (ini.get("url") or "").startswith("chrome-extension://") or \
                    any(u.startswith("chrome-extension://") for u in frames):
                if not ev["request"]["url"].startswith(("chrome-extension://", "data:")):   # its own files are local
                    self.ext_requests.append(ev["request"]["url"])
        cdp.on("Network.requestWillBeSent", seen)
        page.on("pageerror", lambda e: self.page_errors.append(f"{page.url}: {e}"))
        return page

    def popup(self):
        page = self.page()
        t0 = time.monotonic()
        page.goto(f"chrome-extension://{self.ext_id}/popup.html")
        page.wait_for_selector("#meta[data-state]", state="attached", timeout=5000)
        return page, (time.monotonic() - t0) * 1000

    def badge(self):
        sw = self.ctx.service_workers[0]
        return sw.evaluate("chrome.action.getBadgeText({})"), sw.evaluate("chrome.action.getBadgeBackgroundColor({})")


# --- T017: rewritten data file is read without reloading the extension (research R0.1) -------------------------

def check_reload(run: Run):
    write_data(fixture_data(as_of="2026-09-27T00:00:00Z"))
    page, ms = run.popup()
    run.check("popup reads the data file", "2026-09-27 08:00" in page.inner_text("#meta"), f"{ms:.0f} ms")
    run.check("popup shown within 1 s (SC-006)", ms < 1000, f"{ms:.0f} ms")
    page.close()
    run.check("badge = now count, green", run.badge() == ("1", [30, 125, 50, 255]), str(run.badge()))
    alarms = run.sw.evaluate("chrome.alarms.getAll()")
    run.check("one 30-minute refresh alarm", [(a["name"], a["periodInMinutes"]) for a in alarms] == [("refresh", 30)],
              str(alarms))

    write_data(fixture_data(as_of="2026-09-28T02:30:00Z"))          # the report's way: temp file + rename
    page, _ = run.popup()
    run.check("rewritten file read without reloading", "2026-09-28 10:30" in page.inner_text("#meta"))
    page.close()

    two_now = fixture_data(as_of="2026-09-29T02:30:00Z")
    two_now["games"][1]["group"] = "now"
    DATA.write_text(json.dumps(two_now, ensure_ascii=False), encoding="utf-8")      # in place, no page open
    run.ctx.service_workers[0].evaluate("sweetspotRefresh()")
    run.check("alarm handler updates the badge without any page", run.badge()[0] == "2", str(run.badge()))

    cdp = run.ctx.new_cdp_session(run.ctx.pages[0] if run.ctx.pages else run.ctx.new_page())
    cdp.send("ServiceWorker.enable")
    cdp.send("ServiceWorker.stopAllWorkers")                        # Chrome stops an idle worker after ~30 s
    time.sleep(1)
    write_data(fixture_data(as_of="2026-09-30T02:30:00Z"))
    page, _ = run.popup()
    run.check("read after the worker was stopped", "2026-09-30 10:30" in page.inner_text("#meta"))
    page.close()

    write_data('{"format": "steamsage.extension/1", "games": [')
    page, _ = run.popup()
    run.check("half-written file -> broken", page.get_attribute("#meta", "data-state") == "broken")
    page.close()
    run.check("badge ! red when unreadable", run.badge() == ("!", [161, 38, 27, 255]), str(run.badge()))
    write_data(fixture_data(format="steamsage.extension/2"))
    page, _ = run.popup()
    run.check("unknown format -> format", page.get_attribute("#meta", "data-state") == "format")
    page.close()
    DATA.unlink()
    page, _ = run.popup()
    run.check("missing file -> missing", page.get_attribute("#meta", "data-state") == "missing")
    page.close()
    write_data(fixture_data())
    blocked = run.ctx.service_workers[0].evaluate(
        "fetch('https://example.com/').then(() => 'allowed', e => 'blocked')")
    run.check("service worker cannot reach other sites (CSP)", blocked == "blocked", blocked)


# --- T021: game page panel on fixture pages (FR-012, FR-013, FR-013a) ----------------------------------------

PANEL_TEXT = "() => { const p = document.querySelector('.sweetspot-panel'); return p ? p.shadowRoot.textContent : null; }"


def taipei(stamp_: str) -> str:
    return (datetime.strptime(stamp_, "%Y-%m-%dT%H:%M:%SZ") + timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")


def open_store(page, path: str, want_panel: bool):
    page.goto(STORE + path)
    if want_panel:
        page.wait_for_selector(".sweetspot-panel", state="attached", timeout=5000)
    else:
        page.wait_for_timeout(1500)
    return page.evaluate(PANEL_TEXT)


def check_game_pages(run: Run):
    data = fixture_data()
    write_data(data)
    page = run.page()
    text = open_store(page, "/app/1903340/", True)
    run.check("panel on a game in the data", text is not None)
    run.check("one panel, right above the purchase area", page.evaluate(
        "() => document.querySelectorAll('.sweetspot-panel').length === 1 && "
        "document.querySelector('.sweetspot-panel').nextElementSibling.id === 'game_area_purchase'"))
    for part in ("現在買", "頁面現價", "NT$ 790", "甜蜜價", "NT$790 -20%", "2026 秋特（官方）", "83%",
                 "12 個月內最低", "NT$692 -30%", "另有 1 個版本", "可和 Dispatch 超英派遣中心 一起買：組合包 −10%",
                 "原因（5）", taipei(data["data_time"])):
        run.check(f"panel shows {part}", part in text)
    run.check("no stale warning on fresh data", "資料超過" not in text)

    later = fixture_data(data_time="2026-09-28T18:30:00Z", refresh_note=None)
    write_data(later)                                                 # rewritten, no reload of the extension
    text = open_store(page, "/app/1903340/", True)
    run.check("reloaded page reads the rewritten file", "2026-09-29 02:30" in text)
    write_data(data)

    text = open_store(page, "/app/1091500/", True)
    run.check("chosen edition: bundle price on the page", "NT$ 2,206" in text and "（使用者指定）" in text)
    text = open_store(page, "/app/1903340/?usd", True)
    run.check("non-TWD page price is not shown", "頁面不是新台幣，不並列" in text and "$29.99" not in text)
    text = open_store(page, "/app/9500013/", True)
    run.check("unpredictable game shows only the reason", "尚未發行（預定 2026-11-20）" in text and "甜蜜價" not in text)
    text = open_store(page, "/app/1903340/?owned", True)
    collapsed = page.evaluate("() => { const b = document.querySelector('.sweetspot-panel').shadowRoot.querySelector('.body');"
                              " return b.hidden; }")
    run.check("owned game: one collapsed line", "你已擁有這款遊戲；以下是購買前" in text and collapsed)
    page.evaluate("() => document.querySelector('.sweetspot-panel').shadowRoot.querySelector('button').click()")
    run.check("owned game: expands on click", page.evaluate(
        "() => !document.querySelector('.sweetspot-panel').shadowRoot.querySelector('.body').hidden"))
    run.check("no purchase area: no panel", open_store(page, "/app/1903340/?nopurchase", False) is None)
    run.check("age check page: no panel", open_store(page, "/agecheck/app/1903340/", False) is None)
    open_store(page, "/app/730/", False)
    same = page.evaluate("""(fixture) => {
        const doc = new DOMParser().parseFromString(fixture, 'text/html');
        return document.body.innerHTML.trim() === doc.body.innerHTML.trim(); }""",
                         (FIX / "game_twd.html").read_text(encoding="utf-8"))
    run.check("game not in the data: page unchanged", same)
    page.close()


# --- T022: real game pages (--live; SC-002, SC-006) -------------------------------------------------------------

LIVE_APPS = [239140, 359870, 812140, 881020, 1091500, 1113000, 1402110, 1903340, 1868140, 2258500, 2384580,
             2399220, 1593500, 3280350, 9500003, 9500013]


def money(v):
    return "未知" if v is None else f"NT${v:,}"


def pct(p):
    return "—" if p is None else f"{int(p * 100 + 0.5)}%"


def check_live_games(run: Run, data: dict):
    by_id = {g["app_id"]: g for g in data["games"]}
    page = run.page()
    for app in LIVE_APPS:
        g = by_id.get(app)
        if g is None:
            run.check(f"{app} in the data file", False)
            continue
        page.goto(f"{STORE}/app/{app}/", wait_until="domcontentloaded")
        t0 = time.monotonic()
        try:
            page.wait_for_selector(".sweetspot-panel", state="attached", timeout=8000)
        except Exception:  # noqa: BLE001
            run.check(f"{app} panel", False, page.url)
            continue
        ms = (time.monotonic() - t0) * 1000
        text = page.evaluate(PANEL_TEXT)
        above = page.evaluate("() => document.querySelector('.sweetspot-panel').nextElementSibling.id === 'game_area_purchase'")
        want = [S_GROUP[g["group"]]]
        if g["group"] == "na":
            want.append(g["status_reason"])
        else:
            want += [f"{money(g['sweet_twd'])} -{g['sweet_pct']}%", g["point"]["label"], pct(g["probability"]),
                     data["lowest_label"], f"{money(g['p_min_twd'])} -{g['p_min_pct']}%"]
            want += [h["text"] for h in g["bundle_hints"]]
        missing = [w for w in want if w not in text]
        live_ok = True
        if g["group"] != "na" and g["price_twd"] is not None:
            blocks = page.evaluate("""(opt) => {
                const key = opt.kind === 'bundle' ? 'bundleid' : 'subid';
                const input = document.querySelector(`#game_area_purchase form input[name="${key}"][value="${opt.id}"]`);
                const b = input && input.closest('.game_area_purchase_game');
                const priced = b && b.querySelector('[data-price-final]');
                return priced ? Number(priced.getAttribute('data-price-final')) : null; }""", g["option"])
            live_ok = blocks == g["price_twd"] * 100
        run.check(f"{app} {g['group']}: panel above purchase area, values = data file, page price = record",
                  above and not missing and live_ok, f"{ms:.0f} ms after DCL" + (f"; missing {missing}" if missing else ""))
        run.check(f"{app} panel within 1 s of the page content (SC-006)", ms < 1000, f"{ms:.0f} ms")
        if app in (1903340, 1091500, 9500003):
            page.locator(".sweetspot-panel").screenshot(path=str(SHOTS / f"e2e-panel-{app}.png"))
            page.screenshot(path=str(SHOTS / f"e2e-page-{app}.png"))
    page.close()


S_GROUP = {"now": "現在買", "soon": "即將到價", "wait": "繼續等", "low": "低信心", "na": "無法預測"}


# --- T026: popup (FR-009 to FR-011, SC-001) ----------------------------------------------------------------------

POPUP_STATE = """() => ({
    groups: [...document.querySelectorAll('details.group')].map(d => ({key: d.dataset.group, title: d.querySelector('summary').textContent,
        open: d.open, rows: d.querySelectorAll('.row').length, links: [...d.querySelectorAll('.row a')].map(a => a.href)})),
    bundles: [...document.querySelectorAll('.row.bundle a')].map(a => a.href),
    warn: [...document.querySelectorAll('.warn')].map(w => w.textContent),
    error: (document.querySelector('.error') || {}).textContent || null,
    text: document.body.innerText })"""
NAMES = {"now": "現在買", "soon": "即將到價", "wait": "繼續等", "low": "低信心", "na": "無法預測"}


def popup_matches(run: Run, data: dict, label: str):
    page, ms = run.popup()
    state = page.evaluate(POPUP_STATE)
    titles = [(g["key"], g["title"], g["rows"]) for g in state["groups"]]
    want = [(k, f"{NAMES[k]}（{data['summary'][k]}）", data["summary"][k]) for k in NAMES]
    run.check(f"{label}: group titles and rows = summary (SC-001)", titles == want, str(titles))
    links = [u for g in state["groups"] for u in g["links"]]
    run.check(f"{label}: every game links to its store page",
              links == [f"{STORE}/app/{g['app_id']}/" for k in NAMES for g in data["games"] if g["group"] == k])
    run.check(f"{label}: bundles section", state["bundles"] == [f"{STORE}/bundle/{b['id']}/" for b in data["bundles"]])
    run.check(f"{label}: now and soon open, others closed",
              [g["open"] for g in state["groups"]] == [True, True, False, False, False])
    run.check(f"{label}: popup within 1 s (SC-006)", ms < 1000, f"{ms:.0f} ms")
    now = sum(1 for g in data["games"] if g["group"] == "now")
    run.check(f"{label}: badge = now count", run.badge()[0] == (str(now) if now else ""), str(run.badge()))
    return page, state


def check_popup(run: Run):
    data = fixture_data()
    write_data(data)
    page, state = popup_matches(run, data, "popup")
    run.check("popup shows the update hint and no warning", "買完遊戲後可執行 更新資料.cmd 立即更新" in state["text"]
              and not state["warn"])
    page.close()
    none = fixture_data()
    none["games"] = [g for g in none["games"] if g["group"] != "now"]
    none["summary"]["now"] = 0
    write_data(none)
    page, _ = popup_matches(run, none, "no buy-now game")
    page.close()
    for payload, message in (('{"format": "steamsage.extension/1", "games": [', "資料檔損壞或正在寫入，請稍後再開"),
                             (fixture_data(format="steamsage.extension/2"), "資料格式不認得（需要 steamsage.extension/1）"),
                             (None, "還沒有資料：請先執行 更新資料.cmd")):
        if payload is None:
            DATA.unlink()
        else:
            write_data(payload)
        page, _ = run.popup()
        state = page.evaluate(POPUP_STATE)
        run.check(f"popup explains: {message}", (state["error"] or "").startswith(message) and not state["groups"])
        page.close()
    write_data(fixture_data())


def check_live_popup(run: Run, data: dict):
    page, _ = popup_matches(run, data, "popup (real data)")
    page.set_viewport_size({"width": 400, "height": 600})
    page.screenshot(path=str(SHOTS / "e2e-popup.png"))
    page.close()


# --- T030: wishlist lines (FR-014 to FR-016, SC-003) -------------------------------------------------------------

ROWS = """() => [...document.querySelectorAll('[data-index]')].map(r => {
    const a = r.querySelector('a[href*="/app/"]'); const id = a && Number((a.href.match(/\\/app\\/(\\d+)/) || [])[1]);
    const lines = [...r.querySelectorAll('.sweetspot-line')];
    const b = r.getBoundingClientRect();
    return {index: Number(r.dataset.index), id, lines: lines.length, right: lines.filter(l => Number(l.dataset.app) === id).length,
            inMid: lines.every(l => getComputedStyle(l.parentElement).gridRowStart === 'mid'),
            text: lines.map(l => [...l.shadowRoot.childNodes].filter(n => n.nodeName !== 'STYLE').map(n => n.textContent).join('')).join('|'), title: lines.map(l => l.title).join('|'),
            height: Math.round(b.height)};
})"""


def wait_lines(page, want: dict[int, int], timeout_ms=1000) -> tuple[bool, list, float]:
    """Poll until every row with an id in `want` has that many right lines (and no row has more than one)."""
    t0 = time.monotonic()
    while True:
        rows = page.evaluate(ROWS)
        ok = all(r["right"] == want.get(r["id"], 0) and r["lines"] <= 1 for r in rows if r["id"])
        ms = (time.monotonic() - t0) * 1000
        if ok or ms > timeout_ms:
            return ok, rows, ms
        page.wait_for_timeout(50)


def check_wishlist(run: Run):
    data = fixture_data()
    write_data(data)
    by_id = {g["app_id"]: g for g in data["games"]}
    page = run.page()
    page.goto(f"{STORE}/wishlist/profiles/fixture/")
    ok, rows, ms = wait_lines(page, {1903340: 1, 1091500: 1}, 3000)
    run.check("wishlist: one line per game in the data, none for others", ok, str([(r["id"], r["lines"]) for r in rows]))
    run.check("wishlist: lines sit in the grid area under the name", all(r["inMid"] for r in rows))
    first = next(r for r in rows if r["id"] == 1903340)
    run.check("wishlist: line text", first["text"] == "現在買甜蜜價 NT$790 -20% · 2026 秋特 · 到價機率 83% · 12 個月內最低 NT$692 -30%組合包", first["text"])
    g = by_id[1903340]
    probability = (f"到 {g['point']['label']}為止，季節特賣打到 -{g['sweet_pct']}%（{money(g['sweet_twd'])}）以上的機率；"
                   "跟現價無關")                                   # 2026-10-18: what 到價機率 forecasts
    run.check("wishlist: hover shows what 到價機率 means, then the first three reasons",
              first["title"] == "\n".join([probability, *g["reasons"][:3]]), first["title"])
    edition = next(r for r in rows if r["id"] == 1091500)          # the fixture's user-chosen edition (2026-10-14)
    run.check("wishlist: a chosen edition is tagged, its name first in the tooltip",
              edition["text"].startswith("繼續等指定版本甜蜜價") and edition["title"].startswith(
                  "追蹤 《電馭叛客 2077：終極版》（使用者指定），不是這一列顯示的版本\n"), edition["text"])
    run.check("wishlist: the Steam default is not tagged", "指定版本" not in first["text"])
    popup, _ = run.popup()
    tags = popup.evaluate("""() => [...document.querySelectorAll('.row .edition')].map(e =>
        ({name: e.parentElement.querySelector('a').textContent, text: e.textContent, title: e.title}))""")
    run.check("popup: only the chosen edition is tagged, the tooltip says whose prices they are",
              [(t["name"], t["text"]) for t in tags] == [("Cyberpunk 2077", "指定版本")]
              and tags[0]["title"].startswith("追蹤 《電馭叛客 2077：終極版》（使用者指定）：現價與甜蜜價都是這個版本的價格"), str(tags))
    popup.close()
    page.evaluate("""() => { const row = document.querySelector('[data-index="0"]');
        row.querySelectorAll('a[href*="/app/"]').forEach(a => { a.href = a.href.replace('/app/1903340/', '/app/1091500/'); });
        row.querySelector('.P-zVPa2bdmQ- a').textContent = 'Cyberpunk 2077'; }""")
    ok, rows, ms = wait_lines(page, {1903340: 1, 1091500: 1})
    run.check("wishlist: a reused row gets the new game's line within 1 s (FR-015)", ok, f"{ms:.0f} ms")
    page.evaluate("""() => { const row = document.querySelector('[data-index="0"]');
        row.querySelectorAll('a[href*="/app/"]').forEach(a => { a.href = a.href.replace('/app/1091500/', '/app/730/'); }); }""")
    ok, rows, ms = wait_lines(page, {1091500: 1})
    run.check("wishlist: a row reused for a game not in the data loses its line", ok, f"{ms:.0f} ms")
    page.evaluate("""async () => { const list = document.getElementById('list');
        for (let i = 0; i < 50; i++) { const d = document.createElement('div'); list.append(d);
            await new Promise(r => requestAnimationFrame(r)); d.remove(); } }""")
    ok, rows, _ = wait_lines(page, {1091500: 1})
    run.check("wishlist: 50 page changes, still at most one line per row", ok)
    page.goto(f"{STORE}/wishlist/profiles/restyled/")
    page.wait_for_timeout(1500)
    run.check("restyled wishlist: no line, page unchanged (FR-016)", page.locator(".sweetspot-line").count() == 0)
    errors = [e for e in run.page_errors if "/wishlist/" in e]
    run.check("wishlist: no page errors", not errors, "; ".join(errors[:3]))
    page.close()


# --- T033: stale data and update failures in all three places (FR-007) --------------------------------------------

def check_stale(run: Run):
    old = fixture_data(data_time=stamp(datetime.now(UTC) - timedelta(hours=27)), refresh_note="本次資料更新失敗，使用既有資料")
    write_data(old)
    page, _ = run.popup()
    state = page.evaluate(POPUP_STATE)
    page.close()
    run.check("stale: popup warns and shows the update failure",
              state["warn"] == ["資料超過 26 小時，請先執行更新", "本次資料更新失敗，使用既有資料"], str(state["warn"]))
    run.check("stale: badge turns orange", run.badge() == ("1", [176, 96, 0, 255]), str(run.badge()))
    page = run.page()
    text = open_store(page, "/app/1903340/", True)
    run.check("stale: panel warns and shows the update failure",
              "資料超過 26 小時，請先執行更新" in text and "本次資料更新失敗，使用既有資料" in text)
    page.goto(f"{STORE}/wishlist/profiles/fixture/")
    ok, rows, _ = wait_lines(page, {1903340: 1, 1091500: 1}, 3000)
    first = next(r for r in rows if r["id"] == 1903340)
    run.check("stale: wishlist line is marked and its tooltip starts with the update failure",
              ok and first["text"].startswith("資料過舊 ·") and first["title"].startswith("本次資料更新失敗，使用既有資料"),
              first["text"])
    write_data(fixture_data())
    page.reload()
    ok, rows, _ = wait_lines(page, {1903340: 1, 1091500: 1}, 3000)
    run.check("fresh again: no stale mark", ok and not any(r["text"].startswith("資料過舊") for r in rows))
    page.close()


def own_wishlist_url() -> str:
    """--live only: the real wishlist page of the owner's own settings file (014: no SteamID in this file)."""
    sys.path.insert(0, str(ROOT / "src"))
    from sweetspot.config import load_config

    return load_config(ROOT / "sweetspot.toml")[0].wishlist_url


def scroll_wishlist(page, by_id, width):
    """Scroll the inner list with the mouse wheel (the document does not scroll; research R0.2)."""
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(own_wishlist_url(), wait_until="domcontentloaded")
    page.wait_for_selector("[data-index] a[href*='/app/']", timeout=30000)
    page.wait_for_timeout(1500)                       # the list scrolls only after it has settled (prototype P4)
    seen, late, dup, heights, worst, idle, steps = {}, [], set(), {}, 0.0, 0, 0
    while idle < 6 and steps < 300:
        steps += 1
        ok, rows, ms = wait_lines(page, {a: 1 for a in by_id})
        worst = max(worst, ms)
        before = len(seen)
        for r in rows:
            if not r["id"]:
                continue
            if r["lines"] > 1:
                dup.add(r["id"])
            if r["right"] != (1 if r["id"] in by_id else 0):
                late.append(r["id"])
            seen.setdefault(r["id"], r)
            heights[r["index"]] = r["height"]
        idle = idle + 1 if len(seen) == before else 0
        page.mouse.move(width // 2, 500)
        page.mouse.wheel(0, 350)
        page.wait_for_timeout(1000)
    return seen, late, dup, heights, worst


def check_live_wishlist(run: Run, data: dict):
    by_id = {g["app_id"]: g for g in data["games"]}
    page = run.page()
    seen, late, dup, heights, worst = scroll_wishlist(page, by_id, 1280)
    run.check(f"live wishlist: scrolled through the list ({len(seen)} rows; 59 when not logged in)", len(seen) >= 50)
    run.check(f"live wishlist: {len(seen)} rows, each game in the data has exactly one line within 1 s",
              not late and not dup, f"late {late[:5]}, duplicates {sorted(dup)[:5]}, slowest {worst:.0f} ms")
    run.check("live wishlist: every row seen is a game in the data", all(a in by_id for a in seen),
              str([a for a in seen if a not in by_id][:5]))
    run.check("live wishlist: rows keep their height (174 px)", set(heights.values()) <= {174},
              str(sorted(set(heights.values()))))
    print(f"    games in the data not listed (not logged in): {sorted(set(by_id) - set(seen))}")
    page.mouse.move(640, 500)
    for _ in range(40):
        page.mouse.wheel(0, -2000)
    page.wait_for_timeout(1500)
    page.screenshot(path=str(SHOTS / "e2e-wishlist-1280.png"))
    page.set_viewport_size({"width": 700, "height": 900})
    page.wait_for_timeout(1500)
    rows = page.evaluate(ROWS)
    run.check("live wishlist at 700 px: lines present, row height unchanged",
              any(r["lines"] for r in rows) and {r["height"] for r in rows if r["id"]} <= {174},
              str(sorted({r["height"] for r in rows})))
    page.screenshot(path=str(SHOTS / "e2e-wishlist-700.png"))
    page.close()


# --- runner -------------------------------------------------------------------------------------------------

# --- feature 012 (plan D1; FR-021): sale-calendar notices in the popup ---------------------------------------------

def check_calendar_notices(run: Run):
    notice = ("官方特賣頁面的 2026 冬特是 12/18–1/4，data/steam_sales.toml 是 12/17–1/4；預測沿用檔案的日期。"
              "確認後執行 sweetspot calendar --sync --write")
    write_data(fixture_data(calendar_notices=[notice]))
    page, _ = run.popup()
    state = page.evaluate(POPUP_STATE)
    page.close()
    run.check("calendar notice: popup shows it under the header", state["warn"] == [notice], str(state["warn"]))
    write_data(fixture_data())


# --- 015 T021: the version section with a fake local program (contracts/extension-ui.md) ------------------------

def make_copy(work: Path) -> Path:
    """extension/ without data/, with the test host name and a 2-second wait (the only differences)."""
    copy = work / "extension"
    shutil.copytree(SOURCE, copy, ignore=shutil.ignore_patterns("data"))
    lib = copy / "lib.js"
    text = lib.read_text(encoding="utf-8")
    for old, new in PATCHES:
        if text.count(old) != 1:
            sys.exit(f"e2e: cannot patch lib.js ({old!r} found {text.count(old)} times)")
        text = text.replace(old, new)
    lib.write_text(text, encoding="utf-8")
    if "com.sweetspot.edition'" in "".join(p.read_text(encoding="utf-8") for p in copy.glob("*.js")):
        sys.exit("e2e: the copy still names the real local program")
    return copy


@contextmanager
def fake_host(work: Path, ext_id: str):
    """Register tests/extension/fake_host.py as HOST_TEST for this user; removed (with an empty parent key this
    created) on the way out. Yields its state folder."""
    state = work / "fake-host"
    state.mkdir(exist_ok=True)
    (state / "plan.json").write_text("{}", encoding="utf-8")
    (state / "requests.jsonl").write_text("", encoding="utf-8")
    bat = work / "fake-host.bat"
    bat.write_bytes(f'@"{sys.executable}" "{Path(__file__).with_name("fake_host.py")}" "{state}" %*\r\n'.encode("mbcs"))
    manifest = work / "fake-host.json"
    manifest.write_text(json.dumps({"name": HOST_TEST, "description": "SweetSpot e2e fake", "path": str(bat),
                                    "type": "stdio", "allowed_origins": [f"chrome-extension://{ext_id}/"]}),
                        encoding="utf-8")
    try:
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, HOST_PARENT).Close()
        created_parent = False
    except FileNotFoundError:
        created_parent = True
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"{HOST_PARENT}\\{HOST_TEST}") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, str(manifest))
    try:
        yield state
    finally:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, f"{HOST_PARENT}\\{HOST_TEST}")
        if created_parent:
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, HOST_PARENT)
            except OSError:
                pass


def host_left() -> bool:
    try:
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"{HOST_PARENT}\\{HOST_TEST}").Close()
        return True
    except FileNotFoundError:
        return False


def plan(state: Path, **commands):
    (state / "plan.json").write_text(json.dumps(commands, ensure_ascii=False), encoding="utf-8")


def requests_seen(state: Path) -> list[dict]:
    return [json.loads(line)["request"] for line in (state / "requests.jsonl").read_text(encoding="utf-8").splitlines()]


SHADOW = "document.querySelector('.sweetspot-panel').shadowRoot"
VERSIONS = f"() => {{ const d = {SHADOW}.querySelector('details.versions'); return d ? {{open: d.open, " \
           f"text: d.textContent, buttons: [...d.querySelectorAll('button')].map(b => [b.dataset.ref, b.textContent, b.disabled])}} : null; }}"
SYNTHETIC = {
    "element.click()": "b.click()",
    "dispatchEvent(MouseEvent)": "b.dispatchEvent(new MouseEvent('click', {bubbles: true, composed: true}))",
    "dispatchEvent(PointerEvent)": "b.dispatchEvent(new PointerEvent('click', {bubbles: true, composed: true}))",
    "HTMLElement.prototype.click.call": "HTMLElement.prototype.click.call(b)",
    "keydown Enter + keyup": "b.focus(); for (const t of ['keydown', 'keypress', 'keyup']) "
                             "b.dispatchEvent(new KeyboardEvent(t, {key: 'Enter', bubbles: true, composed: true}))",
    "label forwarding": "const l = document.createElement('label'); l.htmlFor = 'x'; document.body.append(l); l.click()",
}


def versions_state(page):
    return page.evaluate(VERSIONS)


def wait_versions(page, predicate, timeout=8.0):
    end = time.monotonic() + timeout
    state = versions_state(page)
    while time.monotonic() < end:
        state = versions_state(page)
        if state and predicate(state):
            return state, True
        page.wait_for_timeout(100)
    return state, False


def expand_versions(page):
    page.locator(".sweetspot-panel details.versions > summary").click()


def deluxe_data() -> dict:
    """What the report would write after choosing Clair Obscur's Deluxe edition."""
    data = fixture_data()
    game = next(g for g in data["games"] if g["app_id"] == 1903340)
    base, deluxe, broken = game["versions"]
    game["option"] = {"kind": "sub", "id": 777001, "name": deluxe["name"], "user": True}
    game["sweet_twd"], game["sweet_pct"] = 1011, 15
    game["versions"] = [{**deluxe, "tracked": True, "action": None, "manual": None},
                        {**base, "tracked": False, "action": "reset",
                         "manual": "刪掉設定檔 [purchase_options] 中 1903340 那一行"}, broken]
    return data


CODES = f"() => [...{SHADOW}.querySelectorAll('.vcode')].map(c => [c.textContent, getComputedStyle(c).userSelect])"
MANUAL = f"() => [...{SHADOW}.querySelectorAll('.vmanual')].map(c => [c.textContent, getComputedStyle(c).userSelect])"
# per purchase box: null, or [ref, text, disabled (null when it is not a button)]
SHORTCUTS = ("() => [...document.querySelectorAll('#game_area_purchase .game_area_purchase_game')].map(b => {"
             " const s = b.querySelector('.sweetspot-shortcut'); if (!s) return null;"
             " const n = s.shadowRoot.querySelector('button, span');"
             " return [s.dataset.ref, n.textContent, n.tagName === 'BUTTON' ? n.disabled : null]; })")
SHORTCUT_BUTTON = "document.querySelector('.sweetspot-shortcut[data-ref=\"{ref}\"]').shadowRoot.querySelector('button')"


def shortcuts(page):
    return page.evaluate(SHORTCUTS)


def wait_shortcuts(page, predicate, timeout=8.0):
    end = time.monotonic() + timeout
    state = shortcuts(page)
    while time.monotonic() < end:
        state = shortcuts(page)
        if predicate(state):
            return state, True
        page.wait_for_timeout(100)
    return state, False


def default_data() -> dict:
    """What the report would write after Cyberpunk 2077 went back to the Steam default."""
    data = fixture_data()
    game = next(g for g in data["games"] if g["app_id"] == 1091500)
    ultimate, base = game["versions"]
    game["option"] = {"kind": "sub", "id": 367653, "name": base["name"], "user": False}
    game["versions"] = [{**base, "tracked": True, "action": None, "manual": None},
                        {**ultimate, "tracked": False, "action": "choose", "manual": '1091500 = "bundle/32470"'}]
    return data


def check_outdated_data(run: Run):
    """2026-10-14: a data file written before 015 (no `versions`) makes the panel say so instead of hiding the
    version section without a word."""
    old = fixture_data()
    for g in old["games"]:
        del g["versions"]
    write_data(old)
    page = run.page()
    text = open_store(page, "/app/1091500/", True)
    run.check("old data file: the panel says to regenerate it, no version section",
              "資料檔是舊版，部分功能不會顯示：請執行 更新資料.cmd 重新產生" in text and versions_state(page) is None)
    write_data(fixture_data())
    text = open_store(page, "/app/1091500/", True)
    run.check("current data file: no such warning", "資料檔是舊版" not in text and versions_state(page) is not None)
    page.close()


def check_no_host(run: Run):
    """015 T024 (US2): nothing registered under the copy's name. The 011 checks before this one ran the same way."""
    write_data(fixture_data())
    run.check("no local program registered for the copy", not host_left())
    page = run.page()
    open_store(page, "/app/1903340/", True)
    expand_versions(page)
    state_, ok = wait_versions(page, lambda s: "uv run sweetspot host install" in s["text"])
    guide = page.evaluate(f"() => {SHADOW}.querySelector('.vguide')?.textContent")
    run.check("not installed: the section says where and how to install, no buttons",
              ok and state_["buttons"] == [] and guide and guide.startswith(
                  "要在這裡直接指定版本：在 D:\\Tools\\SweetSpot 開啟命令列，執行 uv run sweetspot host install"), str(guide))
    run.check("not installed: a version to choose names the settings file in full and what to do",
              "手動指定：用記事本打開 D:\\Tools\\SweetSpot\\sweetspot.toml，" in state_["text"]
              and "存檔後執行 更新資料.cmd" in state_["text"])
    run.check("not installed: the folder, the command and the file can be selected and copied",
              page.evaluate(CODES) == [["D:\\Tools\\SweetSpot", "all"], ["uv run sweetspot host install", "all"],
                                       ["D:\\Tools\\SweetSpot\\sweetspot.toml", "all"]], str(page.evaluate(CODES)))
    manual = page.evaluate(MANUAL)
    run.check("not installed: the line to write by hand, selectable", manual == [['1903340 = "sub/777001"', "all"]],
              str(manual))
    run.check("not installed: a refused version still gives its reason", ok and "沒有 ITAD 的價格歷史，不能指定" in state_["text"])
    run.check("not installed: the rest of the panel as before", "甜蜜價" in page.evaluate(PANEL_TEXT))
    open_store(page, "/app/1091500/?editions", True)
    page.locator(".sweetspot-shortcut[data-ref='sub/367653'] button").click()
    got, ok = wait_shortcuts(page, lambda s: s[0] and s[0][1] == "需要安裝本機程式（見 SweetSpot 面板）")
    section = versions_state(page)
    run.check("not installed: a shortcut says so and opens the panel's section (US4)",
              ok and section["open"] and "要在這裡直接指定版本：" in section["text"]
              and got[1] == ["bundle/32470", "SweetSpot：追蹤中", None], str(got))
    run.check("not installed: going back to the default says which line to delete, nothing to copy",
              "手動改回：用記事本打開 D:\\Tools\\SweetSpot\\sweetspot.toml，在 [purchase_options] 下面找到以「1091500 =」開頭的那一行"
              in section["text"] and page.evaluate(MANUAL) == [], str(page.evaluate(MANUAL)))
    write_data(fixture_data(config_path=None))                         # a data file from before config_path
    open_store(page, "/app/1903340/", True)
    expand_versions(page)
    state_, ok = wait_versions(page, lambda s: "uv run sweetspot host install" in s["text"])
    run.check("no path in the data file: the folder in words",
              ok and "在 SweetSpot 資料夾（extension 資料夾的上一層）開啟命令列" in state_["text"]
              and "用記事本打開 SweetSpot 資料夾的 sweetspot.toml" in state_["text"])
    write_data(fixture_data())
    page.goto(f"{STORE}/wishlist/profiles/fixture/")
    ok, _, _ = wait_lines(page, {1903340: 1, 1091500: 1}, 3000)
    buttons = page.evaluate("() => [...document.querySelectorAll('.sweetspot-line')]"
                            ".map(h => h.shadowRoot.querySelectorAll('button, details').length)")
    run.check("wishlist lines have no buttons (FR-005)", ok and buttons and not any(buttons), str(buttons))
    page.close()
    popup, _ = run.popup()
    run.check("popup has no buttons (FR-005)", popup.locator("button").count() == 0
              and "追蹤這個版本" not in popup.inner_text("body"))
    popup.close()


def check_editions(run: Run, work: Path):
    write_data(fixture_data())
    with fake_host(work, run.ext_id) as state:
        plan(state, status={"reply": {"v": 1, "ok": True, "cmd": "status", "app": 1903340, "choice": None,
                                      "config_ok": True, "host": "fake"}})
        answer = run.ctx.service_workers[0].evaluate(
            "new Promise(r => chrome.runtime.sendNativeMessage(SweetSpot.HOST_NAME, {v: 1, cmd: 'status', app: 1903340}, r))")
        if not (answer and answer.get("fake") is True):
            sys.exit(f"e2e: something other than the fake local program answered: {answer!r}")
        run.check("only the fake local program answers the copy", True, HOST_TEST)
        (state / "requests.jsonl").write_text("", encoding="utf-8")

        page = run.page()
        open_store(page, "/app/1903340/", True)
        first = versions_state(page)
        run.check("version section, collapsed, with its count", first and first["open"] is False and "版本（3）" in first["text"],
                  str(first and first["text"][:40]))
        page.wait_for_timeout(1000)
        run.check("nothing asks the local program before the section is opened (FR-023a)", requests_seen(state) == [])
        expand_versions(page)
        state_, ok = wait_versions(page, lambda s: any(b[0] == "sub/777001" for b in s["buttons"]))
        run.check("opening the section asks once for the status", ok and [r["cmd"] for r in requests_seen(state)] == ["status"],
                  str(requests_seen(state)))
        run.check("a choosable version has a button, the tracked one says so, a refused one gives its reason",
                  ok and "追蹤中（Steam 預設）" in state_["text"] and "沒有 ITAD 的價格歷史，不能指定" in state_["text"]
                  and [b[0] for b in state_["buttons"]] == ["sub/777001"], str(state_ and state_["buttons"]))

        button = f"{SHADOW}.querySelector('button[data-ref=\"sub/777001\"]')"
        for label, code in SYNTHETIC.items():
            page.evaluate(f"() => {{ const b = {button}; {{ {code}; }} {{ {code}; }} }}")
            text = page.evaluate(f"() => {button}.textContent")
            run.check(f"page script {label}, twice, sends nothing (FR-006a)",
                      text == "追蹤這個版本" and [r["cmd"] for r in requests_seen(state)] == ["status"], text)

        locator = page.locator(".sweetspot-panel button[data-ref='sub/777001']")
        locator.click()
        text = page.evaluate(f"() => {button}.textContent")
        run.check("one click asks to confirm", text == "確定追蹤《Clair Obscur: Expedition 33 Deluxe》？再按一次", text)
        page.wait_for_timeout(5300)
        text = page.evaluate(f"() => {button}.textContent")
        run.check("five seconds later it is back and nothing was sent",
                  text == "追蹤這個版本" and [r["cmd"] for r in requests_seen(state)] == ["status"], text)

        nxt = work / "next.json"
        nxt.write_text(json.dumps(deluxe_data(), ensure_ascii=False), encoding="utf-8")
        plan(state, choose={"delay": 1.5, "data": {"from": str(nxt), "to": str(DATA)},
                            "reply": {"v": 1, "ok": True, "cmd": "choose", "app": 1903340, "option": "sub/777001",
                                      "changed": True, "seconds": 1.5, "partial": False}})
        locator.click()
        locator.click()
        state_, ok = wait_versions(page, lambda s: "正在指定《Clair Obscur: Expedition 33 Deluxe》並重新產生報告…" in s["text"], 2)
        run.check("confirmed: progress shown and the buttons are off (FR-006b)",
                  ok and all(b[2] for b in state_["buttons"]), str(state_ and state_["buttons"]))
        state_, ok = wait_versions(page, lambda s: "已改為追蹤《Clair Obscur: Expedition 33 Deluxe》" in s["text"])
        sent = requests_seen(state)[-1]
        run.check("the request names the game and the version", sent == {"v": 1, "cmd": "choose", "app": 1903340,
                                                                        "option": "sub/777001"}, str(sent))
        panel = page.evaluate(PANEL_TEXT)
        run.check("the panel is redrawn with the new report's numbers, no reload (FR-011)",
                  ok and "NT$1,011 -15%" in panel and "追蹤中（使用者指定）" in state_["text"]
                  and [b[0] for b in state_["buttons"]] == ["sub/685434"], str(state_ and state_["buttons"]))
        write_data(fixture_data())

        plan(state, status={"reply": {"v": 1, "ok": True, "cmd": "status", "app": 1091500, "choice": "bundle/32470",
                                      "config_ok": True, "host": "fake"}},
             reset={"reply": {"v": 1, "ok": False, "code": "busy-update", "message": "背景更新進行中，請稍後再試"}})
        open_store(page, "/app/1091500/", True)
        expand_versions(page)
        wait_versions(page, lambda s: s["buttons"])
        gap = page.evaluate(f"""() => {{ const row = {SHADOW}.querySelector('.vrow[data-ref="sub/367653"]');
            const label = row.querySelector('.vlabel').getBoundingClientRect();
            const button = row.querySelector('button').getBoundingClientRect();
            return [row.querySelector('.vlabel').textContent, button.left - label.right, button.top - label.top]; }}""")
        run.check("the label and the button are apart, not run together (2026-10-15)",
                  gap[0] == "Steam 預設" and (gap[1] >= 6 or gap[2] > 4), str(gap))
        reset = page.locator(".sweetspot-panel button[data-ref='sub/367653']")
        reset.click()
        text = page.evaluate(f"() => {SHADOW}.querySelector('button[data-ref=\"sub/367653\"]').textContent")
        run.check("reset asks to confirm too", text == "確定改回 Steam 預設？再按一次", text)
        reset.click()
        state_, ok = wait_versions(page, lambda s: "背景更新進行中，請稍後再試" in s["text"])
        run.check("a refusal is shown and the buttons come back", ok and not any(b[2] for b in state_["buttons"]))

        plan(state, status={"reply": {"v": 1, "ok": True, "cmd": "status", "app": 1091500, "choice": "bundle/32470",
                                      "config_ok": True, "host": "fake"}},
             reset={"delay": 4, "reply": {"v": 1, "ok": True, "cmd": "reset", "app": 1091500, "changed": False}})
        open_store(page, "/app/1091500/", True)
        expand_versions(page)
        wait_versions(page, lambda s: s["buttons"])
        reset.click()
        reset.click()
        state_, ok = wait_versions(page, lambda s: "報告仍在產生，完成後重新整理頁面即可看到" in s["text"], 4)
        run.check("no answer within the wait: says so, buttons stay off (FR-010)",
                  ok and all(b[2] for b in state_["buttons"]), str(state_ and state_["text"][-40:]))
        page.wait_for_timeout(2500)

        open_store(page, "/app/1903340/?owned", True)
        hidden = page.evaluate(f"() => {SHADOW}.querySelector('.body').hidden && !!{SHADOW}.querySelector('details.versions')")
        page.locator(".sweetspot-panel .owned button").click()
        expand_versions(page)
        _, ok = wait_versions(page, lambda s: any(b[0] == "sub/777001" for b in s["buttons"]))
        run.check("owned game: the section folds with the panel and works once opened", hidden and ok)
        page.close()
    run.check("the fake local program is unregistered", not host_left())


def check_shortcuts(run: Run, work: Path):
    """015 T032 (US4): Steam's own purchase boxes, with the fake local program."""
    status = {"reply": {"v": 1, "ok": True, "cmd": "status", "app": 1091500, "choice": None, "config_ok": True,
                        "host": "fake"}}
    chosen = [["sub/367653", "SweetSpot：改回 Steam 預設", False], ["bundle/32470", "SweetSpot：追蹤中", None], None]
    write_data(fixture_data())
    with fake_host(work, run.ext_id) as state:
        plan(state, status=status)
        page = run.page()
        open_store(page, "/app/1091500/?editions", True)
        got = shortcuts(page)
        run.check("shortcuts: reset on the base game's box, tracked on the Ultimate box, none on the soundtrack",
                  got == chosen, str(got))
        write_data(default_data())
        open_store(page, "/app/1091500/?editions", True)
        got = shortcuts(page)
        run.check("shortcuts after a reset: the base game tracked, the Ultimate box can be chosen",
                  got == [["sub/367653", "SweetSpot：追蹤中", None], ["bundle/32470", "SweetSpot：追蹤這個版本", False], None],
                  str(got))
        page.wait_for_timeout(500)
        run.check("shortcuts: nothing asks the local program before a press (FR-023a)", requests_seen(state) == [])

        button = SHORTCUT_BUTTON.format(ref="bundle/32470")
        for label, code in SYNTHETIC.items():
            page.evaluate(f"() => {{ const b = {button}; {{ {code}; }} {{ {code}; }} }}")
            text = page.evaluate(f"() => {button}.textContent")
            run.check(f"shortcut: page script {label}, twice, sends nothing (SC-008)",
                      text == "SweetSpot：追蹤這個版本" and requests_seen(state) == [], text)

        nxt = work / "next-shortcut.json"
        nxt.write_text(json.dumps(fixture_data(), ensure_ascii=False), encoding="utf-8")
        plan(state, status=status,
             choose={"delay": 1.5, "data": {"from": str(nxt), "to": str(DATA)},
                     "reply": {"v": 1, "ok": True, "cmd": "choose", "app": 1091500, "option": "bundle/32470",
                               "changed": True, "seconds": 1.5, "partial": False}})
        locator = page.locator(".sweetspot-shortcut[data-ref='bundle/32470'] button")
        locator.click()
        got, ok = wait_shortcuts(page, lambda s: s[1][1] == "SweetSpot：確定追蹤《電馭叛客 2077：終極版》？再按一次"
                                 and [r["cmd"] for r in requests_seen(state)] == ["status"], 3)
        run.check("shortcut: the first press asks to confirm and only now asks for the status", ok,
                  f"{got} {requests_seen(state)}")
        page.wait_for_timeout(1000)                     # the status is back
        locator.click()
        got, ok = wait_shortcuts(page, lambda s: [x[2] for x in s if x and x[2] is not None] == [True], 1.4)
        run.check("shortcut: confirmed, every shortcut is off while it runs (FR-006b)", ok, str(got))
        section, ok = wait_versions(page, lambda s: s["open"] and "已改為追蹤《電馭叛客 2077：終極版》" in s["text"])
        sent = requests_seen(state)[-1]
        run.check("shortcut: two presses send the same request as the panel",
                  sent == {"v": 1, "cmd": "choose", "app": 1091500, "option": "bundle/32470"}, str(sent))
        run.check("shortcut: progress and result in the panel's section, opened", ok, str(section and section["text"][:60]))
        got = shortcuts(page)
        run.check("shortcut: the boxes are drawn again with the new data (FR-011)", got == chosen, str(got))

        open_store(page, "/app/1091500/?restyled", True)
        run.check("restyled purchase boxes: no shortcut at all, the panel still there (011 FR-016)",
                  page.locator(".sweetspot-shortcut").count() == 0 and page.evaluate(PANEL_TEXT) is not None)
        page.close()
    write_data(fixture_data())
    run.check("the fake local program is unregistered after the shortcuts", not host_left())


OFFLINE_CHECKS = [check_reload, check_game_pages, check_popup, check_wishlist, check_stale, check_calendar_notices,
                  check_outdated_data, check_no_host]
LIVE_CHECKS: list = [check_live_popup, check_live_games, check_live_wishlist]


def serve_fixtures(ctx, routes: dict[str, str]):
    """routes: URL path (e.g. '/app/1903340/') -> fixture file name. Everything else is aborted."""
    aborted = []

    def handle(route):
        url = route.request.url
        path = url[len(STORE):] if url.startswith(STORE) else None
        if path in routes:
            route.fulfill(status=200, content_type="text/html; charset=utf-8",
                          body=(FIX / routes[path]).read_text(encoding="utf-8"))
        else:
            aborted.append(url)
            route.abort()
    ctx.route("http*://**/*", handle)
    return aborted


ROUTES: dict[str, str] = {
    "/app/1903340/": "game_twd.html", "/app/1091500/": "game_twd.html", "/app/9500013/": "game_twd.html",
    "/app/730/": "game_twd.html", "/app/1903340/?usd": "game_usd.html", "/app/1903340/?owned": "game_owned.html",
    "/app/1903340/?nopurchase": "game_no_purchase.html", "/agecheck/app/1903340/": "game_twd.html",
    "/wishlist/profiles/fixture/": "wishlist.html", "/wishlist/profiles/restyled/": "wishlist_restyled.html",
    "/app/1091500/?editions": "game_editions.html", "/app/1091500/?restyled": "game_editions_restyled.html",
}


def launch(p, profile):
    return p.chromium.launch_persistent_context(
        profile, channel="chromium", headless=True, locale="zh-TW", viewport={"width": 1280, "height": 900},
        args=[f"--disable-extensions-except={EXT}", f"--load-extension={EXT}"])


def main():
    global EXT, DATA
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="also check real Steam pages (network)")
    args = parser.parse_args()
    real = REAL_DATA.read_bytes() if REAL_DATA.exists() else None
    runs = []
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as work_dir:
        work = Path(work_dir)
        EXT = make_copy(work)
        DATA = EXT / "data" / "sweetspot-extension.json"
        with sync_playwright() as p:
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile:
                ctx = launch(p, profile)
                aborted = serve_fixtures(ctx, ROUTES)
                run = Run(ctx)
                for check in OFFLINE_CHECKS:
                    check(run)
                check_editions(run, work)
                check_shortcuts(run, work)
                run.check("no extra requests to other sites", not aborted, "; ".join(aborted[:5]))
                ctx.close()
                runs.append(run)
            if args.live:
                if real is None:
                    sys.exit("--live needs a real data file: run `uv run sweetspot report` first")
                write_data(real.decode("utf-8"))
                SHOTS.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile:
                    ctx = launch(p, profile)
                    ctx.add_cookies(AGE)
                    run = Run(ctx)
                    for check in LIVE_CHECKS:
                        check(run, json.loads(real.decode("utf-8")))
                    ctx.close()
                    runs.append(run)
    unchanged = (REAL_DATA.read_bytes() if REAL_DATA.exists() else None) == real
    print("extension/data/ 未被改動" if unchanged else "extension/data/ 被改動了！")
    ext_requests = [u for r in runs for u in r.ext_requests]
    print(f"擴充功能發出的請求 {len(ext_requests)}" + (f": {ext_requests[:5]}" if ext_requests else ""))
    results = [x for r in runs for x in r.results]
    bad = [label for label, ok, _ in results if not ok]
    print(f"{len(results) - len(bad)}/{len(results)} checks passed" + (f"; failed: {bad}" if bad else ""))
    sys.exit(0 if not bad and not ext_requests and unchanged and not host_left() else 1)


if __name__ == "__main__":
    main()
