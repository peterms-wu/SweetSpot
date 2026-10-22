"""SQLite schema (see specs/001-price-data-foundation/data-model.md)."""

import sqlite3
import time
from pathlib import Path

SCHEMA_VERSION = 7
# v2: is_tracking_start marks the first row of every history series, not only zero-discount first rows.
# v3 (feature 006): ITAD rows, history fetches and price checks record their ITAD product; app_versions table.
# v4 (feature 009): purchase_options table (every purchase option of every tracked app, once per daily update).
# v5 (feature 010): purchase_options.bundle_discount_pct and before_bundle_cents (Steam's bundle discount).

RUN_KINDS = ("daily", "reference", "legacy-import", "calendar-check")
RUN_STATUSES = ("running", "completed", "partial", "failed", "interrupted")
STAGES = ("wishlist", "current-price", "metadata", "mapping", "history-tw", "history-aux", "reference", "import")
ITEM_STATUSES = ("ok", "reused", "skipped", "failed", "unsupported", "delisted", "not-found")
MEMBERSHIP_STATES = ("in_wishlist", "removed_tracking", "reference_only")
VERIFICATIONS = ("verified", "verified-legacy", "rejected", "pending")
VERSION_STATUSES = ("ok", "no-option", "ambiguous", "not-in-itad")
VERSION_VERIFICATIONS = ("verified", "rejected")
VERSION_VERIFIED_BY = ("own-mapping", "version-check", "cached")
ITAD_HISTORY_SOURCES = ("itad-history", "legacy-itad")
# feature 009 (research R3): an edition's ITAD history is stored under the wishlist app with its own product id and
# its own source, so every reader of ITAD_HISTORY_SOURCES (default series, sale detection, datasets) ignores it.
OPTION_HISTORY_SOURCE = "itad-option-history"
OPTION_FETCH_SOURCE = "itad-option"
HISTORY_FETCH_SOURCE = "itad"
OPTION_KINDS = ("sub", "bundle")
OPTION_ROLES = ("default", "edition", "other-games", "without-app", "unknown")

# field -> volatility (data-model §3). Volatile values change over time and must not leak into backtests.
FACT_VOLATILITY = {
    "name": "static",
    "product_type": "static",
    "parent_app_id": "static",
    "publishers": "static",
    "developers": "static",
    "release_date": "static",
    "release_state": "static",
    "genres": "static",
    "is_indie": "static",
    "is_free": "static",
    "publisher_catalog_size": "volatile",
    "review_count_total": "volatile",
    "review_count_filtered": "volatile",
    "review_percent_positive": "volatile",
    "tags": "volatile",
}

APPEND_ONLY_TABLES = ("price_observations", "product_facts", "source_mappings", "app_versions", "purchase_options")
_DDL_APPEND_ONLY = APPEND_ONLY_TABLES[:-1]      # purchase_options and its triggers come from _migrate_to_v4


def _in(values: tuple[str, ...]) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


DDL = f"""
CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN {_in(RUN_KINDS)}),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK (status IN {_in(RUN_STATUSES)}),
    summary_json TEXT,
    pid INTEGER
);

CREATE TABLE IF NOT EXISTS run_item_results (
    run_id TEXT NOT NULL,
    app_id INTEGER,
    stage TEXT NOT NULL CHECK (stage IN {_in(STAGES)}),
    status TEXT NOT NULL CHECK (status IN {_in(ITEM_STATUSES)}),
    reason_code TEXT,
    message TEXT,
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_item_results_run ON run_item_results (run_id, app_id);

CREATE TABLE IF NOT EXISTS wishlist_syncs (
    sync_id TEXT PRIMARY KEY,
    source_url TEXT NOT NULL,
    attempted_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ok', 'empty', 'rejected')),
    reject_reason TEXT,
    item_count INTEGER,
    run_id TEXT
);

CREATE TABLE IF NOT EXISTS wishlist_items (
    sync_id TEXT NOT NULL,
    app_id INTEGER NOT NULL,
    priority INTEGER,
    date_added TEXT,
    PRIMARY KEY (sync_id, app_id)
);

CREATE TABLE IF NOT EXISTS wishlist_membership (
    app_id INTEGER PRIMARY KEY,
    state TEXT NOT NULL CHECK (state IN {_in(MEMBERSHIP_STATES)}),
    first_added_at TEXT NOT NULL,
    removed_at TEXT,
    track_until TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    app_id INTEGER PRIMARY KEY,
    first_seen_at TEXT NOT NULL,
    first_seen_via TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS product_facts (
    fact_id INTEGER PRIMARY KEY AUTOINCREMENT,
    app_id INTEGER NOT NULL,
    field TEXT NOT NULL,
    value_json TEXT,
    volatility TEXT NOT NULL CHECK (volatility IN ('static', 'volatile')),
    source TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    run_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_facts_lookup ON product_facts (app_id, field, retrieved_at);

CREATE TABLE IF NOT EXISTS source_mappings (
    mapping_id INTEGER PRIMARY KEY AUTOINCREMENT,
    app_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    external_id TEXT,
    verification TEXT NOT NULL CHECK (verification IN {_in(VERIFICATIONS)}),
    reason_code TEXT,
    warnings_json TEXT,
    aliases_json TEXT,
    checked_at TEXT NOT NULL,
    run_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_mappings_lookup ON source_mappings (app_id, source, checked_at);

CREATE TABLE IF NOT EXISTS price_observations (
    obs_id INTEGER PRIMARY KEY AUTOINCREMENT,
    app_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    region TEXT NOT NULL,
    currency TEXT,
    regular_cents INTEGER,
    price_cents INTEGER,
    cut_pct INTEGER,
    observed_at TEXT NOT NULL,
    raw_observed_at TEXT,
    retrieved_at TEXT NOT NULL,
    is_tracking_start INTEGER NOT NULL DEFAULT 0,
    anomaly TEXT,
    run_id TEXT,
    external_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_observation_asof ON price_observations (app_id, region, observed_at);

-- One row per history request, so "fetched but empty" differs from "never fetched" (FR-022).
CREATE TABLE IF NOT EXISTS history_fetches (
    app_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    region TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    entries INTEGER NOT NULL,
    run_id TEXT,
    external_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_history_fetches ON history_fetches (app_id, region, fetched_at);

CREATE TABLE IF NOT EXISTS current_price_checks (
    run_id TEXT NOT NULL,
    app_id INTEGER NOT NULL,
    steam_price_cents INTEGER,
    steam_regular_cents INTEGER,
    itad_price_cents INTEGER,
    itad_regular_cents INTEGER,
    match INTEGER,
    checked_at TEXT NOT NULL,
    external_id TEXT,
    itad_steam_deals INTEGER
);

-- feature 006: one row per wishlist app per daily update (data-model §1), append-only.
CREATE TABLE IF NOT EXISTS app_versions (
    version_row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    app_id INTEGER NOT NULL,
    checked_at TEXT NOT NULL,
    run_id TEXT,
    status TEXT NOT NULL CHECK (status IN {_in(VERSION_STATUSES)}),
    package_id INTEGER,
    package_name TEXT,
    regular_cents INTEGER,
    price_cents INTEGER,
    external_id TEXT,
    itad_title TEXT,
    verification TEXT CHECK (verification IS NULL OR verification IN {_in(VERSION_VERIFICATIONS)}),
    verified_by TEXT CHECK (verified_by IS NULL OR verified_by IN {_in(VERSION_VERIFIED_BY)}),
    verified_at TEXT,
    reason_code TEXT,
    reason_detail TEXT,
    warnings_json TEXT,
    aliases_json TEXT,
    itad_steam_deals INTEGER
);
CREATE INDEX IF NOT EXISTS ix_app_versions ON app_versions (app_id, checked_at);

CREATE TABLE IF NOT EXISTS reference_candidates (
    app_id INTEGER NOT NULL,
    pool TEXT NOT NULL CHECK (pool IN ('related-publisher', 'related-developer', 'broad')),
    pool_detail TEXT NOT NULL,
    sample_version TEXT NOT NULL,
    shuffle_rank INTEGER,
    status TEXT NOT NULL CHECK (status IN ('pending', 'accepted', 'rejected', 'fetched', 'failed')),
    reject_reason TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (app_id, pool, pool_detail, sample_version)
);

CREATE TABLE IF NOT EXISTS catalog_progress (
    kind TEXT NOT NULL CHECK (kind IN ('publisher', 'developer')),
    name TEXT NOT NULL,
    next_start INTEGER NOT NULL DEFAULT 0,
    total_count INTEGER,
    complete INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (kind, name)
);

CREATE TABLE IF NOT EXISTS steam_app_list (
    app_id INTEGER PRIMARY KEY,
    name TEXT,
    last_modified INTEGER,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sale_estimates (
    estimate_id INTEGER PRIMARY KEY AUTOINCREMENT,
    season TEXT NOT NULL,
    year INTEGER NOT NULL,
    est_start TEXT NOT NULL,
    est_end TEXT NOT NULL,
    basis_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    superseded_at TEXT
);

CREATE TABLE IF NOT EXISTS region_consistency (
    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL,
    aux_region TEXT NOT NULL,
    overlap_start TEXT,
    overlap_end TEXT,
    days_compared INTEGER NOT NULL,
    days_same_cut INTEGER NOT NULL,
    sales_tw INTEGER NOT NULL,
    sales_matched INTEGER NOT NULL,
    computed_at TEXT NOT NULL
);
"""


def _trigger(table: str, action: str) -> str:
    return (f"CREATE TRIGGER IF NOT EXISTS trg_{table}_no_{action.lower()} BEFORE {action} ON {table} "
            f"BEGIN SELECT RAISE(ABORT, 'append-only: {table}'); END")


def _append_only_triggers() -> str:
    return "\n".join(_trigger(t, a) + ";" for t in _DDL_APPEND_ONLY for a in ("UPDATE", "DELETE"))


def _purchase_option_statements() -> list[str]:
    """feature 009, data-model §1: one row per purchase option per daily update, append-only."""
    return [
        f"""CREATE TABLE IF NOT EXISTS purchase_options (
    option_row_id INTEGER PRIMARY KEY AUTOINCREMENT,
    app_id INTEGER NOT NULL,
    checked_at TEXT NOT NULL,
    run_id TEXT,
    kind TEXT NOT NULL CHECK (kind IN {_in(OPTION_KINDS)}),
    option_id INTEGER NOT NULL,
    name TEXT,
    original_cents INTEGER NOT NULL,
    final_cents INTEGER NOT NULL,
    position INTEGER NOT NULL,
    is_default INTEGER NOT NULL,
    role TEXT NOT NULL CHECK (role IN {_in(OPTION_ROLES)}),
    contents_json TEXT,
    contents_checked_at TEXT,
    external_id TEXT,
    verification TEXT CHECK (verification IS NULL OR verification IN {_in(VERSION_VERIFICATIONS)}),
    verified_by TEXT CHECK (verified_by IS NULL OR verified_by IN {_in(VERSION_VERIFIED_BY)}),
    verified_at TEXT,
    reason_code TEXT,
    reason_detail TEXT,
    warnings_json TEXT,
    aliases_json TEXT,
    itad_steam_deals INTEGER
)""",
        "CREATE INDEX IF NOT EXISTS ix_purchase_options ON purchase_options (app_id, checked_at)",
        "CREATE INDEX IF NOT EXISTS ix_purchase_options_option ON purchase_options "
        "(app_id, kind, option_id, checked_at)",
        _trigger("purchase_options", "UPDATE"),
        _trigger("purchase_options", "DELETE"),
    ]


def _migrate_to_v4(conn: sqlite3.Connection) -> None:
    """Feature 009: only a new table; nothing existing is touched. One transaction, so a failure leaves v3."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        for statement in _purchase_option_statements():
            conn.execute(statement)
        conn.execute("UPDATE schema_meta SET value = '4' WHERE key = 'schema_version' AND CAST(value AS INTEGER) < 4")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def connect(path: Path, readonly: bool = False) -> sqlite3.Connection:
    """Open the database. Writers use autocommit mode and manage transactions explicitly."""
    path = Path(path)
    if readonly:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, isolation_level=None)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _current_version(conn: sqlite3.Connection) -> int | None:
    try:
        row = conn.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
    except sqlite3.OperationalError:
        return None
    return int(row[0]) if row else None


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """The only sanctioned correction of append-only data: flag the first row of each history series.

    The UPDATE trigger is dropped and recreated inside one transaction, so nothing else can slip through.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DROP TRIGGER IF EXISTS trg_price_observations_no_update")
        conn.execute(
            "UPDATE price_observations SET is_tracking_start = 1 WHERE source IN ('itad-history', 'legacy-itad') "
            "AND is_tracking_start = 0 AND observed_at = (SELECT MIN(p.observed_at) FROM price_observations p "
            "WHERE p.app_id = price_observations.app_id AND p.region = price_observations.region "
            "AND p.source = price_observations.source)"
        )
        conn.execute(
            "CREATE TRIGGER trg_price_observations_no_update BEFORE UPDATE ON price_observations "
            "BEGIN SELECT RAISE(ABORT, 'append-only: price_observations'); END"
        )
        conn.execute("UPDATE schema_meta SET value = '2' WHERE key = 'schema_version'")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


V5_COLUMNS = (("bundle_discount_pct", "INTEGER"), ("before_bundle_cents", "INTEGER"))


def _v5_statements(conn: sqlite3.Connection) -> list[str]:
    """feature 010, data-model §1: two nullable columns; rows written before stay NULL (unknown, not 0)."""
    have = _columns(conn, "purchase_options")
    return [f"ALTER TABLE purchase_options ADD COLUMN {c} {kind}" for c, kind in V5_COLUMNS if c not in have]


def _migrate_to_v5(conn: sqlite3.Connection) -> None:
    """One transaction (SQLite's ALTER TABLE is transactional), so a failure leaves v4."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        for statement in _v5_statements(conn):
            conn.execute(statement)
        conn.execute("UPDATE schema_meta SET value = '5' WHERE key = 'schema_version' AND CAST(value AS INTEGER) < 5")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


FETCH_STATUSES = ("ok", "no_dates", "failed", "denied", "rate_limited")
SEASONS = ("spring", "summer", "autumn", "winter")


def _calendar_statements() -> list[str]:
    """feature 012, data-model §1: every read of the official seasonal sales page, and the sales each successful read
    listed. Both append-only; first and last sightings are derived by query."""
    return [
        f"""CREATE TABLE IF NOT EXISTS calendar_fetches (
    fetch_id INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at TEXT NOT NULL,
    url TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN {_in(FETCH_STATUSES)}),
    reason TEXT,
    http_status INTEGER,
    bytes INTEGER,
    page_sha256 TEXT,
    accepted INTEGER NOT NULL DEFAULT 0,
    pending INTEGER NOT NULL DEFAULT 0,
    rejected_json TEXT NOT NULL DEFAULT '[]',
    run_id TEXT
)""",
        f"""CREATE TABLE IF NOT EXISTS sale_sightings (
    fetch_id INTEGER NOT NULL REFERENCES calendar_fetches (fetch_id),
    season TEXT NOT NULL CHECK (season IN {_in(SEASONS)}),
    year INTEGER NOT NULL,
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    PRIMARY KEY (fetch_id, season, year)
)""",
        "CREATE INDEX IF NOT EXISTS ix_calendar_fetches_time ON calendar_fetches (fetched_at)",
        "CREATE INDEX IF NOT EXISTS ix_sale_sightings_sale ON sale_sightings (season, year)",
        *(_trigger(table, action) for table in ("calendar_fetches", "sale_sightings") for action in ("UPDATE", "DELETE")),
    ]


def _migrate_to_v6(conn: sqlite3.Connection) -> None:
    """Feature 012: only two new tables; nothing existing is touched. One transaction, so a failure leaves v5."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        for statement in _calendar_statements():
            conn.execute(statement)
        conn.execute("UPDATE schema_meta SET value = '6' WHERE key = 'schema_version' AND CAST(value AS INTEGER) < 6")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def _migrate_to_v7(conn: sqlite3.Connection) -> None:
    """fix-quarantine: replace the observation unique key with one that tells quarantined rows from valid ones. Only
    the index changes; no row is read differently or touched. One transaction, so a failure leaves v6."""
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'index' AND name = 'ux_observation'").fetchone()
    if row is not None and "anomaly IS NULL" in row[0]:
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DROP INDEX IF EXISTS ux_observation")
        conn.execute(OBSERVATION_INDEX)
        conn.execute("UPDATE schema_meta SET value = '7' WHERE key = 'schema_version' AND CAST(value AS INTEGER) < 7")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def _add_column(conn: sqlite3.Connection, table: str, column: str, kind: str) -> None:
    if column not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")


def _backfill_external_ids(conn: sqlite3.Connection) -> int:
    """Tag pre-006 ITAD rows and history fetches with the app's ITAD product. Only apps that were ever mapped to
    exactly one ITAD id are tagged; any other app keeps NULL, which readers treat as its own product (research R3)."""
    conn.execute("CREATE TEMP TABLE _own_ids (app_id INTEGER PRIMARY KEY, external_id TEXT NOT NULL)")
    conn.execute(
        "INSERT INTO _own_ids SELECT app_id, MIN(external_id) FROM source_mappings WHERE source = 'itad' "
        "AND external_id IS NOT NULL GROUP BY app_id HAVING COUNT(DISTINCT external_id) = 1")
    conn.execute(
        "UPDATE price_observations SET external_id = (SELECT o.external_id FROM _own_ids o "
        "WHERE o.app_id = price_observations.app_id) "
        f"WHERE external_id IS NULL AND source IN {_in(ITAD_HISTORY_SOURCES)} "
        "AND app_id IN (SELECT app_id FROM _own_ids)")
    conn.execute(
        "UPDATE history_fetches SET external_id = (SELECT o.external_id FROM _own_ids o "
        "WHERE o.app_id = history_fetches.app_id) "
        "WHERE external_id IS NULL AND app_id IN (SELECT app_id FROM _own_ids)")
    tagged = conn.execute("SELECT COUNT(*) FROM price_observations WHERE external_id IS NOT NULL").fetchone()[0]
    conn.execute("DROP TABLE temp._own_ids")
    return tagged


def _migrate_v2_to_v3(conn: sqlite3.Connection) -> int:
    """The second sanctioned correction of append-only data (feature 006, data-model §3): add the ITAD product
    columns and backfill them. Only external_id is written; every other value stays as it was."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        _add_column(conn, "price_observations", "external_id", "TEXT")
        _add_column(conn, "history_fetches", "external_id", "TEXT")
        _add_column(conn, "current_price_checks", "external_id", "TEXT")
        _add_column(conn, "current_price_checks", "itad_steam_deals", "INTEGER")
        conn.execute("DROP TRIGGER IF EXISTS trg_price_observations_no_update")
        tagged = _backfill_external_ids(conn)
        conn.execute("DROP INDEX IF EXISTS ux_observation")
        conn.execute(
            "CREATE TRIGGER trg_price_observations_no_update BEFORE UPDATE ON price_observations "
            "BEGIN SELECT RAISE(ABORT, 'append-only: price_observations'); END"
        )
        conn.execute("UPDATE schema_meta SET value = '3' WHERE key = 'schema_version'")
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return tagged


def backup_before_migration(conn: sqlite3.Connection, version: int) -> Path | None:
    """Copy the database to <name>.bak-v<version> once, before migrating it (research R3)."""
    row = conn.execute("PRAGMA database_list").fetchone()
    if not row or not row[2]:
        return None
    source = Path(row[2])
    target = source.with_name(f"{source.name}.bak-v{version}")
    if not target.exists():
        copy = sqlite3.connect(target)
        try:
            conn.backup(copy)
        finally:
            copy.close()
    return target


# Created after the migrations: on an older database these columns exist only once _migrate_v2_to_v3 has run.
# NULL amounts must still collide, so the uniqueness key uses IFNULL (SQLite treats NULLs as distinct); two ITAD
# products of one app may hold the same state at the same time (v3). v7: a valid row and a quarantined row of the
# same state are different keys, so a later fetch that sees a quarantined event again can still add it.
OBSERVATION_INDEX = (
    "CREATE UNIQUE INDEX ux_observation ON price_observations (app_id, source, region, IFNULL(external_id, ''), "
    "observed_at, IFNULL(price_cents, -1), IFNULL(regular_cents, -1), IFNULL(cut_pct, -1), anomaly IS NULL)")
POST_MIGRATION_DDL = (
    OBSERVATION_INDEX.replace("CREATE UNIQUE INDEX", "CREATE UNIQUE INDEX IF NOT EXISTS", 1) + ";\n"
    "CREATE INDEX IF NOT EXISTS ix_history_fetches_product ON history_fetches (app_id, region, external_id, fetched_at);\n")


def migrate(conn: sqlite3.Connection) -> dict | None:
    """Create or upgrade the schema. Returns what an upgrade did (for the user), or None when nothing was
    upgraded."""
    started = time.monotonic()
    version = _current_version(conn)
    backup = None
    if version is not None and version < SCHEMA_VERSION:
        backup = backup_before_migration(conn, version)
    conn.executescript(DDL + _append_only_triggers())
    if version == 1:
        _migrate_v1_to_v2(conn)
    tagged = _migrate_v2_to_v3(conn) if version in (1, 2) else None
    _migrate_to_v4(conn)
    _migrate_to_v5(conn)
    _migrate_to_v6(conn)
    conn.executescript(POST_MIGRATION_DDL)
    _migrate_to_v7(conn)
    conn.execute(
        "INSERT INTO schema_meta (key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )
    if version is None or version >= SCHEMA_VERSION:
        return None
    return {"from": version, "to": SCHEMA_VERSION, "backup": backup, "tagged": tagged,
            "seconds": round(time.monotonic() - started, 1)}
