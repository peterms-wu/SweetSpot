"""`sweetspot report` across days: records, baseline, change markers, failures (tasks T026; SC-004, SC-005)."""

import json

import pytest

from sweetspot import cli, commands
from tests.config_builders import TEST_TOML
from sweetspot.decision import records
from sweetspot.decision.records import list_records, load_record
from sweetspot.forecast.models import CURRENT_MODEL
from sweetspot.store.writer import StoreWriter
from tests.decision_builders import steam_current
from tests.forecast_builders import BASIC_CALENDAR, GameSpec, build_db, dt
from tests.report_builders import HISTORY, quiet_cli, run_report


@pytest.fixture
def env(tmp_path, monkeypatch):
    quiet_cli(monkeypatch)
    config = tmp_path / "sweetspot.toml"
    config.write_text(TEST_TOML, encoding="utf-8")
    db = build_db(tmp_path / "data" / "sweetspot.db",
                  [GameSpec(1, tw=HISTORY, name="Alpha", wishlist=True),
                   GameSpec(2, tw=HISTORY, name="Beta", wishlist=True),
                   GameSpec(3, tw=HISTORY, name="Gamma", wishlist=True)], calendar=BASIC_CALENDAR)
    return config, db, tmp_path / "data"


def run(config, monkeypatch, now, *extra):
    monkeypatch.setattr(commands, "NOW", lambda: dt(now))
    return run_report(config, *extra)


def page(data_dir):
    return (data_dir / "reports" / "latest.html").read_text(encoding="utf-8")


def test_records_baseline_and_changes_across_days(env, monkeypatch):
    config, db, data_dir = env
    forecasts = data_dir / "forecasts"

    code, summary = run(config, monkeypatch, "2026-09-24T04:00")
    assert code == 0 and summary["baseline"] is None and summary["changed"] == 0
    assert summary["record"].endswith("20260924T040000Z.json.gz")
    assert "沒有前一天或更早的紀錄，無法比較" in page(data_dir)

    code, summary = run(config, monkeypatch, "2026-09-24T09:00")         # same Taipei day: still no baseline
    assert summary["baseline"] is None and len(list_records(forecasts)) == 2

    writer = StoreWriter.open(db)                                        # next day Beta's regular price rises
    try:
        run_id = writer.start_run("daily")
        with writer.transaction():
            writer.add_observations(run_id, [steam_current(2, "2026-09-25T03:00", 60000, 60000)])
        writer.finish_run(run_id, "completed")
    finally:
        writer.close()

    code, summary = run(config, monkeypatch, "2026-09-25T04:00")
    assert code == 0 and summary["baseline"] == "20260924T090000Z.json.gz" and summary["changed"] == 1
    record = load_record(forecasts / "20260925T040000Z.json.gz")
    by_app = {d["app_id"]: d for d in record["decisions"]}
    assert by_app[1]["change"] is None and by_app[3]["change"] is None
    change = by_app[2]["change"]
    assert change["group"] == {"from": "soon", "to": "low"}
    assert change["sweet_twd"]["from"] != change["sweet_twd"]["to"]
    assert record["comparison"]["baseline"]["as_of"] == "2026-09-24T09:00:00Z"
    html = page(data_dir)
    assert "上次：即將到價" in html and "2026-09-24 17:00" in html        # baseline shown in Taipei time


def test_as_of_writes_no_record(env, monkeypatch):
    config, _, data_dir = env
    code, summary = run(config, monkeypatch, "2026-09-25T04:00", "--as-of", "2025-08-01")
    assert code == 0 and summary["record"] is None and list_records(data_dir / "forecasts") == []


def test_record_failure_still_writes_the_report_and_keeps_the_baseline(env, monkeypatch):
    config, _, data_dir = env
    forecasts = data_dir / "forecasts"
    run(config, monkeypatch, "2026-09-24T04:00")

    def broken(directory, data):
        raise OSError("disk full")

    with monkeypatch.context() as m:
        m.setattr(records, "write_record", broken)
        code, summary = run(config, monkeypatch, "2026-09-25T04:00")
    assert code == cli.EXIT_PARTIAL and "disk full" in summary["record"]
    assert "本次紀錄未保存，下次仍與原比較基準比較" in page(data_dir)
    assert [p.name for p in list_records(forecasts)] == ["20260924T040000Z.json.gz"]
    code, summary = run(config, monkeypatch, "2026-09-25T05:00")
    assert summary["baseline"] == "20260924T040000Z.json.gz"


def test_skipped_broken_record_gives_exit_2(env, monkeypatch):
    config, _, data_dir = env
    (data_dir / "forecasts").mkdir(parents=True)
    (data_dir / "forecasts" / "20260923T000000Z.json.gz").write_bytes(b"broken")
    code, summary = run(config, monkeypatch, "2026-09-25T04:00")
    assert code == cli.EXIT_PARTIAL and summary["baseline"] is None
    assert "20260923T000000Z.json.gz" in page(data_dir)


def test_record_equals_the_report_contract(env, monkeypatch):
    config, _, data_dir = env
    code, summary = run(config, monkeypatch, "2026-09-25T04:00")
    record = load_record(data_dir / "forecasts" / "20260925T040000Z.json.gz")
    assert record["official"] is True and record["forecast"]["schema"] == "steamsage.forecast/1"
    assert len(record["decisions"]) == 3
    for d in record["decisions"]:
        assert f'data-app="{d["app_id"]}"' in page(data_dir)


def test_a_small_reference_dataset_is_noted_in_the_record_and_the_page(env, monkeypatch):
    """014 FR-014a: three wishlist games and no reference game; the record says so and the page shows it."""
    config, _, data_dir = env
    run(config, monkeypatch, "2026-09-25T04:00")
    record = load_record(data_dir / "forecasts" / "20260925T040000Z.json.gz")
    assert record["reference_notice"] == {"dataset_size": 0, "threshold": 2000, "broad_sample": "disabled",
                                        "sampling": "incomplete"}
    assert "參考資料集目前 0 款（建議至少 2,000 款）" in page(data_dir)


def test_a_model_switch_is_named_in_the_next_comparison(env, monkeypatch):
    """004 spec FR-025: yesterday's record is from the previous model and rule; today's report says so."""
    from sweetspot.decision import engine, rule
    from sweetspot.forecast.models import build_model

    config, _, data_dir = env
    with monkeypatch.context() as old:
        old.setattr(commands, "current_model", lambda: build_model("seasonal-freq", {"min_sales": 2}))
        old.setattr(rule, "CURRENT_RULE", "1.0.0")
        old.setattr(engine, "RULE_VERSION", "1.0.0")
        code, summary = run(config, monkeypatch, "2026-09-24T04:00")
        assert code == 0 and summary["rule"]["version"] == "1.0.0" and summary["model"]["name"] == "seasonal-freq"
    code, summary = run(config, monkeypatch, "2026-09-25T04:00")
    assert code == 0 and summary["model"]["name"] == "seasonal-record" and summary["rule"]["version"] == "2.1.0"
    record = load_record(sorted(list_records(data_dir / "forecasts"))[-1])
    changes = record["comparison"]["version_changes"]
    assert any(c.startswith("模型 seasonal-freq 1.0.0") and f"seasonal-record {CURRENT_MODEL[1]}" in c
               for c in changes)
    assert "規則 sweet-price 1.0.0 → 2.1.0" in changes
    html = page(data_dir)
    assert "版本或偏好改變：規則 sweet-price 1.0.0 → 2.1.0" in html
    assert "12 個月內最低" in html and "目前的模型無法預測" not in html


# --- feature 005: rule switch, waiting-cost change, preview (tasks T019) ----------------------------------------

def switch_to_v3(monkeypatch):
    from sweetspot.decision import engine, rule
    monkeypatch.setattr(rule, "CURRENT_RULE", "3.0.0")
    monkeypatch.setattr(engine, "RULE_VERSION", "3.0.0")


def test_a_rule_switch_from_a_v1_record_is_named(env, monkeypatch):
    config, _, data_dir = env
    code, summary = run(config, monkeypatch, "2026-09-24T04:00")          # today's rule 2.1.0 ...
    first = sorted(list_records(data_dir / "forecasts"))[-1]
    old = load_record(first)
    old["schema"] = "steamsage.decision/1"                                # ... as an old /1 record
    import gzip
    first.write_bytes(gzip.compress(json.dumps(old).encode("utf-8")))
    switch_to_v3(monkeypatch)
    code, summary = run(config, monkeypatch, "2026-09-25T04:00")
    assert code == 0 and summary["rule"]["version"] == "3.0.0" and summary["baseline"] == first.name
    record = load_record(sorted(list_records(data_dir / "forecasts"))[-1])
    assert record["schema"] == "steamsage.decision/2"
    assert record["comparison"]["version_changes"] == ["規則 sweet-price 2.1.0 → 3.0.0"]
    assert "版本或偏好改變：規則 sweet-price 2.1.0 → 3.0.0" in page(data_dir)


def test_a_waiting_cost_change_is_named(env, monkeypatch):
    config, _, data_dir = env
    switch_to_v3(monkeypatch)
    run(config, monkeypatch, "2026-09-24T04:00")
    config.write_text(TEST_TOML.replace("wait_cost_twd = 20", "wait_cost_twd = 30"), encoding="utf-8")
    code, _ = run(config, monkeypatch, "2026-09-25T04:00")
    record = load_record(sorted(list_records(data_dir / "forecasts"))[-1])
    assert code == 0 and record["comparison"]["version_changes"] == ["等待成本從 NT$20 改成 NT$30"]
    assert "等待成本從 NT$20 改成 NT$30（部分變動可能來自這個改變）" in page(data_dir)


def test_a_preview_never_becomes_the_baseline(env, monkeypatch):
    config, _, data_dir = env
    code, summary = run(config, monkeypatch, "2026-09-24T04:00", "--rule", "3.0.0")
    assert code == 0 and summary["preview"] is True and summary["record"] is None
    assert list_records(data_dir / "forecasts") == []
    code, summary = run(config, monkeypatch, "2026-09-25T04:00")
    assert summary["baseline"] is None


def test_a_bundle_of_two_wishlist_games_reaches_the_report_and_the_record(env, monkeypatch):
    """feature 010 (tasks T023): a recorded bundle of Alpha and Beta becomes a card, both games point to it, and
    the official record keeps the same block."""
    from tests.forecast_builders import add_purchase_options

    config, db, data_dir = env
    pair = dict(kind="bundle", option_id=900, name="Alpha x Beta", original_cents=90000, final_cents=90000,
                role="other-games", bundle_discount_pct=10, before_bundle_cents=100000,
                contents=[{"app_id": 1, "type": None, "parent_app_id": None},
                          {"app_id": 2, "type": 0, "parent_app_id": None}])
    default = dict(kind="sub", option_id=100, name="Standard", original_cents=50000, final_cents=50000,
                   role="default")
    add_purchase_options(db, 1, "2026-09-23", [default, pair])
    add_purchase_options(db, 2, "2026-09-23", [default, {**pair, "is_default": False}])
    code, summary = run(config, monkeypatch, "2026-09-24T04:00")
    assert code == 0
    html = page(data_dir)
    assert '<section id="bundles"' in html and 'id="bundle-900"' in html and "Alpha x Beta" in html
    assert html.count('href="#bundle-900"') == 2
    record = load_record(data_dir / "forecasts" / "20260924T040000Z.json.gz")
    assert [b["id"] for b in record["bundles"]] == [900] and record["bundle_rule"]["name"] == "bundle-advice"
