"""Find personal values in the files to publish; only the rule table below may allow one (feature 014 US2, FR-005).

    uv run python scripts/scan_personal.py           # offline kinds: list unallowed hits (exit 1) or counts (exit 0)
    uv run python scripts/scan_personal.py --write   # also regenerate docs/personal-scan.md from the scan

The rule table is contracts/scan-personal.md (specs/014-publish-github/). The first rule that matches a hit decides
its category; a hit no rule matches is not allowed. tests/unit/test_scan_personal.py runs the scan on the repository
(FR-016b) and holds samples for every rule. The kinds that need the user's keys, database or the network are added by
`--publish` (014 T027).
"""

import argparse
import re
import subprocess
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import TextIO

ROOT = Path(__file__).resolve().parents[1]
DOC = Path("docs") / "personal-scan.md"
EXCLUDED = {"HANDOFF.md"}                                   # never published (014 FR-009); the scan skips it too
ACCOUNT_0 = 76561197960265728                              # SteamID64 of account 0: Steam gives it to no one

FINDERS = {
    "steamid": re.compile(r"(?<!\d)7656119\d{10}(?!\d)"),
    "path": re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:(?:\\\\|\\|/)[^\s\"'`<>|*?,;)\]，。、；：「」（）]*"),
    "userdir": re.compile(r"(?i)(?:\\\\|\\|/)Users(?:\\\\|\\|/)[^\s\\/\"'`<>|*?]+"),
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"),
    "session": re.compile(r"claude\.ai/(?:code/)?(?:session|chat)[_/][A-Za-z0-9_-]+"),
    "private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}
KEY_FILE = re.compile(r"\.(?:pem|key)$", re.I)
KEY_MARK = "-----BEGIN " + "PRIVATE KEY-----"   # stands for a binary file holding a key
SYSTEM_PATH = re.compile(r"(?i)^[A-Za-z]:(?:\\\\|\\|/)(?:(?:Windows|Program|ProgramData)"  # "Program Files" stops
                         r"(?:\\\\|\\|/|$)|$)")                                  # at its space; a bare drive root
KNOWN_ADDRESS = re.compile(r"(?i)^(?:git@github\.com|[^@]+@users\.noreply\.github\.com|noreply@anthropic\.com|"
                           r"[^@]+@example\.(?:com|org|net))$")
RULE_DOCS = ("scripts/scan_personal.py", "docs/personal-scan.md", "tests/unit/test_scan_personal.py",
             "specs/014-publish-github/contracts/scan-personal.md")


@dataclass(frozen=True)
class Hit:
    path: str
    line_no: int
    kind: str
    value: str
    category: str | None


@dataclass(frozen=True)
class Rule:
    key: str
    title: str
    kinds: tuple[str, ...]
    rule: str
    reason: str
    test: Callable[[str, str, str, "Context"], bool]      # (path, line, value, context)


@dataclass(frozen=True)
class Context:
    real_roots: tuple[PureWindowsPath, ...]                  # the folder holding this repo, and the home folder


def _is_rule_doc(path: str) -> bool:
    return path in RULE_DOCS or path.startswith("specs/014-publish-github/inventory/")


def _inside_real_root(value: str, ctx: Context) -> bool:
    try:
        p = PureWindowsPath(value.replace("\\\\", "\\").rstrip(".:"))
    except ValueError:
        return False
    return any(p == r or r in p.parents for r in ctx.real_roots)


RULES = [
    Rule("fictional-steamid", "虛構的 SteamID", ("steamid",),
         "數值不大於帳號 0 的 SteamID64（`76561197960265728`）",
         "帳號 0 與更小的值 Steam 不會分給任何人；測試與文件用它當例子（014 research R8）",
         lambda path, line, value, ctx: int(value) <= ACCOUNT_0),
    Rule("rule-doc", "規則說明", ("path", "userdir", "email", "session"),
         "路徑是掃描本身、它的測試（`tests/unit/test_scan_personal.py`）、它的契約、`docs/personal-scan.md`，"
         "或 `specs/014-publish-github/inventory/` 底下的檔案",
         "規則與樣本本身必須寫出這些形狀；SteamID 不在此列，樣本一律在執行時組出",
         lambda path, line, value, ctx: _is_rule_doc(path)),
    Rule("system-path", "系統路徑", ("path",),
         "任何磁碟的 `X:\\Windows`、`X:\\Program Files`（路徑在空白處截斷，所以比對的是 `X:\\Program`）、`X:\\ProgramData` 底下，"
         "或磁碟根目錄本身（含 `\\\\` 跳脫寫法），而且不在本機的專案上層資料夾或使用者資料夾",
         "每台 Windows 都有的位置（例如排程用的 `conhost.exe`），不透露任何人的資訊",
         lambda path, line, value, ctx: bool(SYSTEM_PATH.match(value)) and not _inside_real_root(value, ctx)),
    Rule("test-fiction", "測試用的虛構路徑", ("path",),
         "路徑在 `tests/` 下，而且不在本機的專案上層資料夾或使用者資料夾",
         "測試需要 Windows 路徑的形狀；真實的資料夾（本機專案的上層、使用者資料夾）仍然不允許",
         lambda path, line, value, ctx: path.startswith("tests/") and not _inside_real_root(value, ctx)),
    Rule("known-address", "公開的地址", ("email",),
         "`git@github.com`（ssh remote 的寫法）、`…@users.noreply.github.com`、`noreply@anthropic.com`、`example.com／org／net`",
         "不是任何人的私人信箱",
         lambda path, line, value, ctx: bool(KNOWN_ADDRESS.match(value))),
    Rule("license", "授權的著作權人", ("account",),
         "路徑是 `LICENSE`，而且該行以 `Copyright` 開頭",
         "MIT 授權必須寫出著作權人；使用者 2026-10-18 選定用 GitHub 帳號名（014 FR-015）",
         lambda path, line, value, ctx: path == "LICENSE" and line.lstrip().startswith("Copyright")),
]
KINDS = ("steamid", "path", "userdir", "email", "session", "private_key", "account")


@dataclass
class ScanResult:
    hits: list[Hit] = field(default_factory=list)

    @property
    def unallowed(self) -> list[Hit]:
        return [h for h in self.hits if h.category is None]

    def files(self, key: str) -> list[str]:
        return sorted({h.path for h in self.hits if h.category == key})


def default_context(root: Path = ROOT) -> Context:
    return Context(real_roots=(PureWindowsPath(str(root.resolve().parent)), PureWindowsPath(str(Path.home()))))


def categorize(path: str, line: str, kind: str, value: str, ctx: Context) -> str | None:
    for rule in RULES:
        if kind in rule.kinds and rule.test(path, line, value, ctx):
            return rule.key
    return None


def scan(files: Iterable[tuple[str, str]], *, owners: set[str], ctx: Context | None = None,
         excluded: Iterable[str] = EXCLUDED) -> ScanResult:
    ctx = ctx or default_context()
    account = re.compile("|".join(rf"(?<![A-Za-z0-9-]){re.escape(o)}(?![A-Za-z0-9-])" for o in sorted(owners)), re.I) \
        if owners else None
    result = ScanResult()
    excluded = set(excluded)
    for path, text in files:
        if path in excluded:
            continue
        if KEY_FILE.search(path):
            result.hits.append(Hit(path, 0, "private_key", path, None))
        for n, line in enumerate(text.splitlines(), 1):
            finders = list(FINDERS.items()) + ([("account", account)] if account else [])
            for kind, finder in finders:
                for m in finder.finditer(line):
                    value = m.group(0)
                    result.hits.append(Hit(path, n, kind, value, categorize(path, line, kind, value, ctx)))
    return result


def repo_files(root: Path = ROOT) -> tuple[list[tuple[str, str]], int]:
    """(path, text) of every tracked text file, and how many binary files were skipped. -z keeps Chinese names."""
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True).stdout
    files, binary = [], 0
    for path in filter(None, out.decode("utf-8").split("\0")):
        try:
            data = (root / path).read_bytes()
        except FileNotFoundError:
            continue                               # deleted in the working tree, not committed yet
        try:
            files.append((path, data.decode("utf-8")))
        except UnicodeDecodeError:
            binary += 1
            files.append((path, KEY_MARK if b"PRIVATE KEY-----" in data else ""))
    return files, binary


def remote_owners(root: Path = ROOT) -> set[str]:
    """The owner part of every git remote of this repository (014 FR-016b: repo metadata, no user data)."""
    done = subprocess.run(["git", "remote", "-v"], cwd=root, capture_output=True, text=True)
    owners = set()
    for url in re.findall(r"\s(\S+)\s+\((?:fetch|push)\)", done.stdout):
        m = re.search(r"github\.com[:/]([^/]+)/", url)
        if m:
            owners.add(m.group(1))
    return owners


def render_doc(result: ScanResult) -> str:
    lines = [
        "# 個人資訊掃描的例外清單",
        "",
        "> 這份檔案由 `uv run python scripts/scan_personal.py --write` 產生，不要手改（feature 014，"
        "[contracts/scan-personal.md](../specs/014-publish-github/contracts/scan-personal.md)）。",
        "",
        "公開的檔案不能有任何人的 SteamID、本機資料夾、使用者資料夾、私人信箱、對話連結或私鑰；帳號名只能出現在授權的著作權行。"
        "這些只有下列地方允許；其他地方一出現，`tests/unit/test_scan_personal.py` 就會失敗。"
        "`HANDOFF.md` 不公開，不掃描。",
        "",
        "需要金鑰、本機資料庫或網路的檢查（金鑰的值、本人的 SteamID、願望清單的加入日期、NSFW 遊戲）只在發佈時執行，不在這份清單裡；"
        "它們沒有例外。",
        "",
        "每一處依下列規則由上而下歸類，取第一條符合的。各類的出現次數每次執行掃描時當場計算，不寫在這裡。",
    ]
    for n, rule in enumerate(RULES, 1):
        files = result.files(rule.key)
        lines += ["", f"## {n}. {rule.title}", "", f"- 適用：{'、'.join(rule.kinds)}", f"- 規則：{rule.rule}",
                  f"- 理由：{rule.reason}", "- 檔案：" + ("（目前沒有）" if not files else "")]
        lines += [f"  - `{f}`" for f in files]
    return "\n".join(lines) + "\n"


# --- publish-time kinds (contracts/scan-personal.md 「發佈時的類別」; 014 T027) --------------------------------------

NSFW = {3, 4}                                   # Steam content descriptors: adult only / frequent sexual content
APP_ID = re.compile(r'(?:"appid"\s*:\s*|"app_id"\s*:\s*|data-ds-appid="|store\.steampowered\.com/app/|app_id=)(\d{1,8})')
UNIX_TIME = re.compile(r"(?<!\d)(\d{10})(?!\d)")
MIN_ASCII_NAME, MIN_CJK_NAME = 8, 3              # shorter names are ordinary words ("Mirror", "Put in")
_CJK = re.compile(r"[^\x00-\x7f]")


def _usable_name(name: str) -> bool:
    return len(name) >= (MIN_CJK_NAME if _CJK.search(name) else MIN_ASCII_NAME)


def _name_in(name: str, line: str) -> bool:
    if _CJK.search(name):
        return name in line
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", line) is not None


def scan_publish(files: list[tuple[str, str]], *, owners: set[str], secrets: list[str], own_steamid: str | None,
                 wishlist_dates: set, product_names: dict[str, int], content_lookup) -> ScanResult:
    """The offline scan plus: key values (reported as ***), the owner's SteamID, the owner's wishlist dates, and
    games Steam marks as adult or frequent sexual content (by app id, or by a database name that cannot be an
    ordinary word: 8+ characters with word bounds, or 3+ with CJK). Every file is scanned: HANDOFF.md is skipped only
    on master, where it is never published; in a folder to publish it would be."""
    result = scan(files, owners=owners, excluded=())
    names = {n: a for n, a in product_names.items() if _usable_name(n)}
    found: dict[int, list[tuple[str, int]]] = {}
    for path, text in files:
        in_file = [(name, app) for name, app in names.items() if name in text]      # narrow first: fast
        for n, line in enumerate(text.splitlines(), 1):
            for secret in secrets:
                if secret and secret in line:
                    result.hits.append(Hit(path, n, "key", "***", None))
            if own_steamid and own_steamid in line:
                result.hits.append(Hit(path, n, "own_steamid", own_steamid, None))
            for m in UNIX_TIME.finditer(line):
                if int(m.group(1)) in wishlist_dates:
                    result.hits.append(Hit(path, n, "wishlist_date", m.group(1), None))
            for value in (d for d in wishlist_dates if isinstance(d, str) and d in line):
                result.hits.append(Hit(path, n, "wishlist_date", value, None))
            for m in APP_ID.finditer(line):
                found.setdefault(int(m.group(1)), []).append((path, n))
            for name, app in in_file:
                if name in line and _name_in(name, line):
                    found.setdefault(app, []).append((path, n))
    if found:
        descriptors = content_lookup(sorted(found))
        for app in sorted(found):
            if descriptors.get(app, set()) & NSFW:
                for path, n in dict.fromkeys(found[app]):
                    result.hits.append(Hit(path, n, "nsfw", f"app {app}", None))
    return result


def report(result: ScanResult, out: TextIO) -> None:
    for h in result.unallowed:
        print(f"{h.path}:{h.line_no}: {h.kind}: {h.value}", file=out)
    print(f"不允許的個人資訊：{len(result.unallowed)} 處", file=out)


def folder_files(folder: Path) -> list[tuple[str, str]]:
    """Every file a clone of the folder's repository would have: staged or not, minus what .gitignore leaves out
    (the test step's .venv/ and caches; 014 T055). Binary files are only checked for a private key."""
    out = subprocess.run(["git", "-C", str(folder), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                         capture_output=True, check=True).stdout
    files = []
    for rel in sorted(set(filter(None, out.decode("utf-8").split("\0")))):
        p = folder / rel
        if not p.is_file():
            continue                               # staged, then deleted from the working tree
        data = p.read_bytes()
        try:
            files.append((rel, data.decode("utf-8")))
        except UnicodeDecodeError:
            files.append((rel, KEY_MARK if b"PRIVATE KEY-----" in data else ""))
    return files


def steam_content_lookup(app_ids: list[int]) -> dict[int, set[int]]:
    """Content descriptor ids per app from the public GetItems (no key), 100 per request, 1.5 s apart."""
    import json
    import time

    import httpx

    found: dict[int, set[int]] = {}
    with httpx.Client(timeout=30, headers={"User-Agent": "SweetSpot publish check"}) as client:
        for start in range(0, len(app_ids), 100):
            body = {"ids": [{"appid": a} for a in app_ids[start:start + 100]],
                    "context": {"language": "english", "country_code": "TW"}, "data_request": {"include_basic_info": True}}
            response = client.get("https://api.steampowered.com/IStoreBrowseService/GetItems/v1/",
                                  params={"input_json": json.dumps(body)})
            response.raise_for_status()
            for item in response.json().get("response", {}).get("store_items", []):
                found[int(item.get("appid") or item.get("id"))] = set(item.get("content_descriptorids") or [])
            time.sleep(1.5)
    return found


def publish_inputs(root: Path = ROOT) -> dict:
    """The owner's values for --publish, read here and never written anywhere: keys from the environment, the
    SteamID from sweetspot.toml, wishlist dates and product names from data/sweetspot.db (read-only)."""
    import json
    import sqlite3
    from datetime import datetime

    sys.path.insert(0, str(root / "src"))
    from sweetspot.config import load_secrets

    own = None
    toml = root / "sweetspot.toml"
    if toml.exists():
        m = re.search(r"/profiles/(\d{17})/", toml.read_text(encoding="utf-8"))
        own = m.group(1) if m else None
    dates: set = set()
    names: dict[str, int] = {}
    db = root / "data" / "sweetspot.db"
    if db.exists():
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        try:
            for (value,) in conn.execute("SELECT DISTINCT date_added FROM wishlist_items WHERE date_added IS NOT NULL"):
                dates.add(value[:19])
                try:
                    dates.add(int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()))
                except ValueError:
                    pass
            for app, value in conn.execute("SELECT app_id, value_json FROM product_facts WHERE field = 'name'"):
                try:
                    name = json.loads(value)
                except ValueError:
                    continue
                if isinstance(name, str):
                    names[name] = app
        finally:
            conn.close()
    return dict(owners=remote_owners(root), secrets=load_secrets().redaction_values(), own_steamid=own,
                wishlist_dates=dates, product_names=names, content_lookup=steam_content_lookup)


def main(argv: list[str] | None = None, files: list[tuple[str, str]] | None = None, owners: set[str] | None = None,
         out: TextIO | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="regenerate docs/personal-scan.md")
    parser.add_argument("--publish", type=Path, metavar="DIR", help="publish check of a folder (needs the network)")
    args = parser.parse_args(argv)
    out = out or sys.stdout
    if args.publish is not None:
        try:
            files = folder_files(args.publish)
            result = scan_publish(files, **publish_inputs(ROOT))
        except Exception as exc:  # noqa: BLE001 - not a git folder, local values or the online lookup failed
            print(f"發佈檢查不能判定（{type(exc).__name__}: {exc}）；視同不通過", file=out)
            return 2
        if result.unallowed:
            report(result, out)
            return 1
        print(f"發佈檢查：{len(files)} 個檔案，不允許 0", file=out)
        return 0
    binary = 0
    if files is None:
        files, binary = repo_files(ROOT)
    owners = remote_owners(ROOT) if owners is None else owners
    result = scan(files, owners=owners)
    if result.unallowed:
        report(result, out)
        return 1
    for rule in RULES:
        count = sum(1 for h in result.hits if h.category == rule.key)
        print(f"{rule.title}：{count} 處，{len(result.files(rule.key))} 個檔案", file=out)
    print(f"共 {len(result.hits)} 處，掃描 {len(files)} 個檔案（{binary} 個二進位檔只查私鑰）；不允許 0", file=out)
    if args.write:
        (ROOT / DOC).write_text(render_doc(result), encoding="utf-8", newline="\n")
        print(f"已更新 {DOC.as_posix()}", file=out)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
