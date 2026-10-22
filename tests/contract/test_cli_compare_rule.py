"""004 contracts/cli.md: `sweetspot compare-rule` (tasks T030)."""

import io
import json

import pytest

from sweetspot import cli
from tests.config_builders import TEST_TOML
from tests.forecast_builders import BASIC_CALENDAR, GameSpec, build_db
from tests.integration.test_backtest_runner import EXTRA_CALENDAR, tw


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_secrets", lambda: cli.Secrets())
    path = tmp_path / "sweetspot.toml"
    path.write_text(TEST_TOML, encoding="utf-8")
    games = [GameSpec(a, tw=tw(a), known_until={"TW": "2026-09-24"}, wishlist=a <= 3) for a in range(1, 7)]
    build_db(tmp_path / "data" / "sweetspot.db", games, calendar=EXTRA_CALENDAR + BASIC_CALENDAR)
    return path


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(list(argv), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def results(config_path):
    _, out, _ = run("backtest-rule", "--json", "--rule", "1.0.0", "--model", "seasonal-freq", "--param",
                    "min_sales=2", "--config", str(config_path))
    a = json.loads(out)["result"]
    _, out, _ = run("backtest-rule", "--json", "--rule", "2.0.0", "--model", "seasonal-record", "--config",
                    str(config_path))
    return a, json.loads(out)["result"]


def test_side_by_side_with_the_wishlist_and_a_record(config_path, tmp_path):
    a, b = results(config_path)
    record = tmp_path / "records.md"
    code, out, err = run("compare-rule", a, b, "--record-to", str(record), "--json", "--config", str(config_path))
    assert code == cli.EXIT_OK, err
    summary = json.loads(out)
    assert {r["key"] for r in summary["rows"]} >= {"hit_rate.soon", "follow_advice.saving_mean", "sweet_timing.next"}
    assert sum(summary["wishlist"]["counts"]["a"].values()) == 3 == sum(summary["wishlist"]["counts"]["b"].values())
    text = record.read_text(encoding="utf-8")
    assert "規則回測並列：seasonal-freq 1.0.0" in text and "sweet-price 2.0.0" in text and "願望清單（現在）" in text
    code, _, err = run("compare-rule", a, b, "--no-wishlist", "--decision", "不換", "--record-to", str(record),
                       "--config", str(config_path))
    assert code == cli.EXIT_OK, err
    assert "**使用者的決定**：不換" in record.read_text(encoding="utf-8")


def test_different_datasets_are_refused(config_path, tmp_path):
    a, _ = results(config_path)
    _, out, _ = run("backtest-rule", "--json", "--apps-limit", "3", "--rule", "1.0.0", "--model", "seasonal-freq",
                    "--param", "min_sales=2", "--config", str(config_path))
    small = json.loads(out)["result"]
    code, _, err = run("compare-rule", a, small, "--no-wishlist", "--config", str(config_path))
    assert code == cli.EXIT_FAILED and "資料集不同" in err


# --- feature 005: a base and several candidates (tasks T025; contracts/cli.md) --------------------------------

def v3_results(config_path, split="all"):
    _, out, _ = run("backtest-rule", "--json", "--rule", "2.0.0", "--split", split, "--config", str(config_path))
    base = json.loads(out)["result"]
    _, out, _ = run("backtest-rule", "--json", "--rule", "3.0.0", "--wait-cost", "10,20", "--split", split,
                    "--config", str(config_path))
    return base, [s["result"] for s in json.loads(out)]


def test_several_candidates_with_the_net_benefit(config_path, tmp_path):
    base, cands = v3_results(config_path)
    record = tmp_path / "records.md"
    code, out, err = run("compare-rule", base, *cands, "--record-to", str(record), "--json", "--config",
                         str(config_path))
    assert code == cli.EXIT_OK, err
    summary = json.loads(out)
    assert [c["cost_twd"] for c in summary["net"]] == [10, 20]
    for c in summary["net"]:
        assert set(c["modes"]) == {"monthly", "fixed"} and c["verdict"] is None      # not the validation part
    assert {r["result"] for r in summary["net_by_cost"]} == {"基準", "c10", "c20"}
    wl = summary["wishlist"]
    assert len(wl) == 2 and all("net_twd" in g["to"] for d in wl for g in d["changed"])
    assert all("longer_24" in d for d in wl)
    text = record.read_text(encoding="utf-8")
    assert "規則回測並列" in text and "淨效益" in text and "c = 20" in text


def test_validation_needs_an_attempt_and_records_it(config_path, tmp_path):
    base, cands = v3_results(config_path, "validation")
    record = tmp_path / "records.md"
    code, _, err = run("compare-rule", base, *cands, "--no-wishlist", "--record-to", str(record), "--config",
                       str(config_path))
    assert code == cli.EXIT_FAILED and "--attempt" in err
    code, out, err = run("compare-rule", base, *cands, "--no-wishlist", "--record-to", str(record), "--attempt", "1",
                         "--json", "--config", str(config_path))
    assert code == cli.EXIT_OK, err
    verdicts = {c["cost_twd"]: c["verdict"] for c in json.loads(out)["net"]}
    assert verdicts[10] is None and verdicts[20] in ("pass", "fail")
    text = record.read_text(encoding="utf-8")
    assert "規則驗證組比較（sweet-price 3.0.0）第 1 次" in text and "硬門檻" in text
    code, _, err = run("compare-rule", base, *cands, "--no-wishlist", "--record-to", str(record), "--attempt", "1",
                       "--config", str(config_path))
    assert code == cli.EXIT_FAILED and "已有" in err


def test_a_decision_for_a_recorded_attempt_is_appended_alone(config_path, tmp_path):
    base, cands = v3_results(config_path, "validation")
    record = tmp_path / "records.md"
    code, _, err = run("compare-rule", base, *cands, "--no-wishlist", "--record-to", str(record), "--attempt", "1",
                       "--config", str(config_path))
    assert code == cli.EXIT_OK, err
    before = record.read_text(encoding="utf-8")
    code, _, err = run("compare-rule", base, *cands, "--no-wishlist", "--record-to", str(record), "--attempt", "1",
                       "--decision", "不換版", "--config", str(config_path))
    assert code == cli.EXIT_OK, err
    after = record.read_text(encoding="utf-8")
    assert after.startswith(before)                                     # append only
    added = after[len(before):]
    assert "使用者的決定：規則驗證組比較（sweet-price 3.0.0）第 1 次" in added and "不換版" in added
    assert "| 指標 |" not in added                                     # no second copy of the tables
