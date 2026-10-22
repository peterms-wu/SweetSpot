import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sweetspot.store import schema
from sweetspot.store.writer import NewObservation, StoreWriter

NOW = datetime(2026, 9, 25, tzinfo=UTC)


def obs(day, cut, region="TW", source="itad-history"):
    tw = region == "TW"
    return NewObservation(app_id=1, source=source, region=region, currency="TWD" if tw else None,
                          regular_cents=1000 if tw else None, price_cents=1000 * (100 - cut) // 100 if tw else None,
                          cut_pct=cut, observed_at=datetime(2025, 1, day, tzinfo=UTC), raw_observed_at=None,
                          retrieved_at=NOW)


def test_v1_database_gets_first_rows_flagged(db_path):
    w = StoreWriter.open(db_path)
    run = w.start_run("daily")
    w.add_observations(run, [obs(1, 50), obs(2, 0), obs(1, 50, region="US"), obs(3, 0, source="steam-current")])
    w.conn.execute("UPDATE schema_meta SET value = '1' WHERE key = 'schema_version'")  # pretend v1
    w.close()

    w = StoreWriter.open(db_path)
    flags = w.conn.execute(
        "SELECT region, source, observed_at, is_tracking_start FROM price_observations ORDER BY region, observed_at"
    ).fetchall()
    assert [f[3] for f in flags] == [1, 0, 0, 1]  # TW first, TW second, TW steam-current, US first
    assert w.conn.execute("SELECT value FROM schema_meta").fetchone()[0] == str(schema.SCHEMA_VERSION)  # v1 -> latest
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        w.conn.execute("UPDATE price_observations SET cut_pct = 0")
    w.close()


# --- feature 006: v2 -> v3 (data-model §3) ------------------------------------------------------------------

V2_SQL = Path(__file__).parents[1] / "fixtures" / "schema_v2.sql"
ITAD_ROWS = ("itad-history", "legacy-itad")


def make_v2(db_path) -> None:
    """A v2 database: app 1 and 2 have one ITAD id each, app 3 has two, app 4 has none."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(V2_SQL.read_text(encoding="utf-8"))
    mappings = [(1, "itad-1"), (2, "itad-2"), (2, "itad-2"), (3, "itad-3a"), (3, "itad-3b")]
    conn.executemany("INSERT INTO source_mappings (app_id, source, external_id, verification, checked_at) "
                     "VALUES (?, 'itad', ?, 'verified', '2026-09-20T00:00:00.000000Z')", mappings)
    rows = []
    for app in (1, 2, 3, 4):
        for day, source, region in ((1, "itad-history", "TW"), (2, "legacy-itad", "TW"), (1, "itad-history", "US"),
                                    (3, "steam-current", "TW")):
            tw = region == "TW"
            rows.append((app, source, region, "TWD" if tw else None, 1000 if tw else None, 500 if tw else None, 50,
                         f"2025-01-0{day}T00:00:00.000000Z", "2026-09-24T00:00:00.000000Z", int(day == 1)))
    conn.executemany("INSERT INTO price_observations (app_id, source, region, currency, regular_cents, price_cents, "
                     "cut_pct, observed_at, retrieved_at, is_tracking_start) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     rows)
    conn.executemany("INSERT INTO history_fetches (app_id, source, region, fetched_at, entries) VALUES "
                     "(?, 'itad', 'TW', '2026-09-24T00:00:00.000000Z', 2)", [(a,) for a in (1, 2, 3, 4)])
    conn.commit()
    conn.close()


def snapshot(conn, table, columns):
    return conn.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY rowid").fetchall()


OBS_COLUMNS = ("obs_id", "app_id", "source", "region", "currency", "regular_cents", "price_cents", "cut_pct",
               "observed_at", "raw_observed_at", "retrieved_at", "is_tracking_start", "anomaly", "run_id")


def test_v2_database_migrates_to_v3_and_backfills_external_ids(db_path):
    make_v2(db_path)
    before = sqlite3.connect(db_path)
    obs_before = snapshot(before, "price_observations", OBS_COLUMNS)
    fetch_before = snapshot(before, "history_fetches", ("app_id", "source", "region", "fetched_at", "entries"))
    before.close()

    w = StoreWriter.open(db_path)
    assert w.conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0] == str(
        schema.SCHEMA_VERSION)                   # v2 -> v3 -> latest
    assert snapshot(w.conn, "price_observations", OBS_COLUMNS) == obs_before
    assert snapshot(w.conn, "history_fetches", ("app_id", "source", "region", "fetched_at", "entries")) == fetch_before
    ext = {(a, s, r): e for a, s, r, e in w.conn.execute(
        "SELECT app_id, source, region, external_id FROM price_observations")}
    for (app, source, region), value in ext.items():
        expected = {1: "itad-1", 2: "itad-2"}.get(app) if source in ITAD_ROWS else None
        assert value == expected, (app, source, region)
    fetched = dict(w.conn.execute("SELECT app_id, external_id FROM history_fetches"))
    assert fetched == {1: "itad-1", 2: "itad-2", 3: None, 4: None}
    assert w.conn.execute("SELECT COUNT(*) FROM app_versions").fetchone()[0] == 0
    cols = {r[1] for r in w.conn.execute("PRAGMA table_info(current_price_checks)")}
    assert {"external_id", "itad_steam_deals"} <= cols
    w.add_version(None, 1, checked_at=NOW, status="no-option")     # row triggers fire only on existing rows
    for table in ("price_observations", "app_versions"):
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            w.conn.execute(f"DELETE FROM {table}")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        w.conn.execute("UPDATE price_observations SET external_id = 'x'")
    w.close()


def test_v3_unique_index_keeps_two_versions_apart(db_path):
    make_v2(db_path)
    w = StoreWriter.open(db_path)
    run = w.start_run("daily")
    same = dict(app_id=1, source="itad-history", region="TW", currency="TWD", regular_cents=1000, price_cents=500,
                cut_pct=50, observed_at=datetime(2025, 1, 1, tzinfo=UTC), raw_observed_at=None, retrieved_at=NOW)
    assert w.add_observations(run, [NewObservation(**same, external_id="itad-1")]) == 0     # backfilled duplicate
    assert w.add_observations(run, [NewObservation(**same, external_id="itad-new")]) == 1   # another version
    assert w.add_observations(run, [NewObservation(**same, external_id="itad-new")]) == 0
    w.close()


def test_migration_backs_up_the_v2_database_once(db_path):
    make_v2(db_path)
    StoreWriter.open(db_path).close()
    backup = db_path.with_name("sweetspot.db.bak-v2")
    assert backup.exists()
    old = sqlite3.connect(backup)
    assert old.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0] == "2"
    assert "external_id" not in {r[1] for r in old.execute("PRAGMA table_info(price_observations)")}
    old.close()
    stamp = backup.stat().st_mtime_ns
    StoreWriter.open(db_path).close()          # already v3: no second backup
    assert backup.stat().st_mtime_ns == stamp


def test_failed_migration_rolls_back_to_v2(db_path, monkeypatch):
    make_v2(db_path)

    def boom(conn):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(schema, "_backfill_external_ids", boom)
    with pytest.raises(RuntimeError, match="simulated"):
        StoreWriter.open(db_path)
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0] == "2"
    assert "external_id" not in {r[1] for r in conn.execute("PRAGMA table_info(price_observations)")}
    triggers = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    assert "trg_price_observations_no_update" in triggers
    conn.close()


# --- feature 009: v3 -> v4 (data-model §1) ------------------------------------------------------------------

V3_TABLES = ("price_observations", "product_facts", "source_mappings", "app_versions", "history_fetches",
             "current_price_checks", "wishlist_membership", "products", "runs")
PURCHASE_OPTION_COLUMNS = {
    "option_row_id", "app_id", "checked_at", "run_id", "kind", "option_id", "name", "original_cents", "final_cents",
    "position", "is_default", "role", "contents_json", "contents_checked_at", "external_id", "verification",
    "verified_by", "verified_at", "reason_code", "reason_detail", "warnings_json", "aliases_json", "itad_steam_deals"}
V5_COLUMNS = {"bundle_discount_pct", "before_bundle_cents"}          # feature 010, data-model §1


def make_v3(path):
    """A database as feature 006 left it: everything but purchase_options, schema_version 3."""
    w = StoreWriter.open(path)
    run = w.start_run("daily")
    w.add_observations(run, [obs(1, 50), obs(2, 0), obs(1, 50, region="US")])
    w.add_version(run, 1, checked_at=NOW, status="no-option")
    w.conn.execute("DROP TRIGGER IF EXISTS trg_purchase_options_no_update")
    w.conn.execute("DROP TRIGGER IF EXISTS trg_purchase_options_no_delete")
    w.conn.execute("DROP TABLE IF EXISTS purchase_options")
    w.conn.execute("UPDATE schema_meta SET value = '3' WHERE key = 'schema_version'")
    w.close()


def dump(conn, table):
    return sorted(conn.execute(f"SELECT * FROM {table}").fetchall(), key=repr)


def test_v3_database_migrates_to_v4_without_touching_other_tables(db_path):
    make_v3(db_path)
    before = sqlite3.connect(db_path)
    rows_before = {t: dump(before, t) for t in V3_TABLES}
    before.close()

    w = StoreWriter.open(db_path)
    assert w.conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0] == str(
        schema.SCHEMA_VERSION)                   # -> latest
    assert {t: dump(w.conn, t) for t in V3_TABLES} == rows_before
    assert w.conn.execute("SELECT COUNT(*) FROM purchase_options").fetchone()[0] == 0
    assert {r[1] for r in w.conn.execute("PRAGMA table_info(purchase_options)")} ==         PURCHASE_OPTION_COLUMNS | V5_COLUMNS
    w.conn.execute("INSERT INTO purchase_options (app_id, checked_at, kind, option_id, original_cents, final_cents, "
                   "position, is_default, role) VALUES (1, '2026-09-27T00:00:00Z', 'sub', 5, 100, 100, 0, 1, 'default')")
    for action in ("UPDATE purchase_options SET name = 'x'", "DELETE FROM purchase_options"):
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            w.conn.execute(action)
    w.close()


def test_migration_backs_up_the_v3_database_once(db_path):
    make_v3(db_path)
    StoreWriter.open(db_path).close()
    backup = db_path.with_name("sweetspot.db.bak-v3")
    assert backup.exists()
    old = sqlite3.connect(backup)
    assert old.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0] == "3"
    assert old.execute("SELECT name FROM sqlite_master WHERE name = 'purchase_options'").fetchone() is None
    old.close()
    stamp = backup.stat().st_mtime_ns
    StoreWriter.open(db_path).close()          # already current: no second backup
    assert backup.stat().st_mtime_ns == stamp


def test_failed_v4_migration_rolls_back_to_v3(db_path, monkeypatch):
    make_v3(db_path)
    original = schema._purchase_option_statements

    def broken():
        return original() + ["SELECT no_such_function()"]

    monkeypatch.setattr(schema, "_purchase_option_statements", broken)
    with pytest.raises(sqlite3.OperationalError):
        StoreWriter.open(db_path)
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0] == "3"
    assert conn.execute("SELECT name FROM sqlite_master WHERE name = 'purchase_options'").fetchone() is None
    conn.close()


# --- feature 010: v4 -> v5 (data-model §1) ------------------------------------------------------------------

V4_TABLES = V3_TABLES + ("purchase_options",)


def make_v4(path):
    """A database as feature 009 left it: purchase_options without the two v5 columns, schema_version 4."""
    w = StoreWriter.open(path)
    run = w.start_run("daily")
    w.add_observations(run, [obs(1, 50), obs(2, 0)])
    w.conn.execute("INSERT INTO purchase_options (app_id, checked_at, kind, option_id, original_cents, final_cents, "
                   "position, is_default, role) VALUES (1, '2026-09-27T00:00:00Z', 'bundle', 74895, 132800, 115000, "
                   "0, 0, 'other-games')")
    for column in sorted(V5_COLUMNS):
        w.conn.execute(f"ALTER TABLE purchase_options DROP COLUMN {column}")
    w.conn.execute("UPDATE schema_meta SET value = '4' WHERE key = 'schema_version'")
    w.close()


def test_v4_database_migrates_to_v5_adding_two_null_columns(db_path):
    make_v4(db_path)
    before = sqlite3.connect(db_path)
    rows_before = {t: dump(before, t) for t in V3_TABLES}
    options_before = dump(before, "purchase_options")
    before.close()

    w = StoreWriter.open(db_path)
    assert w.conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0] == str(
        schema.SCHEMA_VERSION)                   # -> latest
    assert {t: dump(w.conn, t) for t in V3_TABLES} == rows_before
    assert {r[1] for r in w.conn.execute("PRAGMA table_info(purchase_options)")} ==         PURCHASE_OPTION_COLUMNS | V5_COLUMNS
    rows = w.conn.execute("SELECT * FROM purchase_options").fetchall()
    assert [r[:-2] for r in rows] == options_before and [r[-2:] for r in rows] == [(None, None)]   # unknown, not 0
    for action in ("UPDATE purchase_options SET bundle_discount_pct = 10", "DELETE FROM purchase_options"):
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            w.conn.execute(action)
    w.close()


def test_migration_backs_up_the_v4_database_once(db_path):
    make_v4(db_path)
    StoreWriter.open(db_path).close()
    backup = db_path.with_name("sweetspot.db.bak-v4")
    assert backup.exists()
    old = sqlite3.connect(backup)
    assert old.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0] == "4"
    assert not V5_COLUMNS & {r[1] for r in old.execute("PRAGMA table_info(purchase_options)")}
    old.close()
    stamp = backup.stat().st_mtime_ns
    StoreWriter.open(db_path).close()          # already the latest: no second backup
    assert backup.stat().st_mtime_ns == stamp


def test_failed_v5_migration_rolls_back_to_v4(db_path, monkeypatch):
    make_v4(db_path)
    original = schema._v5_statements

    def broken(conn):
        return original(conn) + ["SELECT no_such_function()"]

    monkeypatch.setattr(schema, "_v5_statements", broken)
    with pytest.raises(sqlite3.OperationalError):
        StoreWriter.open(db_path)
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0] == "4"
    assert not V5_COLUMNS & {r[1] for r in conn.execute("PRAGMA table_info(purchase_options)")}
    conn.close()


# --- feature 012: v5 -> v6 (data-model §1) ------------------------------------------------------------------

CALENDAR_TABLES = ("calendar_fetches", "sale_sightings")
FETCH = ("INSERT INTO calendar_fetches (fetched_at, url, status, accepted) "
         "VALUES ('2026-09-27T12:00:00Z', 'https://example.test/', 'ok', 1)")
SIGHTING = ("INSERT INTO sale_sightings (fetch_id, season, year, starts_at, ends_at) "
            "VALUES (1, 'autumn', 2027, '2027-09-30T17:00:00Z', '2027-10-07T17:00:00Z')")


def make_v5(path):
    """A database as feature 010 left it: no calendar tables, schema_version 5."""
    w = StoreWriter.open(path)
    run = w.start_run("daily")
    w.add_observations(run, [obs(1, 50), obs(2, 0)])
    for table in CALENDAR_TABLES[::-1]:
        w.conn.execute(f"DROP TABLE {table}")
    w.conn.execute("UPDATE schema_meta SET value = '5' WHERE key = 'schema_version'")
    w.close()


def test_new_database_has_the_calendar_tables(db_path):
    w = StoreWriter.open(db_path)
    assert schema.SCHEMA_VERSION >= 6
    names = {r[0] for r in w.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert set(CALENDAR_TABLES) <= names
    w.close()


def test_v5_database_migrates_to_v6_with_empty_calendar_tables(db_path):
    make_v5(db_path)
    before = sqlite3.connect(db_path)
    rows_before = {t: dump(before, t) for t in V4_TABLES}
    before.close()

    w = StoreWriter.open(db_path)
    assert w.conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0] == str(
        schema.SCHEMA_VERSION)
    assert {t: dump(w.conn, t) for t in V4_TABLES} == rows_before
    for table in CALENDAR_TABLES:
        assert w.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert db_path.with_name("sweetspot.db.bak-v5").exists()
    w.close()


def test_calendar_tables_are_append_only(db_path):
    w = StoreWriter.open(db_path)
    w.conn.execute(FETCH)
    w.conn.execute(SIGHTING)
    for action in ("UPDATE calendar_fetches SET status = 'failed'", "DELETE FROM calendar_fetches",
                   "UPDATE sale_sightings SET year = 2028", "DELETE FROM sale_sightings"):
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            w.conn.execute(action)
    with pytest.raises(sqlite3.IntegrityError):
        w.conn.execute(SIGHTING)                 # one row per sale per fetch
    with pytest.raises(sqlite3.IntegrityError):
        w.conn.execute(FETCH.replace("'ok'", "'maybe'"))
    w.close()


def test_failed_v6_migration_rolls_back_to_v5(db_path, monkeypatch):
    make_v5(db_path)
    original = schema._calendar_statements

    def broken():
        return original() + ["SELECT no_such_function()"]

    monkeypatch.setattr(schema, "_calendar_statements", broken)
    with pytest.raises(sqlite3.OperationalError):
        StoreWriter.open(db_path)
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0] == "5"
    assert not {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")} & set(CALENDAR_TABLES)
    conn.close()


def test_read_only_store_refuses_a_v5_database(db_path):
    from sweetspot.store.query import PriceStore

    make_v5(db_path)
    with pytest.raises(Exception, match="update"):
        PriceStore.open(db_path)


# --- fix-quarantine: v6 -> v7, the unique key separates quarantined rows from valid ones --------------------------

V6_INDEX = ("CREATE UNIQUE INDEX ux_observation ON price_observations (app_id, source, region, "
            "IFNULL(external_id, ''), observed_at, IFNULL(price_cents, -1), IFNULL(regular_cents, -1), "
            "IFNULL(cut_pct, -1))")


def make_v6(path):
    """A database as feature 013 left it: the unique key without anomaly, schema_version 6; one quarantined row."""
    w = StoreWriter.open(path)
    run = w.start_run("daily")
    late = NewObservation(app_id=1, source="itad-history", region="TW", currency="TWD", regular_cents=1000,
                          price_cents=670, cut_pct=33, observed_at=NOW + timedelta(seconds=61), raw_observed_at=None,
                          retrieved_at=NOW)
    w.add_observations(run, [obs(1, 50), obs(2, 0), late])
    w.conn.execute("DROP INDEX ux_observation")
    w.conn.execute(V6_INDEX)
    w.conn.execute("UPDATE schema_meta SET value = '6' WHERE key = 'schema_version'")
    w.close()


def index_sql(conn):
    return conn.execute("SELECT sql FROM sqlite_master WHERE name = 'ux_observation'").fetchone()[0]


def test_new_database_has_the_v7_unique_key(db_path):
    w = StoreWriter.open(db_path)
    assert schema.SCHEMA_VERSION >= 7 and "anomaly IS NULL" in index_sql(w.conn)
    w.close()


def test_v6_database_migrates_to_v7_changing_only_the_index(db_path):
    make_v6(db_path)
    before = sqlite3.connect(db_path)
    rows_before = {t: dump(before, t) for t in V4_TABLES + CALENDAR_TABLES}
    before.close()

    w = StoreWriter.open(db_path)
    assert w.conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0] == str(
        schema.SCHEMA_VERSION)
    assert "anomaly IS NULL" in index_sql(w.conn)
    assert {t: dump(w.conn, t) for t in V4_TABLES + CALENDAR_TABLES} == rows_before     # no row is touched
    assert db_path.with_name("sweetspot.db.bak-v6").exists()
    # the quarantined event can now be added again once it is fetched with a later retrieved_at
    run = w.start_run("daily")
    again = NewObservation(app_id=1, source="itad-history", region="TW", currency="TWD", regular_cents=1000,
                           price_cents=670, cut_pct=33, observed_at=NOW + timedelta(seconds=61),
                           raw_observed_at=None, retrieved_at=NOW + timedelta(days=1))
    assert w.add_observations(run, [again]) == 1
    w.close()


def test_failed_v7_migration_rolls_back_to_v6(db_path, monkeypatch):
    make_v6(db_path)
    monkeypatch.setattr(schema, "OBSERVATION_INDEX", "CREATE UNIQUE INDEX ux_observation ON no_such_table (x)")
    with pytest.raises(sqlite3.OperationalError):
        StoreWriter.open(db_path)
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()[0] == "6"
    assert "anomaly" not in index_sql(conn)
    conn.close()
