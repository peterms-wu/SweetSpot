"""contracts/cli.md: `sweetspot compare` (tasks T035)."""

import io
import json

import pytest

from sweetspot import cli
from tests.config_builders import TEST_TOML
from sweetspot.forecast.models import CURRENT_MODEL
from tests.unit.forecast.test_compare import TW_BASE, US_BASE, result, shifted


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "load_secrets", lambda: cli.Secrets())
    path = tmp_path / "sweetspot.toml"
    path.write_text(TEST_TOML, encoding="utf-8")
    return path


def write(tmp_path, name, data):
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(list(argv), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_better_exits_0_and_records(config_path, tmp_path):
    a = write(tmp_path, "a.json", result(TW_BASE, US_BASE))
    b = write(tmp_path, "b.json", result(shifted(TW_BASE, -0.02), shifted(US_BASE, -0.02)))
    record = tmp_path / "records.md"
    code, out, _ = run("compare", a, b, "--record-to", str(record), "--json", "--config", str(config_path))
    summary = json.loads(out)
    assert code == cli.EXIT_OK and summary["verdict"] == "優於"
    assert summary["regions"]["TW"]["games"] == 200 and summary["record"] == str(record)
    assert "**判定：優於**" in record.read_text(encoding="utf-8")


def test_not_better_exits_2(config_path, tmp_path):
    a = write(tmp_path, "a.json", result(TW_BASE, US_BASE))
    b = write(tmp_path, "b.json", result(TW_BASE, US_BASE))
    code, out, _ = run("compare", a, b, "--json", "--config", str(config_path))
    assert code == cli.EXIT_PARTIAL and json.loads(out)["verdict"] == "未優於"


def test_different_dataset_exits_1(config_path, tmp_path):
    a = write(tmp_path, "a.json", result(TW_BASE))
    b = write(tmp_path, "b.json", result(TW_BASE, tw_id="c" * 64))
    code, _, err = run("compare", a, b, "--config", str(config_path))
    assert code == cli.EXIT_FAILED and "資料集不同" in err


def test_record_defaults_to_docs_model_comparisons(config_path, tmp_path):
    a = write(tmp_path, "a.json", result(TW_BASE, US_BASE))
    b = write(tmp_path, "b.json", result(TW_BASE, US_BASE))
    code, out, _ = run("compare", a, b, "--record", "--json", "--config", str(config_path))
    target = tmp_path / "docs" / "model" / "comparisons.md"
    assert json.loads(out)["record"] == str(target) and target.exists()


def test_compare_never_changes_the_current_model(config_path, tmp_path):
    before = CURRENT_MODEL
    a = write(tmp_path, "a.json", result(TW_BASE, US_BASE))
    b = write(tmp_path, "b.json", result(shifted(TW_BASE, -0.02), shifted(US_BASE, -0.02), params={"min_sales": 2,
                                                                                                    "history": "TW"}))
    run("compare", a, b, "--config", str(config_path))
    from sweetspot.forecast import models

    assert models.CURRENT_MODEL == before


def test_validation_attempts(config_path, tmp_path):
    """004 contracts/cli.md: --attempt / --change for validation-part records."""
    from tests.unit.forecast.test_compare import split_result

    a = write(tmp_path, "a.json", split_result("validation", TW_BASE, US_BASE))
    b = write(tmp_path, "b.json", split_result("validation", shifted(TW_BASE, -0.02), US_BASE, name="seasonal-record",
                                               params={"min_sales": 1}))
    record = tmp_path / "records.md"
    code, _, err = run("compare", a, b, "--record-to", str(record), "--config", str(config_path))
    assert code == cli.EXIT_FAILED and "--attempt" in err and not record.exists()
    code, out, err = run("compare", a, b, "--record-to", str(record), "--attempt", "1", "--json",
                         "--config", str(config_path))
    assert code == cli.EXIT_OK, err
    assert json.loads(out)["split"] == "validation"
    assert "（驗證組 · 第 1 次）" in record.read_text(encoding="utf-8")
    code, _, err = run("compare", a, b, "--record-to", str(record), "--attempt", "1", "--config", str(config_path))
    assert code == cli.EXIT_FAILED and "已有" in err
    code, _, err = run("compare", a, b, "--record-to", str(record), "--attempt", "2", "--change", "加上年齡",
                       "--config", str(config_path))
    assert code == cli.EXIT_OK, err
    assert "- 這次的修改：加上年齡" in record.read_text(encoding="utf-8")


# --- feature 008: --target-groups and attempts per model version (tasks T021) ------------------------------------

def test_target_groups_on_the_command_line(config_path, tmp_path):
    from tests.unit.forecast.test_compare import pair

    base, cand = pair(-0.15, +0.001)                     # the 1-sale group is not lower
    a, b = write(tmp_path, "a.json", base), write(tmp_path, "b.json", cand)
    code, out, _ = run("compare", a, b, "--target-groups", "0,1", "--json", "--config", str(config_path))
    summary = json.loads(out)
    assert code == cli.EXIT_PARTIAL and summary["verdict"] == "未優於"
    assert set(summary["groups"]) == {"0", "1"} and summary["groups"]["1"]["diff"] > 0
    code, _, err = run("compare", a, b, "--target-groups", "0,7", "--config", str(config_path))
    assert code == cli.EXIT_FAILED and "場數組" in err


def test_validation_attempts_count_per_model_version(config_path, tmp_path):
    from tests.unit.forecast.test_compare import split_result

    record = tmp_path / "records.md"
    a = write(tmp_path, "a.json", split_result("validation", TW_BASE, US_BASE))
    for version in ("1.0.0", "1.1.0"):                    # 1.1.0 starts again at attempt 1
        b = write(tmp_path, f"b{version}.json", split_result("validation", shifted(TW_BASE, -0.02), US_BASE,
                                                            name="seasonal-record", params={"min_sales": 1},
                                                            version=version))
        code, _, err = run("compare", a, b, "--record-to", str(record), "--attempt", "1", "--config", str(config_path))
        assert code == cli.EXIT_OK, err
    code, _, err = run("compare", a, b, "--record-to", str(record), "--attempt", "1", "--config", str(config_path))
    assert code == cli.EXIT_FAILED and "1.1.0" in err
