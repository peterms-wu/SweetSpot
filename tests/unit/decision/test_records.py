"""Forecast records and the comparison baseline (tasks T022; research R6; FR-015 to FR-019)."""

import gzip
import json

import pytest

from sweetspot.decision import records
from sweetspot.decision.records import (RecordError, find_baseline, list_records, load_record, record_name,
                                        write_record)
from tests.forecast_builders import dt


def contract(as_of: str, marker: int = 0) -> dict:
    return {"schema": "steamsage.decision/1", "as_of": as_of, "official": True, "decisions": [{"app_id": marker}]}


def test_name_is_the_as_of_in_utc():
    assert record_name(dt("2026-09-25T05:17:02")) == "20260925T051702Z.json.gz"


def test_write_and_load_round_trip(tmp_path):
    path = write_record(tmp_path, contract("2026-09-25T05:17:02Z", 7))
    assert path.name == "20260925T051702Z.json.gz"
    assert load_record(path)["decisions"] == [{"app_id": 7}]
    assert json.loads(gzip.decompress(path.read_bytes()))["as_of"] == "2026-09-25T05:17:02Z"


def test_same_content_same_bytes(tmp_path):
    a = write_record(tmp_path / "a", contract("2026-09-25T05:17:02Z"))
    b = write_record(tmp_path / "b", contract("2026-09-25T05:17:02Z"))
    assert a.read_bytes() == b.read_bytes()


def test_never_overwrites(tmp_path):
    write_record(tmp_path, contract("2026-09-25T05:17:02Z", 1))
    with pytest.raises(FileExistsError):
        write_record(tmp_path, contract("2026-09-25T05:17:02Z", 2))
    assert load_record(tmp_path / "20260925T051702Z.json.gz")["decisions"] == [{"app_id": 1}]


def test_failure_before_rename_leaves_no_record(tmp_path, monkeypatch):
    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(records.os, "replace", boom)
    with pytest.raises(OSError):
        write_record(tmp_path, contract("2026-09-25T05:17:02Z"))
    assert list_records(tmp_path) == []
    assert not list(tmp_path.glob("*.json.gz"))


def test_stray_tmp_files_are_not_records(tmp_path):
    (tmp_path / "20260925T051702Z.json.gz.tmp").write_bytes(b"half")
    assert list_records(tmp_path) == []
    assert list_records(tmp_path / "missing") == []


@pytest.mark.parametrize("content", [b"not gzip", gzip.compress(b"{not json"),
                                     gzip.compress(json.dumps({"schema": "other/1"}).encode())])
def test_load_rejects_broken_records(tmp_path, content):
    path = tmp_path / "20260101T000000Z.json.gz"
    path.write_bytes(content)
    with pytest.raises(RecordError):
        load_record(path)


def test_baseline_is_the_latest_record_of_an_earlier_taipei_day(tmp_path):
    write_record(tmp_path, contract("2026-09-23T10:00:00Z", 1))
    write_record(tmp_path, contract("2026-09-24T15:59:00Z", 2))        # Taipei 09-24 23:59
    write_record(tmp_path, contract("2026-09-24T16:00:00Z", 3))        # Taipei 09-25 00:00: same day as now
    path, data, skipped = find_baseline(tmp_path, dt("2026-09-25T05:00"))  # Taipei 09-25 13:00
    assert path.name == "20260924T155900Z.json.gz" and data["decisions"] == [{"app_id": 2}] and skipped == []


def test_same_day_records_are_never_the_baseline(tmp_path):
    write_record(tmp_path, contract("2026-09-25T01:00:00Z"))
    assert find_baseline(tmp_path, dt("2026-09-25T05:00")) == (None, None, [])


def test_broken_records_are_skipped_and_reported(tmp_path):
    write_record(tmp_path, contract("2026-09-23T10:00:00Z", 1))
    (tmp_path / "20260924T100000Z.json.gz").write_bytes(b"garbage")
    path, data, skipped = find_baseline(tmp_path, dt("2026-09-25T05:00"))
    assert path.name == "20260923T100000Z.json.gz" and skipped == ["20260924T100000Z.json.gz"]


# --- feature 005: /1 and /2 records are both readable (tasks T005) ----------------------------------------------

@pytest.mark.parametrize("schema", ["steamsage.decision/1", "steamsage.decision/2"])
def test_both_schema_versions_load(tmp_path, schema):
    path = tmp_path / "20260101T000000Z.json.gz"
    path.write_bytes(gzip.compress(json.dumps({"schema": schema, "as_of": "2026-01-01T00:00:00Z",
                                               "decisions": []}).encode()))
    assert load_record(path)["schema"] == schema


def test_unknown_schema_version_is_rejected(tmp_path):
    path = tmp_path / "20260101T000000Z.json.gz"
    path.write_bytes(gzip.compress(json.dumps({"schema": "steamsage.decision/3"}).encode()))
    with pytest.raises(RecordError):
        load_record(path)
