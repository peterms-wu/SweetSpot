-- Frozen schema v2 (feature 005) for v2 -> v3 migration tests. Generated from StoreWriter.open before feature 006.
CREATE TABLE catalog_progress (
    kind TEXT NOT NULL CHECK (kind IN ('publisher', 'developer')),
    name TEXT NOT NULL,
    next_start INTEGER NOT NULL DEFAULT 0,
    total_count INTEGER,
    complete INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (kind, name)
);
CREATE TABLE current_price_checks (
    run_id TEXT NOT NULL,
    app_id INTEGER NOT NULL,
    steam_price_cents INTEGER,
    steam_regular_cents INTEGER,
    itad_price_cents INTEGER,
    itad_regular_cents INTEGER,
    match INTEGER,
    checked_at TEXT NOT NULL
);
CREATE TABLE history_fetches (
    app_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    region TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    entries INTEGER NOT NULL,
    run_id TEXT
);
CREATE TABLE price_observations (
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
    run_id TEXT
);
CREATE TABLE product_facts (
    fact_id INTEGER PRIMARY KEY AUTOINCREMENT,
    app_id INTEGER NOT NULL,
    field TEXT NOT NULL,
    value_json TEXT,
    volatility TEXT NOT NULL CHECK (volatility IN ('static', 'volatile')),
    source TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    run_id TEXT
);
CREATE TABLE products (
    app_id INTEGER PRIMARY KEY,
    first_seen_at TEXT NOT NULL,
    first_seen_via TEXT NOT NULL
);
CREATE TABLE reference_candidates (
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
CREATE TABLE region_consistency (
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
CREATE TABLE run_item_results (
    run_id TEXT NOT NULL,
    app_id INTEGER,
    stage TEXT NOT NULL CHECK (stage IN ('wishlist', 'current-price', 'metadata', 'mapping', 'history-tw', 'history-aux', 'reference', 'import')),
    status TEXT NOT NULL CHECK (status IN ('ok', 'reused', 'skipped', 'failed', 'unsupported', 'delisted', 'not-found')),
    reason_code TEXT,
    message TEXT,
    recorded_at TEXT NOT NULL
);
CREATE TABLE runs (
    run_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('daily', 'reference', 'legacy-import', 'calendar-check')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'partial', 'failed', 'interrupted')),
    summary_json TEXT,
    pid INTEGER
);
CREATE TABLE sale_estimates (
    estimate_id INTEGER PRIMARY KEY AUTOINCREMENT,
    season TEXT NOT NULL,
    year INTEGER NOT NULL,
    est_start TEXT NOT NULL,
    est_end TEXT NOT NULL,
    basis_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    superseded_at TEXT
);
CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE source_mappings (
    mapping_id INTEGER PRIMARY KEY AUTOINCREMENT,
    app_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    external_id TEXT,
    verification TEXT NOT NULL CHECK (verification IN ('verified', 'verified-legacy', 'rejected', 'pending')),
    reason_code TEXT,
    warnings_json TEXT,
    aliases_json TEXT,
    checked_at TEXT NOT NULL,
    run_id TEXT
);
CREATE TABLE steam_app_list (
    app_id INTEGER PRIMARY KEY,
    name TEXT,
    last_modified INTEGER,
    fetched_at TEXT NOT NULL
);
CREATE TABLE wishlist_items (
    sync_id TEXT NOT NULL,
    app_id INTEGER NOT NULL,
    priority INTEGER,
    date_added TEXT,
    PRIMARY KEY (sync_id, app_id)
);
CREATE TABLE wishlist_membership (
    app_id INTEGER PRIMARY KEY,
    state TEXT NOT NULL CHECK (state IN ('in_wishlist', 'removed_tracking', 'reference_only')),
    first_added_at TEXT NOT NULL,
    removed_at TEXT,
    track_until TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE wishlist_syncs (
    sync_id TEXT PRIMARY KEY,
    source_url TEXT NOT NULL,
    attempted_at TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ok', 'empty', 'rejected')),
    reject_reason TEXT,
    item_count INTEGER,
    run_id TEXT
);
CREATE INDEX ix_facts_lookup ON product_facts (app_id, field, retrieved_at);
CREATE INDEX ix_history_fetches ON history_fetches (app_id, region, fetched_at);
CREATE INDEX ix_item_results_run ON run_item_results (run_id, app_id);
CREATE INDEX ix_mappings_lookup ON source_mappings (app_id, source, checked_at);
CREATE INDEX ix_observation_asof ON price_observations (app_id, region, observed_at);
CREATE UNIQUE INDEX ux_observation ON price_observations (
    app_id, source, region, observed_at, IFNULL(price_cents, -1), IFNULL(regular_cents, -1), IFNULL(cut_pct, -1));
CREATE TRIGGER trg_price_observations_no_delete BEFORE DELETE ON price_observations BEGIN SELECT RAISE(ABORT, 'append-only: price_observations'); END;
CREATE TRIGGER trg_price_observations_no_update BEFORE UPDATE ON price_observations BEGIN SELECT RAISE(ABORT, 'append-only: price_observations'); END;
CREATE TRIGGER trg_product_facts_no_delete BEFORE DELETE ON product_facts BEGIN SELECT RAISE(ABORT, 'append-only: product_facts'); END;
CREATE TRIGGER trg_product_facts_no_update BEFORE UPDATE ON product_facts BEGIN SELECT RAISE(ABORT, 'append-only: product_facts'); END;
CREATE TRIGGER trg_source_mappings_no_delete BEFORE DELETE ON source_mappings BEGIN SELECT RAISE(ABORT, 'append-only: source_mappings'); END;
CREATE TRIGGER trg_source_mappings_no_update BEFORE UPDATE ON source_mappings BEGIN SELECT RAISE(ABORT, 'append-only: source_mappings'); END;
INSERT INTO schema_meta (key, value) VALUES ('schema_version', '2');
