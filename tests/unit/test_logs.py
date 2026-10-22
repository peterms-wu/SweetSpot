"""data/logs/: the file name and logger name after the 016 rename, and key redaction (FR-028)."""

import logging
import re
from datetime import datetime

from sweetspot import logs


def test_log_file_and_logger_use_the_new_name(tmp_path):
    path = logs.setup_logging(tmp_path, ["secret-value"])
    assert path.parent == tmp_path / "logs"
    assert re.fullmatch(r"sweetspot-\d{8}\.log", path.name)
    assert path.name == f"sweetspot-{datetime.now():%Y%m%d}.log"     # the local day, not the UTC one (2026-10-18)
    logging.getLogger("sweetspot.test").info("hello secret-value key=abc")
    for handler in logging.getLogger("sweetspot").handlers:
        handler.flush()
    text = path.read_text(encoding="utf-8")
    assert "sweetspot.test: hello *** key=***" in text
    assert "secret-value" not in text and "abc" not in text


def test_setting_up_twice_keeps_one_handler(tmp_path):
    logs.setup_logging(tmp_path, [])
    logs.setup_logging(tmp_path, [])
    ours = [h for h in logging.getLogger("sweetspot").handlers if getattr(h, "_sweetspot", False)]
    assert len(ours) == 1
    for handler in ours:
        logging.getLogger("sweetspot").removeHandler(handler)
        handler.close()


def test_result_lines_keep_short_values_and_count_lists():
    summary = {"kind": "daily", "status": "completed", "now": 7, "preview": False, "ratio": 98.9, "skipped": None,
               "wishlist": {"count": 69}, "failures": [], "alerts": ["組合包 A：價格對不上"], "long": "x" * 121}
    head, alerts = logs.result_lines("update", 2, 371.25, summary)
    assert head == ("update 結束：代碼 2，371.2 秒；kind=daily, status=completed, now=7, preview=False, ratio=98.9, "
                    "failures=0 項, alerts=1 項")
    assert alerts == 'update alerts：["組合包 A：價格對不上"]'


def test_result_lines_with_a_note_and_a_long_list():
    head, failures = logs.result_lines("backup", 1, 0.04, {"failures": ["y" * 600]}, note="備份失敗：\n  gh   failed")
    assert head == "backup 結束：代碼 1，0.0 秒；備份失敗： gh failed；failures=1 項"
    assert failures.endswith("…") and len(failures) == len("backup failures：") + 501
    assert logs.result_lines("backtest-rule", 0, 1.0, [{"rule": "2.1.0"}]) == ["backtest-rule 結束：代碼 0，1.0 秒"]


def test_log_result_is_redacted_and_warns_unless_the_code_is_0(tmp_path):
    path = logs.setup_logging(tmp_path, ["secret-value"])
    logs.log_result("update", 0, 1.0, {"status": "completed"})
    logs.log_result("backup", 1, 1.0, note="gh failed with secret-value")
    for handler in logging.getLogger("sweetspot").handlers:
        handler.flush()
    text = path.read_text(encoding="utf-8")
    assert "INFO sweetspot.result: update 結束：代碼 0，1.0 秒；status=completed" in text
    assert "WARNING sweetspot.result: backup 結束：代碼 1，1.0 秒；gh failed with ***" in text
    assert "secret-value" not in text
