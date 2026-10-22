"""014 T063: what feature 014 added that the code can enumerate is written in its contracts.

Options, actions, exit codes, values and variables are listed from the code, never by hand, and each must appear in
the contract as a word of its own. Behaviour (what an option does, when a code is used) is beyond a list: the spec
drift audit finds those (specs/014-publish-github/audit-2026-10-22.md).
"""

import argparse
import contextlib
import importlib.util
import io
import re
from pathlib import Path

import pytest

from sweetspot import cli, commands, setup
from tests.contract.test_cli_contract import _subcommands

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "specs" / "014-publish-github" / "contracts"
CLI_001 = ROOT / "specs" / "001-price-data-foundation" / "contracts" / "cli.md"
DATA_MODEL = ROOT / "specs" / "014-publish-github" / "data-model.md"

# Not looked for in 014's contract, and why:
COMMON = {"--config", "--json"}     # every sub-command has them (cli.build_parser's `common`): 001 contracts/cli.md


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def written(word: str, path: Path) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(word)}(?![\w-])", text(path)) is not None


def options(parser: argparse.ArgumentParser) -> set[str]:
    """Long option strings and the choices of positional arguments; not --help."""
    found = set()
    for action in parser._actions:
        if isinstance(action, argparse._HelpAction):
            continue
        found.update(o for o in action.option_strings if o.startswith("--"))
        if not action.option_strings and action.choices:
            found.update(action.choices)
    return found


@pytest.mark.parametrize("name", ["setup", "schedule"])
def test_every_option_of_014s_commands_is_in_its_contract(name):
    sub = _subcommands(cli.build_parser())[name]
    assert COMMON <= options(sub) and all(written(o, CLI_001) for o in COMMON)
    missing = [o for o in sorted(options(sub) - COMMON) if not written(o, CONTRACTS / "cli.md")]
    assert not missing, f"{name}: not in 014 contracts/cli.md: {missing}"


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def script_options(name: str) -> set[str]:
    """The options of a script's parser, from its --help (the parser is built inside main())."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out), pytest.raises(SystemExit):
        _script(name).main(["--help"])
    return set(re.findall(r"(?<![\w-])(--[a-z][a-z-]*)", out.getvalue())) - {"--help"}


@pytest.mark.parametrize(("script", "contract"), [("publish", "publish.md"), ("scan_personal", "scan-personal.md")])
def test_every_option_of_the_scripts_is_in_their_contract(script, contract):
    found = script_options(script)
    assert found, script
    missing = [o for o in sorted(found) if not written(o, CONTRACTS / contract)]
    assert not missing, f"{script}.py: not in contracts/{contract}: {missing}"


def test_every_exit_code_has_a_row_in_001s_table():
    codes = {name: value for name, value in vars(cli).items() if name.startswith("EXIT_") and isinstance(value, int)}
    codes |= {f"setup.{name}": value for name, value in vars(setup).items() if name.startswith("EXIT_")}
    rows = set(re.findall(r"^\| (\d+) \|", text(CLI_001), re.M))
    missing = {name: value for name, value in codes.items() if str(value) not in rows}
    assert codes and not missing, f"exit codes with no row in 001 contracts/cli.md: {missing}"


def test_every_key_and_value_of_the_reference_notice_is_in_the_data_model():
    notices = [commands.reference_notice(10, has_steam_key=key, complete=lambda done=done: done)
               for key in (True, False) for done in (True, False)]
    words = {k for n in notices for k in n} | {v for n in notices for v in n.values() if isinstance(v, str)}
    assert {"sampling", "complete", "incomplete", "ok", "disabled"} <= words      # the list is not empty or stale
    missing = [w for w in sorted(words) if not written(w, DATA_MODEL)]
    assert not missing, f"reference_notice: not in 014 data-model.md: {missing}"


def test_the_background_variable_is_in_the_contract():
    assert written(setup.BACKGROUND, CONTRACTS / "cli.md")
