"""US5: import the legacy SteamSage cache (research R8; FR-019, FR-020; SC-005)."""

import hashlib
import json
from datetime import UTC, datetime

import pytest

from sweetspot.pipeline import legacy_import
from sweetspot.sources import legacy_cache
from sweetspot.store.writer import StoreWriter
from tests.conftest import FIXTURES

LEGACY = FIXTURES / "legacy"
NOW = datetime(2026, 9, 25, tzinfo=UTC)


def legacy_files(kind, sub=None):
    """Valid legacy files of a kind (the deliberately corrupted fixtures are excluded)."""
    for path in LEGACY.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            ident = data["identity"]
        except (ValueError, KeyError, TypeError):
            continue
        if path.stem != hashlib.sha256(json.dumps(ident, ensure_ascii=False, sort_keys=True).encode()).hexdigest():
            continue
        if ident and ident[0] == kind and (sub is None or (len(ident) > 5 and ident[5] == sub)):
            yield ident, data


@pytest.fixture
def writer(db_path):
    w = StoreWriter.open(db_path)
    yield w
    w.close()


def run_import(writer):
    return legacy_import.import_legacy(writer, legacy_cache.LegacyCache(LEGACY), now=NOW)


def test_reader_classifies_every_file():
    records = list(legacy_cache.LegacyCache(LEGACY).records())
    kinds = {type(r).__name__ for r in records}
    assert kinds == {"LegacyMapping", "LegacyHistory", "LegacyMetadata", "LegacyCatalog", "LegacySkip"}
    skips = {r.reason for r in records if isinstance(r, legacy_cache.LegacySkip)}
    assert skips == {"derived-data", "stale-snapshot", "truncated-catalog", "malformed-json", "bad-wrapper",
                     "identity-mismatch", "unsupported-scope"}


def test_history_rows_imported_with_original_retrieved_at(writer):
    summary = run_import(writer)
    expected = sum(len({(r["timestamp"], r["deal"]["cut"], r["deal"]["price"]["amountInt"])
                        for r in data["payload"] if r["shop"]["id"] == 61})
                   for _, data in legacy_files("itad-steam-verified-v1", "history"))
    rows = writer.conn.execute(
        "SELECT source, region, currency, retrieved_at FROM price_observations").fetchall()
    assert len(rows) == expected == summary["observations_added"]
    assert {r[:3] for r in rows} == {("legacy-itad", "TW", "TWD")}
    assert {r[3] for r in rows} == {"2026-09-22T16:58:55.573171Z"}
    first_flags = writer.conn.execute(
        "SELECT app_id, SUM(is_tracking_start) FROM price_observations GROUP BY app_id").fetchall()
    assert all(flag == 1 for _, flag in first_flags)


def test_mappings_imported_as_verified_legacy(writer):
    run_import(writer)
    mappings = writer.conn.execute("SELECT app_id, external_id, verification, checked_at FROM source_mappings")
    rows = mappings.fetchall()
    expected = {int(ident[1].split(":")[1]): data["payload"]["itad_id"]
                for ident, data in legacy_files("itad-steam-verified-v1", "identity") if ident[2] == "TW"}
    assert {r[0]: r[1] for r in rows} == expected
    assert {r[2] for r in rows} == {"verified-legacy"}


def test_metadata_becomes_static_facts(writer):
    run_import(writer)
    ident, data = next(legacy_files("publisher-metadata-v1"))
    app_id = int(ident[1].split(":")[1])
    facts = dict(writer.conn.execute(
        "SELECT field, value_json FROM product_facts WHERE app_id = ? AND source = 'legacy-import'", (app_id,)))
    assert json.loads(facts["publishers"]) == data["payload"]["publishers"]
    assert json.loads(facts["release_date"]) == data["payload"]["release_date"]
    assert json.loads(facts["product_type"]) == data["payload"]["subtype"]


def test_full_steam_release_payload_becomes_facts(writer):
    run_import(writer)
    ident, data = next(legacy_files("steam-release-v1"))
    app_id = int(ident[1].split(":")[1])
    name = writer.conn.execute(
        "SELECT value_json FROM product_facts WHERE app_id = ? AND field = 'name'", (app_id,)).fetchone()
    assert json.loads(name[0]) == data["payload"]["name"]


def test_catalog_v3_becomes_related_candidates(writer):
    run_import(writer)
    ident, data = next(legacy_files("publisher-catalog-v3"))
    rows = writer.conn.execute(
        "SELECT COUNT(*), MIN(pool), MIN(pool_detail) FROM reference_candidates").fetchone()
    assert rows == (len(set(data["payload"])), "related-publisher", ident[1])
    progress = writer.conn.execute("SELECT name, total_count, complete FROM catalog_progress").fetchone()
    assert progress == (ident[1], len(set(data["payload"])), 1)


def test_second_import_adds_nothing(writer):
    first = run_import(writer)
    counts = {t: writer.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("price_observations", "product_facts", "source_mappings", "reference_candidates")}
    second = run_import(writer)
    assert second["observations_added"] == 0 and second["records_imported"] == 0
    assert second["records_already_imported"] == first["records_imported"]
    assert counts == {t: writer.conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in counts}


def test_summary_lists_skips_by_reason(writer):
    summary = run_import(writer)
    assert summary["skipped"]["malformed-json"] == 1
    assert summary["skipped"]["identity-mismatch"] == 1
    assert sum(summary["skipped"].values()) == 8  # library, current, catalog v1+v2, 3 broken, US scope
    assert summary["files"] == len(list(LEGACY.glob("*.json")))


def test_source_directory_is_not_modified(writer, tmp_path):
    before = {p.name: (p.stat().st_mtime_ns, p.stat().st_size) for p in LEGACY.iterdir()}
    run_import(writer)
    assert {p.name: (p.stat().st_mtime_ns, p.stat().st_size) for p in LEGACY.iterdir()} == before


def test_missing_directory_is_an_error(writer, tmp_path):
    with pytest.raises(FileNotFoundError):
        legacy_import.import_legacy(writer, legacy_cache.LegacyCache(tmp_path / "nope"), now=NOW)


# --- feature 006 --------------------------------------------------------------------------------------------------

def test_legacy_history_rows_carry_the_apps_itad_product_when_known(writer):
    """Mapping files are imported before history files, so every history row of a mapped app is tagged."""
    run_import(writer)
    untagged = writer.conn.execute(
        "SELECT COUNT(*) FROM price_observations p WHERE external_id IS NULL AND EXISTS (SELECT 1 FROM "
        "source_mappings m WHERE m.app_id = p.app_id AND m.source = 'itad' AND m.external_id IS NOT NULL)").fetchone()[0]
    tagged = writer.conn.execute(
        "SELECT COUNT(*) FROM price_observations p JOIN source_mappings m ON m.app_id = p.app_id AND "
        "m.source = 'itad' AND m.external_id = p.external_id").fetchone()[0]
    assert untagged == 0 and tagged > 0
    before = writer.conn.execute("SELECT COUNT(*) FROM price_observations").fetchone()[0]
    run_import(writer)
    assert writer.conn.execute("SELECT COUNT(*) FROM price_observations").fetchone()[0] == before


def test_without_a_path_the_command_explains_itself(tmp_path, monkeypatch):
    """014 FR-010: the default is empty, so with no --path the command says what it is for and ends with 1."""
    import io

    from sweetspot import cli
    from tests.config_builders import TEST_TOML

    monkeypatch.setattr(cli, "load_secrets", lambda: cli.Secrets())
    (tmp_path / "sweetspot.toml").write_text(TEST_TOML, encoding="utf-8")
    out, err = io.StringIO(), io.StringIO()
    code = cli.main(["import-legacy", "--config", str(tmp_path / "sweetspot.toml")], stdout=out, stderr=err)
    assert code == cli.EXIT_FAILED
    assert "前身專案" in out.getvalue() and "import-legacy <路徑>" in out.getvalue()
