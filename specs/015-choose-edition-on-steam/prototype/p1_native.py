"""P1 (015 plan research R0): native messaging from an unpacked extension on this machine.

uv run --with playwright==1.63.0 python specs/015-choose-edition-on-steam/prototype/p1_native.py [--python <python.exe>]

Questions:
  K  Does a manifest "key" give the extension a fixed id that we can compute before loading it?
  V  Which HKCU registry location does Playwright's Chromium read (Chromium, Chrome for Testing, Google Chrome)?
  H  Does a .bat host started by Chrome work: its arguments, working directory, job object, and round-trip time?
  C  Does the content script -> worker -> host chain work, and is the sender visible to the worker?
  T  Which clicks reach the content script as trusted input (spec FR-006a, SC-008)?
  L  When does the host process die: worker stopped, port disconnected, sendNativeMessage, a breakaway child,
     and a 40-second job (the worker's 30-second idle limit)?

Writes only a temporary folder and the HKCU key Software\\<vendor>\\NativeMessagingHosts\\com.sweetspot.prototype,
which is removed at the end (also on failure). Steam pages are a static fixture; every other request is aborted.
"""
import argparse
import base64
import ctypes
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
import winreg
from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
HOST_NAME = "com.sweetspot.prototype"
VENDORS = ["Chromium", "Google\\Chrome for Testing", "Google\\Chrome"]
FIXTURE = "<!doctype html><html><head><title>fixture</title></head><body><div id='game_area_purchase'>buy</div></body></html>"
results: list[bool] = []


def check(label, ok, detail=""):
    results.append(bool(ok))
    print(f"{'OK ' if ok else 'BAD'} {label}{': ' + str(detail) if detail != '' else ''}", flush=True)


def note(label, detail):
    print(f"    {label}: {detail}", flush=True)


def pid_alive(pid: int) -> bool:
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
    finally:
        kernel32.CloseHandle(handle)


def make_key(tmp: Path) -> tuple[str, str]:
    """(manifest key, extension id): the id is sha256(public key DER) in a-p letters."""
    openssl = shutil.which("openssl") or r"C:\Program Files\Git\mingw64\bin\openssl.exe"
    pem, der = tmp / "key.pem", tmp / "pub.der"
    subprocess.run([openssl, "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", str(pem)],
                   check=True, capture_output=True)
    subprocess.run([openssl, "pkey", "-in", str(pem), "-pubout", "-outform", "DER", "-out", str(der)],
                   check=True, capture_output=True)
    raw = der.read_bytes()
    ext_id = "".join(chr(ord("a") + int(c, 16)) for c in hashlib.sha256(raw).hexdigest()[:32])
    return base64.b64encode(raw).decode("ascii"), ext_id


CREATED_PARENTS: set[str] = set()      # NativeMessagingHosts keys this probe created (removed again when empty)


def register(vendor: str, manifest: Path):
    parent = f"Software\\{vendor}\\NativeMessagingHosts"
    try:
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, parent).Close()
    except FileNotFoundError:
        CREATED_PARENTS.add(parent)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"{parent}\\{HOST_NAME}") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, str(manifest))


def unregister(vendor: str):
    parent = f"Software\\{vendor}\\NativeMessagingHosts"
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, f"{parent}\\{HOST_NAME}")
    except FileNotFoundError:
        pass
    if parent in CREATED_PARENTS:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, parent)     # fails (and stays) when it is not empty
            CREATED_PARENTS.discard(parent)
        except OSError:
            pass


def host_logs(log_dir: Path, since: float) -> list[tuple[Path, list[str]]]:
    out = []
    for p in sorted(log_dir.glob("*.log")):
        lines = p.read_text(encoding="utf-8").splitlines()
        if lines and float(lines[0].split()[0]) >= since:
            out.append((p, lines))
    return out


def events(lines: list[str]) -> list[str]:
    return [line.split(" ", 1)[1].split(" ")[0] for line in lines if " tick" not in line]


@contextmanager
def session(p, ext: Path):
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as profile:
        ctx = p.chromium.launch_persistent_context(
            profile, channel="chromium", headless=True,
            args=[f"--disable-extensions-except={ext}", f"--load-extension={ext}"])

        def route(r):
            if r.request.url.startswith("https://store.steampowered.com/app/"):
                r.fulfill(status=200, content_type="text/html; charset=utf-8", body=FIXTURE)
            else:
                r.abort()
        ctx.route("http*://**/*", route)
        sw = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker")
        try:
            yield ctx, sw
        finally:
            ctx.close()


def stop_workers(ctx):
    cdp = ctx.new_cdp_session(ctx.pages[0] if ctx.pages else ctx.new_page())
    cdp.send("ServiceWorker.enable")
    cdp.send("ServiceWorker.stopAllWorkers")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--python", default=r"〈專案資料夾〉\.venv\Scripts\python.exe")
    ap.add_argument("--skip-long", action="store_true", help="skip the two 40-second keep-alive checks")
    args = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="sweetspot015-"))
    ext, log_dir = tmp / "ext", tmp / "logs"
    shutil.copytree(HERE / "ext", ext)
    log_dir.mkdir()
    key, ext_id = make_key(tmp)
    manifest = json.loads((ext / "manifest.json").read_text(encoding="utf-8"))
    manifest["key"] = key
    (ext / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    bat = tmp / "host.bat"
    bat.write_bytes(f'@"{args.python}" "{HERE / "host_probe.py"}" "{log_dir}" %*\r\n'.encode("mbcs"))
    host_manifest = tmp / "host.json"
    host_manifest.write_text(json.dumps({"name": HOST_NAME, "description": "015 probe", "path": str(bat),
                                         "type": "stdio", "allowed_origins": [f"chrome-extension://{ext_id}/"]}),
                             encoding="utf-8")
    note("temp folder", tmp)
    try:
        with sync_playwright() as p:
            # K and V: one launch per registry location, only that one registered
            vendor = None
            for v in VENDORS:
                for other in VENDORS:
                    unregister(other)
                register(v, host_manifest)
                with session(p, ext) as (ctx, sw):
                    got = sw.url.split("/")[2]
                    if v == VENDORS[0]:
                        check("K manifest key gives the computed id", got == ext_id, f"{got} vs {ext_id}")
                    r = sw.evaluate("probeSend({cmd: 'hello'})")
                    works = r["r"] is not None
                    note(f"V {v}", "works" if works else r["err"])
                    if works and vendor is None:
                        vendor = v
            check("V some HKCU location works for Playwright's Chromium", vendor is not None, vendor)
            if vendor is None:
                return
            for other in VENDORS:
                unregister(other)
            register(vendor, host_manifest)

            with session(p, ext) as (ctx, sw):
                # H: a fresh process per sendNativeMessage
                times, first = [], None
                for _ in range(3):
                    r = sw.evaluate("probeSend({cmd: 'hello'})")
                    times.append(r["ms"])
                    first = first or r["r"]
                check("H .bat host answers", first is not None)
                note("H argv", first["argv"])
                note("H cwd / exe", f"{first['cwd']} / {first['exe']}")
                note("H in job / flags", f"{first['in_job']} / {first['job_flags']}")
                note("H process start to first message (ms)", first["started_ms"])
                note("H sendNativeMessage round trips (ms)", times)
                r = sw.evaluate("probeConnect({cmd: 'hello'})")
                check("H connectNative answers", r.get("r") is not None, f"{r['ms']} ms")
                bad = sw.evaluate("new Promise(res => chrome.runtime.sendNativeMessage('com.sweetspot.missing', "
                                  "{cmd: 'hello'}, r => res(chrome.runtime.lastError && chrome.runtime.lastError.message)))")
                note("H error text when the host is not registered", bad)

                # C and T on the fixture game page
                page = ctx.new_page()
                page.goto("https://store.steampowered.com/app/1091500/")
                page.wait_for_selector("#probe-host", state="attached")
                page.locator("#ask").click()
                page.wait_for_function("document.querySelector('#probe-host').dataset.native")
                native = json.loads(page.evaluate("document.querySelector('#probe-host').dataset.native"))
                check("C content script -> worker -> host", native.get("r") is not None, f"{native['ms']} ms")
                note("C sender seen by the worker", native.get("sender"))
                synthetic = {
                    "element.click()": "b.click()",
                    "dispatchEvent(MouseEvent)": "b.dispatchEvent(new MouseEvent('click', {bubbles: true}))",
                    "dispatchEvent(PointerEvent)": "b.dispatchEvent(new PointerEvent('click', {bubbles: true}))",
                    "HTMLElement.prototype.click.call": "HTMLElement.prototype.click.call(b)",
                    "keydown Enter + keyup": "b.focus(); for (const t of ['keydown', 'keypress', 'keyup']) "
                                             "b.dispatchEvent(new KeyboardEvent(t, {key: 'Enter', bubbles: true}))",
                    "form-less submit via label": "const l = document.createElement('label'); "
                                                  "l.htmlFor = 'b'; document.body.append(l); l.click()",
                }
                for label, code in synthetic.items():
                    page.evaluate("document.querySelector('#probe-host').dataset.clicks = ''")
                    page.evaluate(f"(() => {{ const b = document.querySelector('#probe-host').shadowRoot"
                                  f".querySelector('#b'); {code}; }})()")
                    clicks = page.evaluate("document.querySelector('#probe-host').dataset.clicks")
                    check(f"T page script {label} is not trusted", "T" not in clicks, repr(clicks))
                page.evaluate("document.querySelector('#probe-host').dataset.clicks = ''")
                page.locator("#b").click()
                page.locator("#b").focus()
                page.keyboard.press("Enter")
                page.keyboard.press("Space")
                clicks = page.evaluate("document.querySelector('#probe-host').dataset.clicks")
                check("T mouse click, Enter and Space are trusted", clicks == "TTT", repr(clicks))
                page.evaluate("(() => { const a = document.querySelector('#probe-host').shadowRoot.querySelector('#ask');"
                              " document.querySelector('#probe-host').dataset.native = ''; a.click(); })()")
                time.sleep(1)
                check("T untrusted click on #ask sends nothing",
                      page.evaluate("document.querySelector('#probe-host').dataset.native") == "refused: untrusted")

            def lifetime(label, start_js, interfere, wait):
                with session(p, ext) as (ctx, sw):
                    since = time.time()
                    sw.evaluate(start_js)
                    time.sleep(1.5)
                    interfere(ctx, sw)
                    time.sleep(wait)
                    logs = host_logs(log_dir, since)
                    for path, lines in logs:
                        pid = int(path.stem.split("-")[1])
                        note(f"L {label} {path.stem}", f"{events(lines)} alive={pid_alive(pid)}")
                    return logs

            def done(logs, prefix="host"):
                return any("work done" in " ".join(lines) or "child done" in " ".join(lines)
                           for path, lines in logs if path.stem.startswith(prefix))

            logs = lifetime("worker stopped (connect)", "void probeConnect({cmd: 'work', seconds: 5}); 1",
                            lambda ctx, sw: stop_workers(ctx), 6)
            note("L result", f"work finished: {done(logs)}")
            logs = lifetime("port disconnected", "void probeConnect({cmd: 'work', seconds: 5}, 1000); 1",
                            lambda ctx, sw: None, 6)
            note("L result", f"work finished: {done(logs)}")
            logs = lifetime("worker stopped (send)", "void probeSend({cmd: 'work', seconds: 5}); 1",
                            lambda ctx, sw: stop_workers(ctx), 6)
            note("L result", f"work finished: {done(logs)}")
            logs = lifetime("breakaway child, port disconnected",
                            "void probeConnect({cmd: 'spawn_then_work', child_seconds: 5, seconds: 5}, 1000); 1",
                            lambda ctx, sw: None, 6)
            note("L result", f"host finished: {done(logs)}; child finished: {done(logs, 'child')}")
            if not args.skip_long:
                for how in ("probeConnect", "probeSend"):
                    with session(p, ext) as (ctx, sw):
                        r = sw.evaluate(f"{how}({{cmd: 'work', seconds: 40}})")
                        check(f"L 40-second job answered through {how}", r.get("r") is not None,
                              f"{r.get('err')} after {r['ms']} ms")
    finally:
        for v in VENDORS:
            unregister(v)
        left = []
        for v in VENDORS:
            try:
                winreg.OpenKey(winreg.HKEY_CURRENT_USER, f"Software\\{v}\\NativeMessagingHosts\\{HOST_NAME}").Close()
                left.append(v)
            except FileNotFoundError:
                pass
        check("cleanup: no registry key left", not left, left)
    print(f"{sum(results)}/{len(results)} checks passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
