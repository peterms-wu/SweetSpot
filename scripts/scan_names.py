"""Find the pre-016 name in every tracked file; only the rule table below may allow one (feature 016 US4, FR-013/14).

    uv run python scripts/scan_names.py           # list unallowed hits (exit 1) or the count per category (exit 0)
    uv run python scripts/scan_names.py --write   # also regenerate docs/legacy-names.md from the scan

The rule table is contracts/scan.md section 2 (specs/016-rename-internal-ids/). The first rule that matches a hit
decides its category; a hit no rule matches is not allowed. tests/unit/test_scan_names.py runs the scan on the
repository and holds a sample that must match and one that must not for every rule.
"""

import argparse
import re
import subprocess
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

ROOT = Path(__file__).resolve().parents[1]
DOC = Path("docs") / "legacy-names.md"
OLD = re.compile(r"steamsage", re.I)
KEPT = [re.compile(r"steamsage\.[a-z][a-z-]*/\d+"), re.compile(r"steamsage-004-split"),
        re.compile(r"steamsage_version\b")]
OLD_NAME_LINE = re.compile(r"舊名|formerly", re.I)
PREDECESSOR_LINE = re.compile(r"前身|舊專案|legacy", re.I)
PREDECESSOR_PATH = re.compile(r"[\\/]{1,2}[A-Za-z]")       # 〈前身專案資料夾〉\state, not a regex escape \.


@dataclass(frozen=True)
class Hit:
    path: str
    line_no: int
    line: str
    start: int
    category: str | None


@dataclass(frozen=True)
class Rule:
    key: str
    title: str
    rule: str
    reason: str
    whole_path: bool = False                     # the document lists the rule only, not every file
    path: Callable[[str], bool] | None = None
    hit: Callable[[str, int], bool] | None = None    # (line, start of the hit)


def _in_kept(line: str, start: int) -> bool:
    return any(m.start() <= start < m.end() for pattern in KEPT for m in pattern.finditer(line))


def _predecessor(line: str, start: int) -> bool:
    if line[start:start + 9] != "SteamSage" or line[start + 9:start + 10].isalnum():
        return False
    return bool(PREDECESSOR_LINE.search(line)) or bool(PREDECESSOR_PATH.match(line, start + 9))


def _migration_path(p: str) -> bool:
    name = p.rsplit("/", 1)[-1]
    return p in ("src/sweetspot/legacy.py", "src/sweetspot/migrate.py") or \
        (p.startswith("tests/") and ("migrate" in name or "legacy_names" in name))


RULES = [
    Rule("history", "歷史文件", "路徑在 `specs/` 下",
         "過去 feature 的 spec、plan、原型腳本是當時的紀錄，不改寫（016 spec Assumptions）", True,
         path=lambda p: p.startswith("specs/")),
    Rule("handoff", "交接紀錄", "路徑是 `HANDOFF.md`",
         "歷史段落保留當時的名稱；操作步驟由 016 改成新名稱（FR-005）；014 不公開這份檔案", True,
         path=lambda p: p == "HANDOFF.md"),
    Rule("comparisons", "只附加的比較紀錄", "路徑是 `docs/model/comparisons.md`",
         "「只附加、不修改」（003 FR-030）；舊紀錄中的指令是當時實際執行的指令", True,
         path=lambda p: p == "docs/model/comparisons.md"),
    Rule("scan", "掃描本身", "路徑是 `scripts/scan_names.py`、`docs/legacy-names.md`、`tests/unit/test_scan_names.py`",
         "規則與樣本本身必須寫出舊名",
         path=lambda p: p in ("scripts/scan_names.py", "docs/legacy-names.md", "tests/unit/test_scan_names.py")),
    Rule("migration", "搬家與舊名稱保護",
         "路徑是 `src/sweetspot/legacy.py`、`src/sweetspot/migrate.py`，或 `tests/` 下檔名含 `migrate` 或 `legacy_names`",
         "要認得舊檔名才能搬家，以及在只有舊檔時拒絕執行", path=_migration_path),
    Rule("gitignore", "忽略舊名稱的檔案", "路徑是 `.gitignore`",
         "舊名的設定檔與資料庫在搬家前後都不能被誤加進版控", path=lambda p: p == ".gitignore"),
    Rule("data-id", "資料識別碼",
         "該處是格式名稱 `steamsage.<名稱>/<版本>`、分組依據 `steamsage-004-split` 或紀錄欄位 `steamsage_version`",
         "寫在只新增不修改的紀錄裡，或決定回測資料集（016 FR-006、contracts/names.md §2）",
         hit=_in_kept),
    Rule("old-name", "舊名稱說明", "該行含「舊名」或「formerly」",
         "README、憲章、套件說明中說明舊名稱（016 FR-005）", hit=lambda line, start: bool(OLD_NAME_LINE.search(line))),
    Rule("predecessor", "前身專案",
         "大小寫相同的 `SteamSage`、後面不是 `2`，而且該行含「前身」「舊專案」「legacy」之一，"
         "或後面接一或兩個 `\\`／`/` 再接英文字母（路徑的一段）",
         "前身專案 SteamSage 的名稱與它的快取路徑，不是本專案的識別碼；正規表示式的跳脫 `SteamSage\\.` 不算路徑",
         hit=_predecessor),
]


@dataclass
class ScanResult:
    hits: list[Hit] = field(default_factory=list)

    @property
    def unallowed(self) -> list[Hit]:
        """One per line that has at least one hit no rule allows."""
        seen, out = set(), []
        for h in self.hits:
            if h.category is None and (h.path, h.line_no) not in seen:
                seen.add((h.path, h.line_no))
                out.append(h)
        return out

    def files(self, key: str) -> list[str]:
        return sorted({h.path for h in self.hits if h.category == key})


def categorize(path: str, line: str, start: int) -> str | None:
    for rule in RULES:
        if rule.path is not None and rule.path(path):
            return rule.key
        if rule.hit is not None and rule.hit(line, start):
            return rule.key
    return None


def scan(files: Iterable[tuple[str, str]]) -> ScanResult:
    result = ScanResult()
    for path, text in files:
        for n, line in enumerate(text.splitlines(), 1):
            for m in OLD.finditer(line):
                result.hits.append(Hit(path, n, line.strip(), m.start(), categorize(path, line, m.start())))
    return result


def repo_files(root: Path = ROOT) -> tuple[list[tuple[str, str]], int]:
    """(path, text) of every tracked text file, and how many binary files were skipped. -z keeps Chinese names."""
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True).stdout
    files, binary = [], 0
    for path in filter(None, out.decode("utf-8").split("\0")):
        try:
            files.append((path, (root / path).read_bytes().decode("utf-8")))
        except UnicodeDecodeError:
            binary += 1
        except FileNotFoundError:
            pass                                   # deleted in the working tree, not committed yet
    return files, binary


def render_doc(result: ScanResult) -> str:
    lines = [
        "# 舊名稱與例外清單",
        "",
        "> 這份檔案由 `uv run python scripts/scan_names.py --write` 產生，不要手改（feature 016，"
        "[contracts/scan.md](../specs/016-rename-internal-ids/contracts/scan.md)）。",
        "",
        "專案的舊名是 SteamSage2（2026-09-28 改名為 SweetSpot）；feature 016 之前，程式的指令、套件、設定檔、資料庫、日誌與"
        "擴充功能內部仍用舊名 `steamsage`，016 起全部改為 `sweetspot`（對照見 "
        "[contracts/names.md](../specs/016-rename-internal-ids/contracts/names.md)）。",
        "",
        "版本控制中的檔案只有下列地方允許留下舊名；其他地方一出現，`tests/unit/test_scan_names.py` 就會失敗。"
        "寫在已保存紀錄裡的資料識別碼（格式名稱、004 的分組依據、紀錄欄位）刻意保留舊名：改了，舊紀錄就讀不懂、回測資料集也會改變。",
        "",
        "每一處依下列規則由上而下歸類，取第一條符合的。各類的出現次數每次執行掃描時當場計算，不寫在這裡。",
    ]
    for n, rule in enumerate(RULES, 1):
        lines += ["", f"## {n}. {rule.title}", "", f"- 規則：{rule.rule}", f"- 理由：{rule.reason}"]
        if rule.whole_path:
            lines.append("- 檔案：整個路徑都是例外，不逐檔列出")
        else:
            files = result.files(rule.key)
            lines.append("- 檔案：" + ("（目前沒有）" if not files else ""))
            lines += [f"  - `{f}`" for f in files]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None, files: list[tuple[str, str]] | None = None, out: TextIO | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="regenerate docs/legacy-names.md")
    args = parser.parse_args(argv)
    out = out or sys.stdout
    binary = 0
    if files is None:
        files, binary = repo_files(ROOT)
    result = scan(files)
    if result.unallowed:
        for h in result.unallowed:
            print(f"{h.path}:{h.line_no}: {h.line}", file=out)
        print(f"未允許的舊名：{len(result.unallowed)} 行", file=out)
        return 1
    for rule in RULES:
        count = sum(1 for h in result.hits if h.category == rule.key)
        print(f"{rule.title}：{count} 處，{len(result.files(rule.key))} 個檔案", file=out)
    print(f"共 {len(result.hits)} 處，掃描 {len(files)} 個文字檔，略過 {binary} 個二進位檔；未允許 0", file=out)
    if args.write:
        (ROOT / DOC).write_text(render_doc(result), encoding="utf-8", newline="\n")
        print(f"已更新 {DOC.as_posix()}", file=out)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
