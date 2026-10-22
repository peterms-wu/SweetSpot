"""014 T039: the publish step (contracts/publish.md; FR-016–FR-018a, SC-005). A temporary git repository stands in for
master; gh, the scan and the tests are fakes, and nothing is pushed anywhere."""

import importlib.util
import io
import subprocess
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location("publish", ROOT / "scripts" / "publish.py")
publish = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(publish)

NOREPLY = "1234567+someone@users.noreply.github.com"


def git(cwd, *args, check=True):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=check,
                          encoding="utf-8").stdout.strip()


@pytest.fixture
def master(tmp_path):
    src = tmp_path / "SweetSpot"
    src.mkdir()
    git(src, "init", "-q", "-b", "master")
    git(src, "config", "user.name", "Owner")
    git(src, "config", "user.email", "owner@example.com")
    git(src, "config", "commit.gpgsign", "false")
    (src / "README.md").write_text("# SweetSpot\n", encoding="utf-8")
    (src / "HANDOFF.md").write_text("private notes\n", encoding="utf-8")
    (src / "src").mkdir()
    (src / "src" / "a.py").write_text("A = 1\n", encoding="utf-8")
    (src / "src" / "gone.py").write_text("G = 1\n", encoding="utf-8")
    git(src, "add", "-A")
    git(src, "commit", "-q", "-m", "first", "-m", "Claude-Session: https://claude.ai/code/" + "session_x")
    return src


class Fakes:
    def __init__(self, scan=0, tests=0):
        self.scan_code, self.test_code = scan, tests
        self.scanned, self.tested = [], []

    def gh_user(self):
        return 1234567, "someone"

    def scanner(self, folder):
        self.scanned.append(sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*")
                                   if p.is_file() and ".git" not in p.parts))
        return self.scan_code

    def tester(self, folder):
        self.tested.append(folder)
        self.tracked = sorted(git(folder, "ls-files").splitlines())    # the scans' tests read git ls-files
        return self.test_code


def run(master, target, fakes, **kw):
    out = io.StringIO()
    code = publish.publish(master, target, gh_user=kw.get("gh_user", fakes.gh_user), scanner=fakes.scanner,
                           tester=fakes.tester, dry_run=kw.get("dry_run", False), message_file=kw.get("message_file"),
                           today=date(2026, 10, 20), say=lambda line: print(line, file=out),
                           which=kw.get("which", lambda tool: f"fake-{tool}"))
    return code, out.getvalue()


def files(folder):
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file() and ".git" not in p.parts)


def test_first_publish_is_one_noreply_commit_without_handoff(master, tmp_path):
    target = tmp_path / "SweetSpot-public"
    head = git(master, "rev-parse", "HEAD")
    code, out = run(master, target, Fakes())
    assert code == 0
    assert git(target, "rev-list", "--count", "HEAD") == "1"
    assert git(target, "log", "-1", "--format=%an <%ae>|%cn <%ce>") == f"someone <{NOREPLY}>|someone <{NOREPLY}>"
    message = git(target, "log", "-1", "--format=%B")
    assert message.startswith("SweetSpot 初次公開") and "claude.ai" not in message
    assert files(target) == ["README.md", "src/a.py", "src/gone.py"]
    tag = git(master, "tag", "--list", "publish/*")
    assert tag == "publish/001"
    assert git(master, "rev-list", "-n", "1", "publish/001") == head
    assert git(target, "rev-parse", "HEAD") in git(master, "tag", "-l", "--format=%(contents)", "publish/001")
    assert "gh repo create someone/SweetSpot --public" in out and "push -u origin main" in out
    assert git(target, "remote", "get-url", "origin") == "https://github.com/someone/SweetSpot.git"


def test_second_publish_adds_one_commit_with_changes_and_deletions(master, tmp_path):
    target = tmp_path / "SweetSpot-public"
    run(master, target, Fakes())
    (master / "src" / "a.py").write_text("A = 2\n", encoding="utf-8")
    (master / "src" / "gone.py").unlink()
    (master / "src" / "new.py").write_text("N = 1\n", encoding="utf-8")
    git(master, "add", "-A")
    git(master, "commit", "-q", "-m", "change a, drop gone, add new")
    code, out = run(master, target, Fakes())
    assert code == 0
    assert git(target, "rev-list", "--count", "HEAD") == "2"
    assert files(target) == ["README.md", "src/a.py", "src/new.py"]
    assert (target / "src" / "a.py").read_text(encoding="utf-8") == "A = 2\n"
    assert "change a, drop gone, add new" in git(target, "log", "-1", "--format=%B")
    assert git(master, "tag", "--list", "publish/*").split() == ["publish/001", "publish/002"]
    assert "git -C" in out and "push" in out and "git push private --tags" in out


def test_only_committed_content_is_published(master, tmp_path):
    (master / "src" / "a.py").write_text("UNCOMMITTED\n", encoding="utf-8")
    code, out = run(master, tmp_path / "pub", Fakes())
    assert code == 1 and "沒有提交" in out                     # a dirty working tree is refused
    git(master, "checkout", "--", "src/a.py")
    code, _ = run(master, tmp_path / "pub", Fakes())
    assert code == 0 and (tmp_path / "pub" / "src" / "a.py").read_text(encoding="utf-8") == "A = 1\n"


def test_must_be_on_master(master, tmp_path):
    git(master, "checkout", "-q", "-b", "feature")
    code, out = run(master, tmp_path / "pub", Fakes())
    assert code == 1 and "master" in out and not (tmp_path / "pub").exists()


def test_a_hand_edited_public_folder_is_refused(master, tmp_path):
    target = tmp_path / "pub"
    run(master, target, Fakes())
    (target / "README.md").write_text("edited by hand\n", encoding="utf-8")
    git(target, "add", "-A")
    git(target, "-c", "user.name=x", "-c", "user.email=x@example.com", "commit", "-q", "-m", "hand edit")
    code, out = run(master, target, Fakes())
    assert code == 1 and "publish/001" in out


@pytest.mark.parametrize("which", ["scan", "tests"])
def test_a_failed_check_leaves_no_commit_no_tag_and_restores_the_folder(master, tmp_path, which):
    target = tmp_path / "pub"
    run(master, target, Fakes())
    (master / "src" / "a.py").write_text("A = 3\n", encoding="utf-8")
    git(master, "commit", "-q", "-am", "three")
    fakes = Fakes(scan=1) if which == "scan" else Fakes(tests=1)
    code, out = run(master, target, fakes)
    assert code == 1
    assert git(target, "rev-list", "--count", "HEAD") == "1"
    assert (target / "src" / "a.py").read_text(encoding="utf-8") == "A = 1\n"
    assert git(master, "tag", "--list", "publish/*") == "publish/001"
    assert git(target, "status", "--porcelain") == ""


def test_a_same_size_change_in_the_same_second_is_published(master, tmp_path):
    """Regression (2026-10-22): git archive stamps every file with the commit time; copied with that time, a same-size
    change committed in the same second as the last publish looked unchanged to git's stat check, so it was neither
    published nor restored after a failed check (the test above failed now and then)."""
    import os

    target = tmp_path / "pub"
    run(master, target, Fakes())
    (master / "src" / "a.py").write_text("A = 3\n", encoding="utf-8")       # same size as "A = 1\n"
    when = git(master, "log", "-1", "--format=%cI")
    env = {**os.environ, "GIT_COMMITTER_DATE": when, "GIT_AUTHOR_DATE": when}
    subprocess.run(["git", "-C", str(master), "commit", "-q", "-am", "same second"], check=True, env=env)
    code, out = run(master, target, Fakes())
    assert code == 0 and "1 個檔案有變動" in out
    assert git(target, "show", "HEAD:src/a.py") == "A = 3"


def test_a_failed_first_publish_removes_the_new_folder(master, tmp_path):
    code, _ = run(master, tmp_path / "pub", Fakes(scan=2))
    assert code == 1 and not (tmp_path / "pub").exists()
    assert git(master, "tag", "--list", "publish/*") == ""


def test_dry_run_changes_nothing(master, tmp_path):
    target = tmp_path / "pub"
    code, out = run(master, target, Fakes(), dry_run=True)
    assert code == 0 and not target.exists() and git(master, "tag", "--list") == ""
    assert "README.md" in out and "HANDOFF.md" not in out and "SweetSpot 初次公開" in out


def test_the_scan_and_the_tests_see_the_exported_files(master, tmp_path):
    fakes = Fakes()
    run(master, tmp_path / "pub", fakes)
    assert fakes.scanned == [["README.md", "src/a.py", "src/gone.py"]] and fakes.tested == [tmp_path / "pub"]
    assert fakes.tracked == ["README.md", "src/a.py", "src/gone.py"]     # staged before the tests, as in a clone


def test_master_files_and_head_do_not_change(master, tmp_path):
    before = (git(master, "rev-parse", "HEAD"), git(master, "status", "--porcelain"), files(master))
    run(master, tmp_path / "pub", Fakes())
    assert (git(master, "rev-parse", "HEAD"), git(master, "status", "--porcelain"), files(master)) == before


def test_message_file_replaces_the_draft(master, tmp_path):
    msg = tmp_path / "msg.txt"
    msg.write_text("SweetSpot 初次公開\n\n自己寫的說明\n", encoding="utf-8")
    run(master, tmp_path / "pub", Fakes(), message_file=msg)
    assert git(tmp_path / "pub", "log", "-1", "--format=%B").strip() == "SweetSpot 初次公開\n\n自己寫的說明"


# --- found by the spec drift audit of 2026-10-22 (014 T058) --------------------------------------------------------

@pytest.mark.parametrize("error", [FileNotFoundError(2, "gh not found"),
                                   subprocess.CalledProcessError(1, ["gh", "api", "user"]),
                                   ValueError("not enough values to unpack")])
def test_gh_is_checked_before_anything_is_made(master, tmp_path, error):
    """The first publish asked gh inside the try; on failure restore() removed a folder not made yet: a traceback."""
    def gh_user():
        raise error

    fakes = Fakes()
    code, out = run(master, tmp_path / "pub", fakes, gh_user=gh_user)
    assert code == 1 and "gh auth login" in out and not (tmp_path / "pub").exists()
    assert fakes.scanned == [] and git(master, "tag", "--list") == ""


def test_uv_and_node_are_checked_before_anything_is_made(master, tmp_path):
    fakes = Fakes()
    code, out = run(master, tmp_path / "pub", fakes, which=lambda tool: None if tool == "node" else "x")
    assert code == 1 and "node" in out and not (tmp_path / "pub").exists() and fakes.scanned == []


@pytest.mark.parametrize("first", [True, False])
def test_a_failed_tag_takes_the_public_commit_back(master, tmp_path, first):
    """A tag that cannot be made (here: tags must be signed, by a gpg that is not there) left a public commit with no
    tag; every later publish was then refused as a hand edit."""
    target = tmp_path / "pub"
    if not first:
        run(master, target, Fakes())
        (master / "src" / "a.py").write_text("A = 3\n", encoding="utf-8")
        git(master, "commit", "-q", "-am", "three")
    git(master, "config", "tag.gpgSign", "true")
    git(master, "config", "gpg.program", str(tmp_path / "no-such-gpg"))
    code, out = run(master, target, Fakes())
    assert code == 1 and "tag" in out
    assert git(master, "tag", "--list", "publish/*") == ("" if first else "publish/001")
    if first:
        assert not target.exists()
    else:
        assert git(target, "rev-list", "--count", "HEAD") == "1" and git(target, "status", "--porcelain") == ""
        assert (target / "src" / "a.py").read_text(encoding="utf-8") == "A = 1\n"


def test_a_change_of_handoff_only_publishes_nothing(master, tmp_path):
    """HANDOFF.md is not published: commits that touch only it export nothing new (it used to run the scan and the
    tests, then fail on an empty commit)."""
    target = tmp_path / "pub"
    run(master, target, Fakes())
    (master / "HANDOFF.md").write_text("more private notes\n", encoding="utf-8")
    git(master, "commit", "-q", "-am", "handoff")
    fakes = Fakes()
    code, out = run(master, target, fakes)
    assert code == 0 and "和上次發佈相同" in out and fakes.scanned == []
    assert git(target, "rev-list", "--count", "HEAD") == "1" and git(master, "tag", "--list", "publish/*") == "publish/001"
    assert git(target, "status", "--porcelain") == ""


@pytest.mark.parametrize("where", ["message_file", "subject"])
def test_a_conversation_link_in_the_message_is_refused(master, tmp_path, where):
    """FR-016: the public commit message never holds a conversation link (it was left to the commit subjects)."""
    link = "https://claude.ai/code/" + "session_01AbCdEf"
    target = tmp_path / "pub"
    kw = {}
    if where == "message_file":
        msg = tmp_path / "msg.txt"
        msg.write_text(f"SweetSpot 初次公開\n\n{link}\n", encoding="utf-8")
        kw["message_file"] = msg
    else:
        run(master, target, Fakes())
        (master / "src" / "a.py").write_text("A = 3\n", encoding="utf-8")
        git(master, "commit", "-q", "-am", f"see {link}")
    before = target.exists() and git(target, "rev-parse", "HEAD")
    fakes = Fakes()
    code, out = run(master, target, fakes, **kw)
    assert code == 1 and "對話連結" in out and fakes.scanned == []
    assert (target.exists() and git(target, "rev-parse", "HEAD")) == before


def test_nothing_new_publishes_nothing(master, tmp_path):
    target = tmp_path / "pub"
    run(master, target, Fakes())
    code, out = run(master, target, Fakes())
    assert code == 0 and "沒有新的內容" in out
    assert git(target, "rev-list", "--count", "HEAD") == "1"
    assert git(master, "tag", "--list", "publish/*") == "publish/001"
