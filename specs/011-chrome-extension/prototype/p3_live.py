"""P3 (plan research R0.2, R0.4): the prototype extension on live Steam pages (not logged in) plus fixtures.

uv run python specs/011-chrome-extension/prototype/p0_export.py      # data file first
uv run --with playwright python specs/011-chrome-extension/prototype/p3_live.py

- Game pages: panel right above #game_area_purchase, page price of the tracked option = record price, time to panel.
- A game not in the data: page unchanged.  Fixtures: owned game (collapsed note), restyled wishlist (0 lines).
- The live wishlist is in p4_wishlist.py (it scrolls the inner list with the mouse wheel).
- Network: any request initiated by extension code (CDP initiator) and a CSP check from the service worker.
Screenshots and out/p3_live.json go to out/ (ignored by git).
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("PW_EXPERIMENTAL_SERVICE_WORKER_NETWORK_EVENTS", "1")
from playwright.sync_api import sync_playwright  # noqa: E402

HERE = Path(__file__).resolve().parent
EXT, OUT = HERE / "ext", HERE / "out"
DATA = json.loads((EXT / "data" / "steamsage-extension.json").read_text(encoding="utf-8"))
BY_ID = {g["app_id"]: g for g in DATA["games"]}
SAMPLE = [239140, 359870, 812140, 881020, 1091500, 1113000, 1402110, 1903340, 1868140, 2258500, 2384580,
          2399220, 1593500, 3280350, 9500003, 9500013]
NOT_IN_DATA = 730
WISHLIST = "https://store.steampowered.com/wishlist/profiles/〈SteamID〉/"
AGE = [{"name": n, "value": v, "domain": "store.steampowered.com", "path": "/"}
       for n, v in (("birthtime", "0"), ("lastagecheckage", "1-0-1990"), ("wants_mature_content", "1"))]
OWNED = """<!doctype html><html><body><div class="game_area_already_owned">已在收藏庫中</div>
<div id="game_area_purchase"><div class="game_area_purchase_game_wrapper"><div class="game_area_purchase_game">
<h2>購買 光與影：33號遠征隊</h2><form name="add_to_cart_685434"><input type="hidden" name="subid" value="685434"></form>
<div class="game_purchase_price price" data-price-final="79000">NT$ 790</div></div></div></div></body></html>"""
RESTYLED = """<!doctype html><html><body><div id="list">""" + "".join(
    f'<div data-index="{i}"><a href="https://store.steampowered.com/app/{a}/"><img alt=""></a>'
    f'<div><a href="https://store.steampowered.com/app/{a}/"><span>{g["name"]}</span></a></div></div>'
    for i, (a, g) in enumerate(list(BY_ID.items())[:10])) + "</div></body></html>"


def probe(page):
    el = page.locator("#steamsage-probe")
    el.wait_for(state="attached", timeout=10000)
    raw = el.get_attribute("data-probe")
    return json.loads(raw) if raw else {}


def main():
    OUT.mkdir(exist_ok=True)
    report, ext_initiated = {"games": []}, []
    with sync_playwright() as p, tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile:
        ctx = p.chromium.launch_persistent_context(
            profile, channel="chromium", headless=True, locale="zh-TW", viewport={"width": 1280, "height": 900},
            args=[f"--disable-extensions-except={EXT}", f"--load-extension={EXT}"])
        ctx.add_cookies(AGE)
        sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
        sw_requests = []
        ctx.on("request", lambda r: sw_requests.append(r.url) if r.service_worker else None)
        ctx.route("https://store.steampowered.com/app/1903340/?fixture=owned",
                  lambda r: r.fulfill(status=200, content_type="text/html; charset=utf-8", body=OWNED))
        ctx.route("https://store.steampowered.com/wishlist/profiles/fixture/",
                  lambda r: r.fulfill(status=200, content_type="text/html; charset=utf-8", body=RESTYLED))

        def watch(page):
            cdp = ctx.new_cdp_session(page)
            cdp.send("Network.enable")

            def seen(ev):
                ini = ev.get("initiator") or {}
                frames = [f.get("url", "") for f in ((ini.get("stack") or {}).get("callFrames") or [])]
                if (ini.get("url") or "").startswith("chrome-extension://") or any(u.startswith("chrome-extension://") for u in frames):
                    ext_initiated.append(ev["request"]["url"])
            cdp.on("Network.requestWillBeSent", seen)
            return page

        page = watch(ctx.new_page())
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        for app in SAMPLE:
            t0 = time.monotonic()
            page.goto(f"https://store.steampowered.com/app/{app}/", wait_until="domcontentloaded")
            info = {"app_id": app, "group": BY_ID[app]["group"], "url": page.url}
            try:
                pr = probe(page)
                if pr.get("game", {}).get("inserted"):
                    page.wait_for_selector(".steamsage-panel", timeout=5000)
                info["panel_ms"] = round((time.monotonic() - t0) * 1000)
                info["probe"] = pr
                info["panels"] = page.locator(".steamsage-panel").count()
                info["right_above_purchase"] = page.evaluate(
                    "() => { const p = document.querySelector('.steamsage-panel');"
                    " return !!p && p.nextElementSibling && p.nextElementSibling.id === 'game_area_purchase'; }")
                live = (pr.get("game") or {}).get("live") or {}
                info["page_cents"], info["record_twd"] = live.get("cents"), BY_ID[app].get("price_twd")
                info["price_equal"] = (live.get("cents") is not None and BY_ID[app].get("price_twd") is not None
                                       and live["cents"] == BY_ID[app]["price_twd"] * 100)
                if app in (1903340, 1091500, 9500003):
                    page.locator(".steamsage-panel").screenshot(path=str(OUT / f"panel-{app}.png"))
            except Exception as exc:  # noqa: BLE001
                info["error"] = f"{type(exc).__name__}: {exc}"
            report["games"].append(info)

        page.goto(f"https://store.steampowered.com/app/{NOT_IN_DATA}/", wait_until="domcontentloaded")
        pr = probe(page)
        report["not_in_data"] = {"probe": pr, "panels": page.locator(".steamsage-panel").count()}
        page.goto("https://store.steampowered.com/app/1903340/?fixture=owned")
        page.wait_for_selector(".steamsage-panel", timeout=5000)
        report["owned_fixture"] = page.evaluate(
            "() => document.querySelector('.steamsage-panel').shadowRoot.textContent.includes('你已擁有這款遊戲')")
        page.goto("https://store.steampowered.com/wishlist/profiles/fixture/")
        pr = probe(page)
        page.wait_for_timeout(1000)
        report["restyled_fixture"] = {"lines": page.locator(".steamsage-line").count(), "probe": pr.get("wish")}

        report["csp_from_service_worker"] = sw.evaluate(
            "fetch('https://example.com/').then(() => 'allowed', e => 'blocked: ' + e.message)")
        report["page_errors"] = errors
        report["extension_initiated_requests"] = ext_initiated
        report["service_worker_requests"] = sw_requests
        ctx.close()

    (OUT / "p3_live.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for g in report["games"]:
        pr = (g.get("probe") or {}).get("game") or {}
        print(f"{g['app_id']:>8} {g['group']:<4} panels={g.get('panels')} above={g.get('right_above_purchase')} "
              f"price_equal={g.get('price_equal')} page={g.get('page_cents')} record_twd={g.get('record_twd')} "
              f"{g.get('panel_ms')} ms, {pr.get('ms_after_dcl')} ms after DCL, area={pr.get('area')} {g.get('error', '')}")
    for k in ("not_in_data", "owned_fixture", "restyled_fixture", "csp_from_service_worker",
              "page_errors", "extension_initiated_requests", "service_worker_requests"):
        print(k, json.dumps(report[k], ensure_ascii=False)[:600])


if __name__ == "__main__":
    sys.exit(main())
