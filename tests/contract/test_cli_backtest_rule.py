"""contracts/cli.md: `sweetspot backtest-rule` (tasks T034; contracts/rule-backtest-result.md)."""

import hashlib
import io
import json
import re
from pathlib import Path

import pytest

from sweetspot import cli
from tests.config_builders import TEST_TOML
from sweetspot.decision import backtest as rule_backtest
from tests.forecast_builders import BASIC_CALENDAR, GameSpec, build_db
from tests.integration.test_backtest_runner import EXTRA_CALENDAR, tw


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_secrets", lambda: cli.Secrets())
    path = tmp_path / "sweetspot.toml"
    path.write_text(TEST_TOML, encoding="utf-8")
    games = [GameSpec(a, tw=tw(a), known_until={"TW": "2026-09-24"}) for a in range(1, 7)]
    build_db(tmp_path / "data" / "sweetspot.db", games, calendar=EXTRA_CALENDAR + BASIC_CALENDAR)
    return path


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(list(argv), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_writes_the_result_and_summarises(config_path):
    db = config_path.parent / "data" / "sweetspot.db"
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    code, out, err = run("backtest-rule", "--json", "--model", "seasonal-freq", "--param", "min_sales=2",
                         "--rule", "1.0.0", "--config", str(config_path))
    assert code == cli.EXIT_OK, err
    summary = json.loads(out)
    path = Path(summary["result"])
    assert path.parent == config_path.parent / "data" / "backtests" and path.exists()
    assert re.search(r"_sweet-price-1\.0\.0_seasonal-freq-1\.0\.0_[0-9a-f]{6}_TW_", path.name)   # 004: params hash
    result = json.loads(path.read_text(encoding="utf-8"))
    assert result["schema"] == "steamsage.rule-backtest/1"
    assert result["rule"]["name"] == "sweet-price" and result["preferences"]["tolerance_min_twd"] == 30
    for key in ("decisions", "hit_rate", "timing_error", "now_followup", "errors", "run"):
        assert key in result
    for key in ("result", "cutoff", "dataset_id", "decisions", "hit_rate", "timing_error", "now_followup",
                "report_figures", "seconds"):
        assert key in summary, key
    assert "規則回測 分析時點 1/" in err
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    assert not (config_path.parent / "data" / ".lock").exists()


def test_dataset_id_matches_the_forecast_backtest(config_path):
    _, out, _ = run("backtest-rule", "--json", "--cutoff", "2026-09-24", "--config", str(config_path))
    rule = json.loads(out)
    _, out, _ = run("backtest", "--json", "--region", "TW", "--cutoff", "2026-09-24", "--config", str(config_path))
    forecast = json.loads(Path(json.loads(out)["result"]).read_text(encoding="utf-8"))
    assert rule["dataset_id"] == forecast["dataset"]["regions"]["TW"]["dataset_id"]


def test_decision_errors_give_exit_2(config_path, monkeypatch):
    def broken(**kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(rule_backtest, "decide", broken)
    code, out, _ = run("backtest-rule", "--json", "--config", str(config_path))
    assert code == cli.EXIT_PARTIAL and json.loads(out)["decisions"]["decision_error"] > 0


def test_model_rule_and_split_options(config_path):
    """004 contracts/cli.md: the side-by-side runs (spec FR-015, FR-020, FR-021)."""
    code, out, err = run("backtest-rule", "--json", "--model", "seasonal-record@1.0.0", "--param", "half_life=2",
                         "--rule", "2.0.0", "--split", "tuning", "--config", str(config_path))
    assert code in (cli.EXIT_OK, cli.EXIT_PARTIAL), err
    summary = json.loads(out)
    assert summary["rule"] == "2.0.0" and summary["split"] == "tuning"
    assert summary["model"]["name"] == "seasonal-record" and summary["model"]["params"]["half_life"] == 2
    for key in ("sweet_timing", "follow_advice", "hindsight"):
        assert key in summary, key
    result = json.loads(Path(summary["result"]).read_text(encoding="utf-8"))
    assert result["rule"]["version"] == "2.0.0" and result["rule"]["constants"]["p_min_months"] == 12
    assert result["dataset"]["split"]["name"] == "tuning"
    assert result["sweet_timing"]["beyond_1y"] == 0               # 2.0.0 never looks past 12 months
    assert "_sweet-price-2.0.0_seasonal-record-1.0.0_" in Path(summary["result"]).name


def test_unknown_rule_version_is_an_argument_error(config_path):
    with pytest.raises(SystemExit):
        run("backtest-rule", "--rule", "9.9.9", "--config", str(config_path))


# --- feature 005: --wait-cost, monthly re-evaluation, net benefit (tasks T023; rule-backtest-v005.md) -----------

def test_several_waiting_costs_share_the_forecast(config_path):
    code, out, err = run("backtest-rule", "--json", "--rule", "3.0.0", "--wait-cost", "10,20", "--config",
                         str(config_path))
    assert code in (cli.EXIT_OK, cli.EXIT_PARTIAL), err
    summaries = json.loads(out)
    assert isinstance(summaries, list) and [s["wait_cost_twd"] for s in summaries] == [10, 20]
    results = [json.loads(Path(s["result"]).read_text(encoding="utf-8")) for s in summaries]
    assert [Path(s["result"]).name.split("_")[1] for s in summaries] == ["sweet-price-3.0.0-c10", "sweet-price-3.0.0-c20"]
    for s, r in zip(summaries, results):
        assert r["preferences"] == {"wait_cost_twd": s["wait_cost_twd"], "soon_sales": 1}
        assert r["evaluation_costs_twd"] == [0, 10, 20, 30, 50, 80]
        for key in ("follow_advice_monthly", "longer_horizon", "cases"):
            assert key in r, key
        assert set(r["longer_horizon"]) == {"24", "60"}
        evaluated = r["follow_advice"]["overall"]["evaluated"] + r["follow_advice_monthly"]["overall"]["evaluated"]
        assert len(r["cases"]) == evaluated
        assert r["cases"] == sorted(r["cases"], key=lambda c: (c[0], c[1], c[2]))
        assert {c[2] for c in r["cases"]} <= {"fixed", "monthly"}
        nets = {n["cost_twd"]: n for n in r["follow_advice_monthly"]["overall"]["net_twd"]}
        assert set(nets) == {0, 10, 20, 30, 50, 80}
        for key in ("follow_advice_monthly", "longer_horizon"):
            assert key in s, key
        assert "net_twd" in s
    # the forecasts are identical: the same games are decided at the same analysis times
    assert results[0]["decisions"]["total"] == results[1]["decisions"]["total"]
    assert results[0]["dataset"] == results[1]["dataset"]


def test_the_default_waiting_cost_comes_from_the_config(config_path):
    code, out, err = run("backtest-rule", "--json", "--rule", "3.0.0", "--config", str(config_path))
    summary = json.loads(out)
    assert code in (cli.EXIT_OK, cli.EXIT_PARTIAL), err
    assert summary["wait_cost_twd"] == 20 and "-c20_" in Path(summary["result"]).name
    assert summary["report_figures"]["wait_cost_twd"] == 20


def test_tolerance_rules_have_no_waiting_cost(config_path):
    code, _, err = run("backtest-rule", "--rule", "2.0.0", "--wait-cost", "20", "--config", str(config_path))
    assert code == cli.EXIT_FAILED and "規則 2.0.0 不使用等待成本" in err
    code, out, _ = run("backtest-rule", "--json", "--rule", "2.0.0", "--config", str(config_path))
    result = json.loads(Path(json.loads(out)["result"]).read_text(encoding="utf-8"))
    assert "longer_horizon" not in result and "follow_advice_monthly" in result
    assert json.loads(out)["report_figures"]["wait_cost_twd"] is None


@pytest.mark.parametrize("value", ["-1", "abc", "10001", "20,x"])
def test_invalid_waiting_costs_are_rejected(config_path, value):
    code, _, err = run("backtest-rule", "--rule", "3.0.0", "--wait-cost", value, "--config", str(config_path))
    assert code == cli.EXIT_FAILED and "--wait-cost" in err


def test_edition_histories_and_purchase_options_leave_the_dataset_unchanged(config_path):
    """Feature 009 (spec FR-012, SC-007): backtests read neither editions nor purchase options."""
    from sweetspot.store.writer import NewPurchaseOption, StoreWriter
    from tests.forecast_builders import add_history, dt

    argv = ("backtest-rule", "--json", "--cutoff", "2026-09-24", "--config", str(config_path))
    _, out, _ = run(*argv)
    before = json.loads(out)
    db = config_path.parent / "data" / "sweetspot.db"
    add_history(db, 1, "itad-edition", tw=[("2024-12-11", 0), ("2025-06-26T17:00", 90)],
                us=[("2024-12-11", 0), ("2025-06-26T17:00", 90)], regular_cents=99000, fetched="2026-09-23",
                source="itad-option-history", fetch_source="itad-option")
    w = StoreWriter.open(db)
    w.add_purchase_options(None, [NewPurchaseOption(app_id=1, kind="bundle", option_id=9, name="Deluxe",
                                                    original_cents=99000, final_cents=99000, position=1,
                                                    is_default=False, role="edition", external_id="itad-edition",
                                                    verification="verified", verified_by="version-check",
                                                    verified_at=dt("2026-09-23"))], checked_at=dt("2026-09-23"))
    w.close()
    _, out, _ = run(*argv)
    after = json.loads(out)
    assert after["dataset_id"] == before["dataset_id"]
    assert after["decisions"] == before["decisions"] and after["hit_rate"] == before["hit_rate"]
