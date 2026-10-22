"""Editing one line of [purchase_options] (feature 015 tasks T005; research R3; spec FR-008, SC-003).
Every case compares the whole file byte for byte."""

import pytest

from tests.config_builders import TEST_TOML
from sweetspot.host import toml_edit
from sweetspot.host.toml_edit import ConfigInvalid, ConfigUnsafe

TODAY = "2026-10-14"
SAMPLE = """schema_version = 1

[market]
region = "TW"          # 固定值，不可更改（憲章 IX）

# 指定要追蹤的購買選項（使用者偏好，不是模型事實）
[purchase_options]
1091500 = "bundle/32470"   # Cyberpunk 2077 → 《電馭叛客 2077：終極版》（2026-09-27 使用者指定）
"""
ULTIMATE = "《電馭叛客 2077：終極版》"


def line(app, ref, name):
    comment = f"{name}（{TODAY} 從 Steam 頁面指定）" if name else f"{TODAY} 從 Steam 頁面指定"
    return f'{app} = "{ref}"   # {comment}'


def edit(text, app, choice, name="Game"):
    return toml_edit.set_choice(text, app, choice, name=name, today=TODAY)


# --- adding -------------------------------------------------------------------------------------------------------

def test_add_after_the_last_line_of_the_section():
    assert edit(SAMPLE, 2000, ("sub", 5)) == SAMPLE + line(2000, "sub/5", "Game") + "\n"


def test_add_to_the_default_file_whose_section_holds_only_comments():
    assert edit(TEST_TOML, 1091500, ("bundle", 32470), ULTIMATE) == \
        TEST_TOML + line(1091500, "bundle/32470", ULTIMATE) + "\n"


def test_add_before_the_blank_line_and_the_next_section():
    text = '[purchase_options]\n1 = "sub/1"\n\n[other]\nx = 1   # keep\n'
    assert edit(text, 2, ("sub", 2)) == \
        f'[purchase_options]\n1 = "sub/1"\n{line(2, "sub/2", "Game")}\n\n[other]\nx = 1   # keep\n'


def test_add_right_after_a_header_with_nothing_under_it():
    text = "[purchase_options]\n[market]\nregion = \"TW\"\n"
    assert edit(text, 2, ("bundle", 9)) == f'[purchase_options]\n{line(2, "bundle/9", "Game")}\n[market]\nregion = "TW"\n'


def test_a_header_written_with_spaces_and_a_comment_is_found():
    text = '[ purchase_options ]   # mine\n1 = "sub/1"\n'
    assert edit(text, 2, ("sub", 2)) == text + line(2, "sub/2", "Game") + "\n"


def test_add_the_section_when_there_is_none():
    assert edit('a = 1\n', 5, ("sub", 7)) == f'a = 1\n\n[purchase_options]\n{line(5, "sub/7", "Game")}\n'


def test_add_the_section_to_a_file_without_a_final_newline():
    assert edit('a = 1', 5, ("sub", 7)) == f'a = 1\n\n[purchase_options]\n{line(5, "sub/7", "Game")}'


def test_add_after_a_last_line_without_a_newline():
    text = '[purchase_options]\n1 = "sub/1"'
    assert edit(text, 2, ("sub", 2)) == f'[purchase_options]\n1 = "sub/1"\n{line(2, "sub/2", "Game")}'


# --- replacing and removing ---------------------------------------------------------------------------------------

def test_replace_the_line_and_its_comment():
    want = SAMPLE.replace(SAMPLE.splitlines()[-1], line(1091500, "sub/367653", "Cyberpunk 2077"))
    assert edit(SAMPLE, 1091500, ("sub", 367653), "Cyberpunk 2077") == want


@pytest.mark.parametrize("key", ['"1091500"', "'1091500'"])
def test_replace_a_quoted_key(key):
    text = SAMPLE.replace('1091500 = "bundle/32470"', f'{key} = "bundle/32470"')
    want = SAMPLE.replace(SAMPLE.splitlines()[-1], line(1091500, "sub/1", "Game"))
    assert edit(text, 1091500, ("sub", 1)) == want


def test_replace_a_literal_string_value():
    text = "[purchase_options]\n5 = 'sub/1'\n"
    assert edit(text, 5, ("sub", 2)) == f'[purchase_options]\n{line(5, "sub/2", "Game")}\n'


def test_replace_the_last_line_without_a_newline():
    assert edit('[purchase_options]\n1 = "sub/1"', 1, ("sub", 2)) == f'[purchase_options]\n{line(1, "sub/2", "Game")}'


def test_remove_only_that_line():
    want = SAMPLE[:SAMPLE.index("1091500 =")]
    assert edit(SAMPLE, 1091500, None) == want


def test_remove_a_line_in_the_middle():
    text = '[purchase_options]\n# a\n1 = "sub/1"\n\n2 = "sub/2"   # x\n# b\n3 = "sub/3"\n'
    assert edit(text, 2, None) == '[purchase_options]\n# a\n1 = "sub/1"\n\n# b\n3 = "sub/3"\n'


def test_removing_what_is_not_there_changes_nothing():
    assert edit(SAMPLE, 5, None) == SAMPLE
    assert edit("a = 1\n", 5, None) == "a = 1\n"


# --- what is kept -------------------------------------------------------------------------------------------------

def test_crlf_files_stay_crlf():
    text = SAMPLE.replace("\n", "\r\n")
    assert edit(text, 2000, ("sub", 5)) == text + line(2000, "sub/5", "Game") + "\r\n"
    assert edit(text, 1091500, None) == text[:text.index("1091500 =")]


def test_a_byte_order_mark_is_refused_like_the_config_loader_does():
    with pytest.raises(ConfigInvalid):            # tomllib (and load_config) reject it, so SweetSpot cannot read it
        edit("﻿" + SAMPLE, 2000, ("sub", 5))


def test_other_sections_comments_and_blank_lines_are_untouched():
    text = TEST_TOML + '2 = "sub/2"\n\n# trailing comment\n'
    out = edit(text, 3, ("sub", 3))
    assert out == TEST_TOML + f'2 = "sub/2"\n{line(3, "sub/3", "Game")}\n\n# trailing comment\n'


# --- refusals -----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["a = ", "[purchase_options]\n1 = sub/1\n"])
def test_invalid_toml(text):
    with pytest.raises(ConfigInvalid):
        edit(text, 1, ("sub", 1))
    with pytest.raises(ConfigInvalid):
        toml_edit.current_choice(text, 1)


@pytest.mark.parametrize("text", [
    '[purchase_options]\n"0123" = "sub/1"\n123 = "sub/2"\n',        # the same app written two ways
    'purchase_options.123 = "sub/1"\n',                            # outside the section
    'purchase_options = { 123 = "sub/1" }\n',
    '[[purchase_options]]\nx = 1\n',
    '[purchase_options]\n123 = """sub/1"""\n',                     # not a plain one-line string
    '[purchase_options]\n123 = """\nsub/1"""\n',
    '[purchase_options]\n123 = "sub\\u002f1"\n',
    '[purchase_options]\n123.x = "sub/1"\n',
])
def test_unsafe_layouts_are_refused(text):
    with pytest.raises(ConfigUnsafe):
        edit(text, 123, ("sub", 9))


# --- the written comment ------------------------------------------------------------------------------------------

def test_control_characters_and_newlines_in_the_name_become_spaces():
    out = edit("[purchase_options]\n", 1, ("sub", 1), "Bad\nName\x00​\tEnd")
    assert out == f'[purchase_options]\n{line(1, "sub/1", "Bad Name End")}\n'


def test_a_long_name_is_cut_to_80_characters():
    out = edit("[purchase_options]\n", 1, ("sub", 1), "長" * 100)
    assert out == f'[purchase_options]\n{line(1, "sub/1", "長" * 80)}\n'


def test_no_name():
    assert edit("[purchase_options]\n", 1, ("sub", 1), None) == f'[purchase_options]\n{line(1, "sub/1", None)}\n'


# --- current_choice -----------------------------------------------------------------------------------------------

def test_current_choice_reads_like_the_config_loader():
    assert toml_edit.current_choice(SAMPLE, 1091500) == ("bundle", 32470)
    assert toml_edit.current_choice(SAMPLE, 5) is None
    assert toml_edit.current_choice(TEST_TOML, 1091500) is None
    assert toml_edit.current_choice('[purchase_options]\n"0123" = "sub/1"\n123 = "sub/2"\n', 123) is None
    assert toml_edit.current_choice('[purchase_options]\n5 = "pkg/1"\n', 5) is None
