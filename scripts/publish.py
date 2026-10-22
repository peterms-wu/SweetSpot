"""Publish master as a snapshot commit of the public repository (feature 014 US4; contracts/publish.md).

    uv run python scripts/publish.py [--to FOLDER] [--dry-run] [--message-file FILE]

Master is the only source; the public repository is its publish snapshots: master's committed files, minus
EXCLUDED, replace the public folder's files, the personal-information scan and the tests run there, and only then one
commit is made, by the GitHub noreply address. A tag publish/NNN on master records which master commit it was. Nothing
is pushed: the next commands are printed for the owner to run after checking (FR-017).
"""

import argparse
import importlib.util
import io
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {"HANDOFF.md"}                      # FR-009: never published
REPO_NAME = "SweetSpot"
TAG = re.compile(r"^publish/(\d{3})$")
TOOLS = ("uv", "node")                         # the test step's (step 4)


def _scan_pattern(kind: str) -> re.Pattern:
    """One of the personal scan's own patterns, so the two never drift apart."""
    spec = importlib.util.spec_from_file_location("scan_personal", ROOT / "scripts" / "scan_personal.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.FINDERS[kind]


SESSION_LINK = _scan_pattern("session")        # FR-016: no conversation link in the public commit message


class Refused(Exception):
    pass


def git(cwd: Path, *args: str, check: bool = True) -> str:
    done = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, encoding="utf-8")
    if check and done.returncode != 0:
        raise Refused(f"git {' '.join(args[:2])}：{done.stderr.strip() or done.stdout.strip()}")
    return done.stdout.strip()


def last_tag(source: Path) -> str | None:
    tags = sorted(t for t in git(source, "tag", "--list", "publish/*").split() if TAG.match(t))
    return tags[-1] if tags else None


def recorded_public_commit(source: Path, tag: str) -> str:
    m = re.search(r"public ([0-9a-f]{40})", git(source, "tag", "-l", "--format=%(contents)", tag))
    if not m:
        raise Refused(f"{tag} 的訊息裡沒有公開 commit")
    return m.group(1)


def check_source(source: Path) -> None:
    if git(source, "rev-parse", "--abbrev-ref", "HEAD") != "master":
        raise Refused("要在 master 上發佈（目前不是 master）")
    if git(source, "status", "--porcelain"):
        raise Refused("工作目錄有沒有提交的修改；發佈的是已提交的內容，請先 commit 或移開")


def check_target(source: Path, target: Path, tag: str | None) -> None:
    if not target.exists():
        if tag is not None:
            raise Refused(f"已經發佈過（{tag}），但公開資料夾 {target} 不存在")
        return
    if not (target / ".git").exists():
        raise Refused(f"{target} 不是 git repo")
    if git(target, "status", "--porcelain"):
        raise Refused(f"公開資料夾 {target} 有沒有提交的修改")
    if tag is None:
        raise Refused(f"還沒發佈過，但公開資料夾 {target} 已經存在；第一次發佈要用新的資料夾")
    if git(target, "rev-parse", "HEAD") != recorded_public_commit(source, tag):
        raise Refused(f"公開資料夾最新的 commit 不是 {tag} 記錄的那一個（有人在公開資料夾手動改過）")


def export(source: Path, target: Path) -> None:
    """Master's committed files, minus EXCLUDED, replace everything in target except .git/ (and ignored files)."""
    data = subprocess.run(["git", "-C", str(source), "archive", "--format=tar", "HEAD"], capture_output=True,
                          check=True).stdout
    tracked = set(filter(None, git(target, "ls-files", "-z").split("\0"))) if (target / ".git").exists() else set()
    for rel in tracked:                                     # removed on master -> removed here; ignored files stay
        (target / rel).unlink(missing_ok=True)
    with tempfile.TemporaryDirectory() as tmp, tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(tmp, filter="data")
        for path in sorted(Path(tmp).rglob("*")):
            rel = path.relative_to(tmp).as_posix()
            if not path.is_file() or rel in EXCLUDED:
                continue
            dest = target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            # not copy2: git archive stamps every file with the commit time, so a same-size change committed
            # within the same second as the last publish would look unchanged to git (its stat check)
            shutil.copy(path, dest)
    for d in sorted((p for p in target.rglob("*") if p.is_dir() and ".git" not in p.parts), reverse=True):
        if not any(d.iterdir()):
            d.rmdir()


def draft_message(source: Path, tag: str | None, today: date) -> str:
    if tag is None:
        return f"SweetSpot 初次公開（{today.isoformat()}）\n"
    subjects = git(source, "log", "--reverse", "--format=%s", f"{tag}..HEAD").splitlines()
    return f"SweetSpot 發佈 {today.isoformat()}\n\n" + "".join(f"- {s}\n" for s in subjects)


def _remove_read_only(func, path, _exc) -> None:
    """git writes its objects read-only; on Windows rmtree cannot delete them until that is cleared."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def restore(target: Path, first: bool, committed: bool = False) -> None:
    """Back to how the public folder was before this run; `committed`: the new public commit is taken back too."""
    if first:
        if target.exists():
            shutil.rmtree(target, onexc=_remove_read_only)
        return
    git(target, "reset", "-q", "--hard", "HEAD~1" if committed else "HEAD")
    git(target, "clean", "-q", "-fd")


def check_tools(which: Callable[[str], str | None], gh_user: Callable[[], tuple[int, str]]) -> tuple[int, str]:
    """§1: uv and node for the test step, and the GitHub account from gh, before anything is made (014 T058)."""
    missing = [tool for tool in TOOLS if which(tool) is None]
    if missing:
        raise Refused(f"找不到 {'、'.join(missing)}（測試步驟要用）")
    try:
        return gh_user()
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        raise Refused(f"gh 讀不到 GitHub 帳號（{type(exc).__name__}: {exc}）；請先安裝 gh 並執行 gh auth login") from None


def check_message(message: str) -> None:
    link = SESSION_LINK.search(message)
    if link:
        raise Refused(f"commit 訊息有對話連結（{link.group(0)}）；公開 commit 不放對話連結（FR-016），請用 --message-file 改寫")


def publish(source: Path, target: Path, *, gh_user: Callable[[], tuple[int, str]], scanner: Callable[[Path], int],
            tester: Callable[[Path], int], dry_run: bool, message_file: Path | None, today: date,
            say: Callable[[str], None], which: Callable[[str], str | None] = shutil.which) -> int:
    try:
        check_source(source)
        tag = last_tag(source)
        check_target(source, target, tag)
        if tag is not None and git(source, "rev-list", "-n", "1", tag) == git(source, "rev-parse", "HEAD"):
            say(f"master 沒有新的內容（{tag} 之後沒有 commit），不發佈")
            return 0
        user_id, login = check_tools(which, gh_user)
        message = message_file.read_text(encoding="utf-8") if message_file else draft_message(source, tag, today)
        check_message(message)
    except (Refused, OSError) as exc:
        say(f"不發佈：{exc}")
        return 1
    first = not target.exists()
    committed = False
    try:
        if first:
            target.mkdir(parents=True)
            git(target, "init", "-q", "-b", "main")
            # the remote a clone of the public repo has: the scan finds the account name on the LICENSE line through it
            git(target, "remote", "add", "origin", f"https://github.com/{login}/{REPO_NAME}.git")
        export(source, target)
        git(target, "add", "-A")                       # staged: the tests' `git ls-files` sees what a clone would
        changes = git(target, "status", "--porcelain", "--untracked-files=all").splitlines()
        if not changes:                                # e.g. only HANDOFF.md changed since the last publish
            say(f"master 在 {tag} 之後的 commit 沒有改到公開的檔案（匯出的內容和上次發佈相同），不發佈")
            restore(target, first)
            return 0
        say(f"{'初次公開' if first else '這次發佈'}：{len(changes)} 個檔案有變動")
        for line in changes[:40]:
            say(f"  {line}")
        if len(changes) > 40:
            say(f"  …另外 {len(changes) - 40} 個")
        say("訊息：")
        say(message.rstrip())
        code = scanner(target)
        if code != 0:
            say(f"掃描沒有通過（結束代碼 {code}），不發佈")
            restore(target, first)
            return 1
        code = tester(target)
        if code != 0:
            say(f"公開資料夾的測試沒有通過（結束代碼 {code}），不發佈")
            restore(target, first)
            return 1
        if dry_run:
            say("（--dry-run：沒有 commit、沒有 tag；公開資料夾已回到原樣）")
            restore(target, first)
            return 0
        email = f"{user_id}+{login}@users.noreply.github.com"
        git(target, "config", "user.name", login)
        git(target, "config", "user.email", email)
        git(target, "config", "commit.gpgsign", "false")
        git(target, "add", "-A")
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as f:
            f.write(message)
        try:
            git(target, "commit", "-q", "-F", f.name)
            committed = True
        finally:
            Path(f.name).unlink(missing_ok=True)
        public = git(target, "rev-parse", "HEAD")
        number = int(TAG.match(tag).group(1)) + 1 if tag else 1
        new_tag = f"publish/{number:03d}"
        scope = f"{tag}..{git(source, 'rev-parse', '--short', 'HEAD')}" if tag else "初次公開"
        try:                                           # a commit without its tag would refuse every later publish
            git(source, "tag", "-a", new_tag, "-m",
                f"public {public}\n{datetime.now().astimezone().isoformat(timespec='seconds')}\n範圍：{scope}")
        except Refused as exc:
            raise Refused(f"打 {new_tag} 失敗，公開 commit 已撤回（{exc}）") from None
    except (Refused, OSError, subprocess.CalledProcessError) as exc:
        say(f"發佈失敗：{exc}")
        restore(target, first, committed)
        return 1
    say(f"已建立公開 commit {public[:12]}，master 打上 {new_tag}；沒有推送任何東西。")
    say("確認後的下一步：")
    if first:
        say(f"  gh repo create {login}/{REPO_NAME} --public       # 建立空的公開 repo")
        say(f"  git -C \"{target}\" push -u origin main")
    else:
        say(f"  git -C \"{target}\" push")
    say("  git push private --tags        # 把發佈紀錄備份到私人 repo")
    return 0


# --- the real gh, scan and tests ------------------------------------------------------------------------------------

def real_gh_user() -> tuple[int, str]:
    out = subprocess.run(["gh", "api", "user", "--jq", ".id,.login"], capture_output=True, text=True, check=True)
    user_id, login = out.stdout.split()
    return int(user_id), login


def real_scanner(folder: Path) -> int:
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "scan_personal.py"), "--publish", str(folder)],
                          cwd=ROOT).returncode


def real_tester(folder: Path) -> int:
    for args in (["uv", "sync", "-q"], ["uv", "run", "pytest", "-q"], ["node", "--test", "tests/extension/*.test.js"]):
        code = subprocess.run(args, cwd=folder).returncode
        if code != 0:
            return code
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--to", type=Path, default=ROOT.parent / "SweetSpot-public", help="the public folder")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--message-file", type=Path)
    args = parser.parse_args(argv)
    return publish(ROOT, args.to.resolve(), gh_user=real_gh_user, scanner=real_scanner, tester=real_tester,
                   dry_run=args.dry_run, message_file=args.message_file, today=date.today(),
                   say=lambda line: print(line, flush=True))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
