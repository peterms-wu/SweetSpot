"""contracts/review.md: `sweetspot review` (feature 013 tasks T011, T019, T023, T028)."""

import hashlib
import io
import json
import re

import pytest

from sweetspot import cli, commands
from tests.config_builders import TEST_TOML
from tests.forecast_builders import dt
from tests.review_builders import (EARLY, F_OPTION, RECORD, bundle_entry, bundle_rows, daily_rows,
                                   default_decisions, during_records, pre_sale_record, review_db, write_records)

NOW = dt("2026-10-12T04:00")


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_secrets", lambda: cli.Secrets())
    monkeypatch.setattr(commands, "NOW", lambda: NOW)
    path = tmp_path / "sweetspot.toml"
    path.write_text(TEST_TOML, encoding="utf-8")
    return path


def setup_data(config_path, *, apps=None, daily=None):
    """All seven games plus the A x C bundle (with its daily rows), or only `apps` without the bundle."""
    data = config_path.parent / "data"
    if daily is None and apps is None:
        daily = {6: daily_rows(F_OPTION, 33), 1: bundle_rows(40500)}
    review_db(data / "sweetspot.db", daily=daily)
    decisions = [d for d in default_decisions() if apps is None or d["app_id"] in apps]
    bundles = [bundle_entry()] if apps is None else []
    write_records(data / "forecasts", [pre_sale_record(decisions=decisions, bundles=bundles), *during_records(EARLY)])
    return data


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(list(argv), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_review_writes_the_contract(config_path, tmp_path):
    setup_data(config_path, apps={1, 2, 3, 4, 7}, daily={})
    out = tmp_path / "r.json"
    code, text, err = run("review", "--config", str(config_path), "--sale", "autumn-2026", "--out", str(out),
                          "--no-recompute")
    assert code == cli.EXIT_OK, err
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema"] == "steamsage.review/1"
    assert data["definitions"] == {"primary": "sale-max", "secondary": "crossing"}
    assert [g["app_id"] for g in data["games"]] == [1, 2, 3, 4, 7]
    assert data["target"]["record"]["file"] == RECORD and data["target"]["record"]["hours_before_start"] == 22.5
    assert data["target"]["sale"] == {"season": "autumn", "year": 2026, "label": "2026 秋特",
                                      "start": "2026-10-01T17:00:00Z", "end": "2026-10-08T17:00:00Z"}
    assert data["summary"]["counts"] == {"records": 5, "reviewed": 4, "no_actual": 0, "not_scored": 1, "corrected": 0,
                                         "groups": {"now": 1, "soon": 2, "wait": 1, "na": 1}}
    assert set(data["run"]) == {"started_at", "seconds", "steamsage_version"}
    assert "事後對照：2026 秋特" in text and "即將到價" in text


def test_json_prints_the_summary(config_path, tmp_path):
    setup_data(config_path, apps={1, 2, 3, 4, 7}, daily={})
    code, text, _ = run("review", "--json", "--config", str(config_path), "--out", str(tmp_path / "r.json"),
                        "--no-recompute")
    assert code == cli.EXIT_OK
    summary = json.loads(text)
    assert summary == json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))["summary"]


def test_default_output_path(config_path):
    data = setup_data(config_path, apps={1, 2, 3, 4, 7}, daily={})
    code, _, err = run("review", "--config", str(config_path), "--no-recompute")
    assert code == cli.EXIT_OK, err
    assert (data / "reviews" / "autumn-2026_20260930T183137Z_20261012.json").exists()


def test_a_sale_that_has_not_ended_fails_without_writing(config_path, tmp_path):
    setup_data(config_path)
    out = tmp_path / "r.json"
    code, _, err = run("review", "--config", str(config_path), "--sale", "winter-2026", "--out", str(out))
    assert code == cli.EXIT_FAILED and "還沒結束" in err
    assert not out.exists()


def test_review_is_read_only(config_path):
    assert "review" in cli.READ_ONLY_COMMANDS and "review" not in cli.WRITE_COMMANDS


def test_unknown_and_corrected_games_make_it_partial(config_path, tmp_path):
    setup_data(config_path)
    out = tmp_path / "r.json"
    code, text, err = run("review", "--config", str(config_path), "--out", str(out), "--no-recompute")
    assert code == cli.EXIT_PARTIAL, err
    data = json.loads(out.read_text(encoding="utf-8"))
    c = data["summary"]["counts"]
    assert (c["records"], c["reviewed"], c["no_actual"], c["not_scored"], c["corrected"]) == (7, 5, 1, 1, 1)
    assert data["summary"]["mismatches"] == {
        "corrected": [{"app_id": 6, "name": "Game 6", "history_max_cut": 0, "daily_max_cut": 33}], "noted": []}
    games = {g["app_id"]: g for g in data["games"]}
    assert games[5]["status"] == "no-actual" and games[5]["reason"] == "價格歷史只到 2026-10-05"
    # F: sweet -30% = NT$350; the corrected sale low is NT$335 (-33%), a hit only because of the daily rows
    assert games[6]["actual"]["corrected"]
    assert (games[6]["decision"]["hit"], games[6]["decision"]["gap_cents"]) == (True, -1500)
    assert "依每日價格紀錄補正 1 款（Game 6）" in text
    [bundle] = data["summary"]["bundles"]
    assert (bundle["id"], bundle["actual"]["min_cents"], bundle["estimate_gap_cents"], bundle["joint_hit"]) == (
        9001, 40500, -4500, True)
    assert "組合包    A x C：下一場買組合包，推算 NT$450" in text


# --- US5: recompute unless --no-recompute (T032) ----------------------------------------------------------------

def test_recompute_is_on_by_default(config_path, tmp_path):
    setup_data(config_path)
    on, off = tmp_path / "on.json", tmp_path / "off.json"
    code, text, err = run("review", "--config", str(config_path), "--out", str(on))
    assert code == cli.EXIT_PARTIAL, err
    run("review", "--config", str(config_path), "--out", str(off), "--no-recompute")
    rc = json.loads(on.read_text(encoding="utf-8"))["summary"]["recompute"]
    assert set(rc) == {"record", "current", "baseline", "different", "probability_drift", "note"}
    assert rc["record"]["n"] == rc["current"]["n"] == rc["baseline"]["n"]
    assert json.loads(off.read_text(encoding="utf-8"))["summary"]["recompute"] is None
    assert "重算      正式紀錄" in text and "不判定優劣" in text


# --- US4: non-seasonal periods by --today (T028) --------------------------------------------------------------

def test_non_seasonal_periods_follow_today(config_path, tmp_path):
    setup_data(config_path)
    early, late = tmp_path / "early.json", tmp_path / "late.json"
    run("review", "--config", str(config_path), "--out", str(early), "--today", "2026-10-12", "--no-recompute")
    code, text, err = run("review", "--config", str(config_path), "--out", str(late), "--today", "2026-11-01",
                          "--no-recompute")
    assert code == cli.EXIT_PARTIAL, err
    a = json.loads(early.read_text(encoding="utf-8"))["summary"]["non_seasonal"]
    b = json.loads(late.read_text(encoding="utf-8"))["summary"]["non_seasonal"]
    assert {h: v["games"] for h, v in a["horizons"].items()} == {"30": 0, "60": 0, "90": 0}
    assert a["next_due"] == "2026-10-30T18:31:37Z"
    # 11/01: only C's history is known past 10/30 (A stops at 10/09) → one game in the 30-day period
    assert {h: v["games"] for h, v in b["horizons"].items()} == {"30": 1, "60": 0, "90": 0}
    assert b["horizons"]["30"]["brier"]["value"] == 0.1363                # (10 × 0.25 + 9 × 0.01) / 19
    assert b["next_due"] == "2026-11-29T18:31:37Z"
    assert "非季節    30 天 1 款 Brier 0.1363" in text


# --- US6: reproducible, read-only, and a draft whose numbers are all in the JSON (T023) ----------------------

def digests(data_dir, config_path):
    files = [data_dir / "sweetspot.db", data_dir / "steam_sales.toml", config_path,
             *sorted((data_dir / "forecasts").iterdir())]
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def without_run(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["run"]
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def test_same_data_same_bytes_and_inputs_untouched(config_path, tmp_path):
    data = setup_data(config_path)
    before = digests(data, config_path)
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    for out in (a, b):
        code, _, err = run("review", "--config", str(config_path), "--out", str(out), "--today", "2026-10-12")
        assert code == cli.EXIT_PARTIAL, err
    assert without_run(a) == without_run(b)
    assert digests(data, config_path) == before


def _walk(obj, numbers, strings):
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        numbers.add(round(abs(float(obj)), 4))      # the draft writes the sign in words (低／高)
    elif isinstance(obj, str):
        strings.add(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _walk(v, numbers, strings)
    elif isinstance(obj, list):
        numbers.add(float(len(obj)))          # "12 款" counts the items of a list
        for v in obj:
            _walk(v, numbers, strings)


def traced(x: float, percent: bool, numbers: set[float]) -> bool:
    """A figure in the draft is a JSON number as is, NT$ of a *_cents value, or a share shown as a percentage."""
    if round(x, 4) in numbers or round(x * 100) in numbers:
        return True
    return percent and any(n <= 1 and abs(x - n * 100) < 0.051 for n in numbers)


def test_every_number_in_the_draft_is_in_the_result(config_path, tmp_path):
    setup_data(config_path)
    out = tmp_path / "r.json"
    code, text, err = run("review", "--config", str(config_path), "--out", str(out), "--doc")
    assert code == cli.EXIT_PARTIAL, err
    assert text.startswith("## 2026-10-12 · 事後對照：2026 秋特") and out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    numbers, strings = set(), set()
    _walk({k: v for k, v in data.items() if k != "run"}, numbers, strings)
    assert text.splitlines()[0].startswith(f"## {data['target']['today'][:10]} · ")    # the heading's date
    body = re.sub(r"\d{4}-\d{2}-\d{2}(T[\d:]+Z)?", " ", text)      # dates are labels; every one is checked above
    assert set(re.findall(r"\d{4}-\d{2}-\d{2}T[\d:]+Z", text)) <= strings
    for s in sorted(strings, key=len, reverse=True):     # names, labels, file names and dates are data, not figures
        if len(s) > 2 and not re.fullmatch(r"\d\.\d", s):     # not the calibration bin labels ("0.3")
            body = body.replace(s, " ")
    missing = [m.group(0) for m in re.finditer(r"(?<![\w.])(\d+(?:,\d{3})*(?:\.\d+)?)(%?)", body)
               if not traced(float(m.group(1).replace(",", "")), m.group(2) == "%", numbers)]
    assert missing == []
    assert "和回測一致" in text or "和回測不同" in text
