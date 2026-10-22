"""P4 (plan research R0.2): wishlist page details. Does React error #418 appear without the extension too?
Which element scrolls? Does a line survive React re-rendering, and does every row get one while scrolling?

uv run --with playwright python specs/011-chrome-extension/prototype/p4_wishlist.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
EXT, OUT = HERE / "ext", HERE / "out"
DATA = json.loads((EXT / "data" / "steamsage-extension.json").read_text(encoding="utf-8"))
BY_ID = {g["app_id"]: g for g in DATA["games"]}
WISHLIST = "https://store.steampowered.com/wishlist/profiles/〈SteamID〉/"

STATE = """() => [...document.querySelectorAll('[data-index]')].map(r => {
  const a = r.querySelector('a[href*="/app/"]'); const id = a && Number((a.href.match(/\\/app\\/(\\d+)/) || [])[1]);
  const lines = [...r.querySelectorAll('.steamsage-line')];
  const b = r.getBoundingClientRect();
  return {index: Number(r.dataset.index), id, lines: lines.length,
          right: lines.filter(l => Number(l.dataset.app) === id).length, top: Math.round(b.top), h: Math.round(b.height)};
})"""
SCROLLER = """() => { const r = document.querySelector('[data-index]'); const out = []; let el = r;
  while (el) { const s = getComputedStyle(el); if (/(auto|scroll)/.test(s.overflowY) && el.scrollHeight > el.clientHeight)
    out.push({tag: el.tagName, cls: el.className, sh: el.scrollHeight, ch: el.clientHeight}); el = el.parentElement; }
  return {chain: out, doc: [document.documentElement.scrollHeight, innerHeight], scrollingElement: document.scrollingElement.tagName}; }"""


def run(with_ext: bool):
    errors, rows = [], {}
    with sync_playwright() as p, tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile:
        args = [f"--disable-extensions-except={EXT}", f"--load-extension={EXT}"] if with_ext else []
        ctx = p.chromium.launch_persistent_context(profile, channel="chromium", headless=True, locale="zh-TW",
                                                   viewport={"width": 1280, "height": 900}, args=args)
        ctx.add_cookies([{"name": n, "value": v, "domain": "store.steampowered.com", "path": "/"} for n, v in
                         (("birthtime", "0"), ("lastagecheckage", "1-0-1990"), ("wants_mature_content", "1"))])
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)[:120]))
        page.on("console", lambda m: errors.append("console: " + m.text[:120]) if m.type == "error" else None)
        page.goto(WISHLIST, wait_until="domcontentloaded")
        page.wait_for_selector("[data-index] a[href*='/app/']", timeout=30000)
        page.wait_for_timeout(1500)
        scroller = page.evaluate(SCROLLER)
        late, dup, idle, steps = [], set(), 0, 0
        while idle < 6 and steps < 300:
            steps += 1
            before = len(rows)
            for r in page.evaluate(STATE):                  # every rendered row, visible or in the overscan
                if not r["id"]:
                    continue
                if with_ext:
                    want = 1 if r["id"] in BY_ID else 0
                    if r["lines"] > 1:
                        dup.add(r["id"])
                    if r["right"] != want:
                        late.append(r)
                rows.setdefault(r["id"], r)
            idle = idle + 1 if len(rows) == before else 0
            page.mouse.move(640, 500)
            page.mouse.wheel(0, 350)
            page.wait_for_timeout(1000)                     # FR-015: checked 1 s after each scroll step
        if with_ext:
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(1500)
            page.screenshot(path=str(OUT / "wishlist.png"))
            # hover title (native tooltip) of the first line
            first_title = page.evaluate("() => { const l = document.querySelector('.steamsage-line'); return l && l.title; }")
        else:
            first_title = None
        ctx.close()
    return {"with_ext": with_ext, "errors": errors, "scroller": scroller, "steps": steps, "seen": len(rows),
            "in_data": sum(1 for a in rows if a in BY_ID), "missing": sorted(set(BY_ID) - set(rows)),
            "not_right_after_1s": len(late), "late_sample": late[:5], "duplicates": sorted(dup),
            "first_title": first_title}


def main():
    OUT.mkdir(exist_ok=True)
    results = [run(False), run(True)]
    (OUT / "p4_wishlist.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in results:
        print(json.dumps({k: r[k] for k in r if k != "late_sample"}, ensure_ascii=False)[:1500])
        if r["late_sample"]:
            print("  late:", r["late_sample"])


if __name__ == "__main__":
    sys.exit(main())
