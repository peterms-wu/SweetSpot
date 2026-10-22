"""P1 (plan research R0.1): after the data file is rewritten, does the unpacked extension read the new file
without reloading the extension or restarting the browser? Also records every network request (SC-005).

uv run --with playwright python specs/011-chrome-extension/prototype/p1_reload.py

Runs Playwright's Chromium (branded Chrome 137+ ignores --load-extension) with the prototype extension in ext/.
Steam pages are served from a static fixture (route), so the only requests are the document itself and anything
the extension makes; every other request is aborted and logged.
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
EXT = HERE / "ext"
DATA = EXT / "data" / "steamsage-extension.json"
FIXTURE = "<!doctype html><html><head><title>fixture</title></head><body><div id='game_area_purchase'>buy</div></body></html>"


def write_atomic(payload: dict):
    tmp = DATA.with_name(DATA.name + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, DATA)


def payload(as_of: str, now: int) -> dict:
    return {"format": "steamsage.extension/0", "as_of": as_of,
            "games": [{"app_id": i, "group": "now" if i < now else "wait"} for i in range(5)]}


def main():
    DATA.parent.mkdir(exist_ok=True)
    saved = DATA.read_bytes() if DATA.exists() else None           # restored at the end (p0_export.py's file)
    write_atomic(payload("2026-09-27T00:00:00Z", 1))
    requests, results = [], []

    def check(label, got, want):
        ok = got == want
        results.append(ok)
        print(f"{'OK ' if ok else 'BAD'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))

    with sync_playwright() as p, tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile:
        ctx = p.chromium.launch_persistent_context(
            profile, channel="chromium", headless=True,
            args=[f"--disable-extensions-except={EXT}", f"--load-extension={EXT}"])
        ctx.on("request", lambda r: requests.append((r.url, r.resource_type)))

        def route(r):
            if r.request.url.startswith("https://store.steampowered.com/app/"):
                r.fulfill(status=200, content_type="text/html; charset=utf-8", body=FIXTURE)
            else:
                r.abort()
        ctx.route("http*://**/*", route)
        sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
        ext_id = sw.url.split("/")[2]
        popup_url = f"chrome-extension://{ext_id}/popup.html"
        cdp = ctx.new_cdp_session(ctx.pages[0] if ctx.pages else ctx.new_page())

        def popup_text():
            page = ctx.new_page()
            t0 = time.monotonic()
            page.goto(popup_url)
            page.wait_for_selector("#stamp[data-ok]")
            ms = (time.monotonic() - t0) * 1000
            text = page.inner_text("#stamp")
            page.close()
            return text, ms

        def badge():
            return sw.evaluate("chrome.action.getBadgeText({})") if not sw_dead() else None

        def sw_dead():
            return sw not in ctx.service_workers

        def store_text(page):
            page.reload() if page.url.startswith("https://store") else page.goto("https://store.steampowered.com/app/1903340/")
            page.wait_for_selector("#steamsage-probe", state="attached")
            return page.inner_text("#steamsage-probe")

        time.sleep(1)
        text, ms = popup_text()
        check("1 popup reads v1", text, "as_of=2026-09-27T00:00:00Z games=5")
        print(f"    popup shown in {ms:.0f} ms")
        check("1 badge v1", badge(), "1")
        store = ctx.new_page()
        check("1 store page reads v1", store_text(store), "as_of=2026-09-27T00:00:00Z")
        check("1 alarms", [a["name"] for a in sw.evaluate("chrome.alarms.getAll()")], ["refresh"])

        write_atomic(payload("2026-09-28T02:30:00Z", 2))            # rewrite (temp + rename), no reload
        text, _ = popup_text()
        check("2 popup reads v2 after atomic rewrite", text, "as_of=2026-09-28T02:30:00Z games=5")
        check("2 badge v2 (updated when popup opened)", badge(), "2")
        check("2 store page reload reads v2", store_text(store), "as_of=2026-09-28T02:30:00Z")

        DATA.write_text(json.dumps(payload("2026-09-29T02:30:00Z", 3)), encoding="utf-8")   # in-place rewrite
        sw.evaluate("refreshBadge()")                                 # what the 30-minute alarm does
        check("3 badge v3 via the alarm handler (no page)", badge(), "3")

        cdp.send("ServiceWorker.enable")
        cdp.send("ServiceWorker.stopAllWorkers")                      # the worker is idle-killed after ~30 s anyway
        time.sleep(1)
        write_atomic(payload("2026-09-30T02:30:00Z", 0))
        text, _ = popup_text()
        check("4 popup after the worker was stopped reads v4", text, "as_of=2026-09-30T02:30:00Z games=5")
        sw = ctx.service_workers[0]
        check("4 badge 0 -> empty", badge(), "")

        DATA.write_text('{"format": "steamsage.extension/0", "as_of": ', encoding="utf-8")
        text, _ = popup_text()
        check("5 half-written file -> broken", text, "no data: broken")
        check("5 badge !", badge(), "!")
        DATA.unlink()
        text, _ = popup_text()
        check("6 missing file -> missing", text, "no data: missing")
        ctx.close()

    external = [(u, t) for u, t in requests if not u.startswith(("chrome-extension://", "https://store.steampowered.com/app/"))]
    print(f"requests seen: {len(requests)}; store documents: "
          f"{sum(1 for u, _ in requests if u.startswith('https://store.steampowered.com/app/'))}; "
          f"extension files: {sum(1 for u, _ in requests if u.startswith('chrome-extension://'))}; other: {len(external)}")
    for u, t in external:
        print("   other:", t, u)
    print(f"{sum(results)}/{len(results)} checks passed")
    if saved is not None:
        DATA.write_bytes(saved)
    sys.exit(0 if all(results) and not external else 1)


if __name__ == "__main__":
    main()
