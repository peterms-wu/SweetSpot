"""P2 (plan research R0.2): read-only probe of live Steam pages, no extension, not logged in.

uv run --with playwright python specs/011-chrome-extension/prototype/p2_probe.py

- Game pages: every purchase option's package/bundle id, title, final price (data attribute and text), currency;
  compared with the tracked option (`version.option`) and `current.price_cents` of the latest official record.
- Wishlist page: row containers, the name link, and whether every wishlist App shows up while scrolling.
Output: out/p2_probe.json (contains the wishlist, ignored by git).
"""
import gzip
import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent / "out"
SAMPLE = [239140, 359870, 812140, 881020, 1091500, 1113000, 1402110, 1903340, 1868140, 2258500, 2384580,
          2399220, 1593500, 3280350, 9500003, 9500013]
WISHLIST = "https://store.steampowered.com/wishlist/profiles/〈SteamID〉/"
AGE = [{"name": n, "value": v, "domain": "store.steampowered.com", "path": "/"}
       for n, v in (("birthtime", "0"), ("lastagecheckage", "1-0-1990"), ("wants_mature_content", "1"))]

OPTIONS_JS = """() => [...document.querySelectorAll('#game_area_purchase .game_area_purchase_game')].map(b => {
  const inputs = Object.fromEntries([...b.querySelectorAll('form input[type=hidden]')].map(i => [i.name, i.value]));
  const priced = b.querySelector('[data-price-final]');
  const final = b.querySelector('.discount_final_price, .game_purchase_price');
  const title = b.querySelector('h1, h2');
  return {subid: inputs.subid || null, bundleid: inputs.bundleid || null,
          title: title ? title.innerText.trim() : null,
          data_price_final: priced ? priced.getAttribute('data-price-final') : null,
          final_text: final ? final.innerText.trim() : null,
          wrapper_ids: b.closest('.game_area_purchase_game_wrapper') ?
             [...b.closest('.game_area_purchase_game_wrapper').attributes].filter(a => a.name.startsWith('data-')).map(a => a.name + '=' + a.value) : [],
          in_dropdown: !!b.closest('.game_area_purchase_game_dropdown_subscription, .game_purchase_sub_dropdown')};
})"""


def latest_record():
    path = max((ROOT / "data" / "forecasts").glob("*.json.gz"))
    return path.name, json.load(gzip.open(path))


def probe_game(page, d):
    page.goto(f"https://store.steampowered.com/app/{d['app_id']}/", wait_until="domcontentloaded")
    info = {"app_id": d["app_id"], "name": d["name"], "group": d["group"], "final_url": page.url,
            "agecheck": "/agecheck/" in page.url}
    if info["agecheck"]:
        return info
    page.wait_for_selector("#game_area_purchase, .game_area_comingsoon, #error_box", timeout=15000)
    info["purchase_area"] = page.locator("#game_area_purchase").count() > 0
    info["options"] = page.evaluate(OPTIONS_JS)
    opt = (d.get("version") or {}).get("option") or {}
    key = "bundleid" if opt.get("kind") == "bundle" else "subid"
    match = [o for o in info["options"] if opt and o[key] == str(opt.get("id"))]
    cur = (d.get("current") or {}).get("price_cents")
    info["tracked"] = {"kind": opt.get("kind"), "id": opt.get("id"), "record_price_cents": cur,
                       "matches_on_page": len(match),
                       "page_price_cents": int(match[0]["data_price_final"]) if match and match[0]["data_price_final"] else None,
                       "page_text": match[0]["final_text"] if match else None}
    return info


ROWS_JS = """() => [...document.querySelectorAll('[data-index]')].map(r => {
  const links = [...r.querySelectorAll('a[href*="/app/"]')];
  const ids = [...new Set(links.map(a => (a.href.match(/\\/app\\/(\\d+)/) || [])[1]).filter(Boolean))];
  const named = links.filter(a => a.innerText.trim().length > 0);
  const n = named[0];
  const path = []; let el = n;
  while (el && el !== r && path.length < 8) { path.push(el.tagName.toLowerCase()); el = el.parentElement; }
  return {index: r.getAttribute('data-index'), ids, name: n ? n.innerText.trim() : null, name_links: named.length,
          links: links.length, name_path: path.join('<'),
          name_parent_children: n ? n.parentElement.children.length : null,
          top: Math.round(r.getBoundingClientRect().top)};
})"""


def probe_wishlist(page, wanted):
    page.goto(WISHLIST, wait_until="domcontentloaded")
    t0 = time.monotonic()
    page.wait_for_selector("[data-index] a[href*='/app/']", timeout=30000)
    first_rows_s = time.monotonic() - t0
    seen, samples = {}, []
    height = page.evaluate("document.documentElement.scrollHeight")
    y = 0
    while y < height + 2000:
        for row in page.evaluate(ROWS_JS):
            for i in row["ids"][:1]:
                seen.setdefault(int(i), row)
        if not samples:
            samples = page.evaluate("() => [...document.querySelectorAll('[data-index]')].slice(0, 2).map(r => r.outerHTML.slice(0, 4000))")
        y += 500
        page.mouse.wheel(0, 500)
        page.wait_for_timeout(250)
        height = page.evaluate("document.documentElement.scrollHeight")
    rendered = page.evaluate("document.querySelectorAll('[data-index]').length")
    return {"first_rows_s": round(first_rows_s, 1), "rendered_at_end": rendered, "seen": len(seen),
            "wanted": len(wanted), "missing": sorted(set(wanted) - set(seen)), "extra": sorted(set(seen) - set(wanted)),
            "name_paths": sorted({r["name_path"] for r in seen.values()}),
            "name_links_per_row": sorted({r["name_links"] for r in seen.values()}),
            "names_equal_record": sum(1 for a, r in seen.items() if r["name"] == wanted.get(a)),
            "rows": {str(a): r for a, r in seen.items()}, "sample_html": samples}


def main():
    OUT.mkdir(exist_ok=True)
    fname, rec = latest_record()
    by_id = {d["app_id"]: d for d in rec["decisions"]}
    result = {"record": fname, "games": [], "wishlist": None}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(locale="zh-TW", viewport={"width": 1280, "height": 900})
        ctx.add_cookies(AGE)
        page = ctx.new_page()
        for app in SAMPLE:
            try:
                result["games"].append(probe_game(page, by_id[app]))
            except Exception as exc:  # noqa: BLE001 - a probe; keep going
                result["games"].append({"app_id": app, "error": f"{type(exc).__name__}: {exc}"})
        ctx2 = browser.new_context(locale="zh-TW", viewport={"width": 1280, "height": 900})
        page2 = ctx2.new_page()
        try:
            result["wishlist"] = probe_wishlist(page2, {a: d["name"] for a, d in by_id.items()})
        except Exception as exc:  # noqa: BLE001
            result["wishlist"] = {"error": f"{type(exc).__name__}: {exc}"}
        noage = ctx2.new_page()
        noage.goto("https://store.steampowered.com/app/2399220/", wait_until="domcontentloaded")
        result["agecheck_without_cookie"] = noage.url
        browser.close()
    (OUT / "p2_probe.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    for g in result["games"]:
        if "error" in g:
            print(g["app_id"], "ERROR", g["error"])
            continue
        t = g.get("tracked") or {}
        print(f"{g['app_id']:>8} {g['group']:<4} age={g['agecheck']!s:<5} options={len(g.get('options', []))} "
              f"tracked={t.get('kind')}/{t.get('id')} on_page={t.get('matches_on_page')} "
              f"record={t.get('record_price_cents')} page={t.get('page_price_cents')} text={t.get('page_text')!r}")
    w = result["wishlist"]
    print("wishlist:", {k: w[k] for k in w if k not in ("rows", "sample_html")} if "error" not in w else w)
    print("agecheck without cookie:", result["agecheck_without_cookie"])


if __name__ == "__main__":
    sys.exit(main())
