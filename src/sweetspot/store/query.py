"""Read-only, point-in-time query interface for the analysis core (contracts/store-api.md).

Every method taking `as_of` never returns anything observed after `as_of` (FR-012).
"""

import json
import sqlite3
from dataclasses import dataclass
from dataclasses import replace
from datetime import date, datetime, timedelta
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from sweetspot.calendar import SaleEvent, current_estimates, load_calendar, sales_at
from sweetspot.store import schema
from sweetspot.timeutil import from_db, now_utc, to_db

__all__ = ["Fact", "Observation", "OldDatabaseError", "PriceStore", "ProductFacts", "SaleEvent"]

ITAD_SOURCES = ("itad-history", "legacy-itad")   # price history series; steam-current is sampled, not a change log
# feature 009 (research R3): an edition's ITAD history. Read only when asked for with the edition's key; never a
# store snapshot, never part of the default series.
OPTION_HISTORY_SOURCE = schema.OPTION_HISTORY_SOURCE
SERIES_SOURCES = ITAD_SOURCES + (OPTION_HISTORY_SOURCE,)
LIVE_WINDOW = timedelta(days=1)   # as_of this close to now counts as "the present" for sale queries


@dataclass(frozen=True)
class Observation:
    app_id: int
    region: str
    source: str
    observed_at: datetime
    retrieved_at: datetime
    regular_cents: int | None
    price_cents: int | None
    cut_pct: int | None
    is_tracking_start: bool
    external_id: str | None = None     # ITAD product of a history row (feature 006)


# app_id -> the ITAD product whose history to read (feature 006). Rows without a product (written before
# schema v3 and not backfilled) belong to the app's own product.
Keys = Mapping[int, str | None]


@dataclass(frozen=True)
class VersionRecord:
    """One app_versions row (feature 006, data-model §1)."""
    app_id: int
    checked_at: datetime
    status: str
    package_id: int | None
    package_name: str | None
    regular_cents: int | None
    price_cents: int | None
    external_id: str | None
    verification: str | None
    verified_by: str | None
    verified_at: datetime | None
    reason_code: str | None
    reason_detail: str | None
    itad_steam_deals: int | None


@dataclass(frozen=True)
class VersionSwitch:
    """The latest version change of an app at a point in time (data-model §1). from_title is None when the old
    product was the app's own (its display name is the app's name)."""
    from_itad_id: str | None
    from_title: str | None
    to_itad_id: str | None
    to_title: str | None
    detected_at: datetime


@dataclass(frozen=True)
class HistoryKey:
    """The ITAD product an app reads at a point in time (feature 006, research R4). basis: `version` (a verified
    version row), `rejected` (a version row that failed verification: no usable history) or `own` (the app's own
    001 product) with basis_reason no-record | no-option | ambiguous | not-in-itad."""
    external_id: str | None
    basis: str
    basis_reason: str | None = None
    record: VersionRecord | None = None
    change: VersionSwitch | None = None
    stopped: bool = False                    # ITAD no longer has a Steam price for the product (FR-009)
    last_confirmed: datetime | None = None   # set when stopped: the last time the history was known to be current


@dataclass(frozen=True)
class OptionRecord:
    """One purchase_options row (feature 009, data-model §1)."""
    app_id: int
    checked_at: datetime
    kind: str
    option_id: int
    name: str | None
    original_cents: int
    final_cents: int
    position: int
    is_default: bool
    role: str
    external_id: str | None
    verification: str | None
    verified_at: datetime | None
    reason_code: str | None
    reason_detail: str | None
    itad_steam_deals: int | None
    bundle_discount_pct: int | None = None      # feature 010 (schema v5); None before v5 and for packages
    before_bundle_cents: int | None = None
    contents: list[dict] | None = None          # contents_json: [{app_id, type, parent_app_id[, final_cents]}]


@dataclass(frozen=True)
class OptionLow:
    """An ITAD product's lowest TW price in its history (feature 009, the report's list of editions)."""
    low_cents: int
    low_at: datetime
    first_at: datetime


@dataclass(frozen=True)
class OptionKey:
    """What a user's choice resolves to at a point in time (feature 009, research R4, data-model §4).
    `key` is the HistoryKey to read: basis `user` (the edition's product) or, when the choice is the Steam default,
    its product equals the default version's, or it falls back, the default version's own key."""
    key: HistoryKey
    source: str                              # user | user-fallback
    requested: tuple[str, int]
    record: OptionRecord | None = None
    fallback_code: str | None = None
    fallback_detail: str | None = None
    same_as_default: bool = False


class OldDatabaseError(RuntimeError):
    """A read-only command opened a database older than the current schema; only writers migrate."""


@dataclass(frozen=True)
class Fact[T]:
    value: T | None
    source: str | None = None
    retrieved_at: datetime | None = None


UNKNOWN: Fact[Any] = Fact(None)


@dataclass(frozen=True)
class ProductFacts:
    app_id: int
    name: Fact[str]
    product_type: Fact[str]
    parent_app_id: Fact[int]
    publishers: Fact[list[str]]
    developers: Fact[list[str]]
    release_date: Fact[date]
    released_as_of: bool | None
    genres: Fact[list[dict]]
    is_indie: Fact[bool]
    review_count_total: Fact[int]
    publisher_catalog_size: Fact[int]
    release_state: Fact[str] = UNKNOWN      # released | coming_soon | unknown (static; feature 002)


class PriceStore:
    def __init__(self, conn: sqlite3.Connection, calendar_path: Path | None = None):
        self.conn = conn
        self.calendar_path = calendar_path
        self._calendar: list[SaleEvent] | None = None

    @classmethod
    def open(cls, path: Path, calendar_path: Path | None = None) -> "PriceStore":
        """The sale calendar defaults to steam_sales.toml next to the database (data/). A database older than the
        current schema is refused: read-only commands do not take the writer lock, so they cannot migrate."""
        conn = schema.connect(path, readonly=True)
        version = schema._current_version(conn)
        if version is not None and version < schema.SCHEMA_VERSION:
            conn.close()
            raise OldDatabaseError(f"資料庫是舊版（v{version}），請先執行 sweetspot update 升級")
        return cls(conn, calendar_path or Path(path).parent / "steam_sales.toml")

    def close(self) -> None:
        self.conn.close()

    # --- product sets ------------------------------------------------------------------------

    def wishlist_apps(self, state: set[str] = frozenset({"in_wishlist"})) -> list[int]:
        placeholders = ",".join("?" * len(state))
        rows = self.conn.execute(
            f"SELECT app_id FROM wishlist_membership WHERE state IN ({placeholders}) ORDER BY app_id",
            tuple(state),
        )
        return [r[0] for r in rows]

    def reference_apps(self, pool: str | None = None) -> list[int]:
        """Products outside the wishlist: reference samples, legacy imports and expired removed apps.

        `pool` filters by how the product entered the system (products.first_seen_via).
        """
        sql = (
            "SELECT p.app_id FROM products p LEFT JOIN wishlist_membership m USING (app_id) "
            "WHERE m.state = 'reference_only' OR (m.state IS NULL AND p.first_seen_via != 'wishlist')"
        )
        params: tuple = ()
        if pool is not None:
            sql += " AND p.first_seen_via = ?"
            params = (pool,)
        return [r[0] for r in self.conn.execute(sql + " ORDER BY p.app_id", params)]

    # --- ITAD products (feature 006) ------------------------------------------------------------------

    def own_keys(self, app_ids: Sequence[int]) -> dict[int, str | None]:
        """Each app's own ITAD product: the latest non-null id of its 001 mapping, or None."""
        return own_keys(self.conn, app_ids)

    def versions(self, app_ids: Sequence[int], as_of: datetime) -> dict[int, VersionRecord]:
        """Each app's latest version row checked at or before `as_of` (no look-ahead)."""
        wanted = set(app_ids)
        out: dict[int, VersionRecord] = {}
        rows = self.conn.execute(
            "SELECT app_id, checked_at, status, package_id, package_name, regular_cents, price_cents, external_id, "
            "verification, verified_by, verified_at, reason_code, reason_detail, itad_steam_deals FROM app_versions "
            "WHERE checked_at <= ? ORDER BY app_id, checked_at, version_row_id", (to_db(as_of),))
        for r in rows:
            if r[0] in wanted:
                out[r[0]] = VersionRecord(r[0], from_db(r[1]), r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9],
                                          from_db(r[10]) if r[10] else None, r[11], r[12], r[13])
        return out

    def history_keys(self, app_ids: Sequence[int], as_of: datetime) -> dict[int, HistoryKey]:
        """Which ITAD product each app reads at `as_of` (data-model §4), with its latest version change and
        whether ITAD stopped tracking it. Only version rows decide; nothing checked after `as_of` is used."""
        records = self.versions(app_ids, as_of)
        own = self.own_keys(app_ids)
        out: dict[int, HistoryKey] = {}
        for app in app_ids:
            record = records.get(app)
            if record is None:
                out[app] = HistoryKey(own[app], "own", "no-record")
                continue
            change = self._latest_switch(app, own[app], as_of)
            if record.status == "ok" and record.verification == "verified":
                stopped = record.itad_steam_deals == 0 and record.price_cents is not None
                out[app] = HistoryKey(record.external_id, "version", None, record, change, stopped,
                                      self._last_confirmed(app, record.external_id, own[app], as_of) if stopped else None)
            elif record.status == "ok" and record.verification == "rejected":
                out[app] = HistoryKey(record.external_id, "rejected", None, record, change)
            else:
                out[app] = HistoryKey(own[app], "own", record.status, record, change)
        return out

    def _latest_switch(self, app_id: int, own_id: str | None, as_of: datetime) -> VersionSwitch | None:
        """Adjacent `ok` rows with different ITAD products; the first row is compared with the own product."""
        previous, title, switch = own_id, None, None
        for ext, name, checked in self.conn.execute(
                "SELECT external_id, package_name, checked_at FROM app_versions WHERE app_id = ? AND status = 'ok' "
                "AND checked_at <= ? ORDER BY checked_at, version_row_id", (app_id, to_db(as_of))):
            if ext != previous:
                switch = VersionSwitch(previous, title, ext, name, from_db(checked))
            previous, title = ext, name
        return switch

    def _last_confirmed(self, app_id: int, external_id: str, own_id: str | None, as_of: datetime) -> datetime | None:
        """Latest of: the product's newest TW history row, and the newest version row that still saw a Steam price
        for it (research R4)."""
        row = self.conn.execute(
            f"SELECT MAX(observed_at) FROM price_observations WHERE app_id = ? AND region = 'TW' AND "
            f"source IN {ITAD_SOURCES} AND IFNULL(external_id, ?) = ? AND observed_at <= ?",
            (app_id, own_id, external_id, to_db(as_of))).fetchone()
        seen = self.conn.execute(
            "SELECT MAX(checked_at) FROM app_versions WHERE app_id = ? AND external_id = ? AND itad_steam_deals >= 1 "
            "AND checked_at <= ?", (app_id, external_id, to_db(as_of))).fetchone()
        times = [from_db(t) for t in (row[0], seen[0]) if t]
        return max(times) if times else None

    @staticmethod
    def capped_known_until(known: Mapping[int, datetime], keys: Mapping[int, HistoryKey]) -> dict[int, datetime]:
        """Known-until per app, capped at the last confirmation where ITAD stopped tracking (spec FR-009)."""
        out = dict(known)
        for app, key in keys.items():
            if key.stopped and key.last_confirmed is not None and app in out:
                out[app] = min(out[app], key.last_confirmed)
        return out

    def has_versions(self) -> bool:
        """Whether the daily version step has recorded anything yet (feature 006 is active in this database)."""
        return self.conn.execute("SELECT 1 FROM app_versions LIMIT 1").fetchone() is not None

    @staticmethod
    def key_ids(keys: Mapping[int, HistoryKey]) -> dict[int, str | None]:
        return {app: key.external_id for app, key in keys.items()}

    def _key_filter(self, keys: Keys | None):
        """A predicate (app_id, row external_id) -> bool; rows without a product count as the app's own."""
        if keys is None:
            return lambda app, ext: True
        own = self.own_keys(list(keys))
        return lambda app, ext: app not in keys or (ext if ext is not None else own.get(app)) == keys[app]

    def _row_filter(self, keys: Keys | None):
        """A predicate (app_id, source, external_id) -> bool for reads mixing store snapshots and ITAD rows.
        Store snapshots are always kept; ITAD history rows follow `keys`; an edition's rows (feature 009) are kept
        only when `keys` names that edition's product for the app."""
        keep = self._key_filter(keys)

        def row(app, source, ext):
            if source == OPTION_HISTORY_SOURCE:
                return keys is not None and app in keys and ext is not None and ext == keys[app]
            return source not in ITAD_SOURCES or keep(app, ext)
        return row

    # --- purchase options (feature 009, data-model §4) -----------------------------------------

    def app_names(self, app_ids: Sequence[int]) -> dict[int, str | None]:
        """Display names of apps inside bundles (feature 010): the latest product fact, else the store app list
        (games only), else None. Apps outside the wishlist are never written to product_facts (009 research R1)."""
        out: dict[int, str | None] = {a: None for a in app_ids}
        for start in range(0, len(app_ids), 500):
            batch = list(app_ids[start:start + 500])
            marks = ",".join("?" * len(batch))
            for app, name in self.conn.execute(f"SELECT app_id, name FROM steam_app_list WHERE app_id IN ({marks})",
                                               batch):
                out[app] = name or None
            for app, value in self.conn.execute(
                    f"SELECT app_id, value_json FROM product_facts WHERE field = 'name' AND app_id IN ({marks}) "
                    "ORDER BY retrieved_at, fact_id", batch):
                name = json.loads(value) if value else None
                if name:
                    out[app] = name
        return out

    def purchase_options(self, app_ids: Sequence[int], as_of: datetime) -> dict[int, list[OptionRecord]]:
        """Each app's rows of its latest purchase-option step with checked_at <= as_of (apps without one are
        absent)."""
        wanted = sorted(set(app_ids))
        out: dict[int, list[OptionRecord]] = {}
        if not wanted:
            return out
        marks = ",".join("?" * len(wanted))
        rows = self.conn.execute(
            f"SELECT {OPTION_COLUMNS} "
            "FROM purchase_options p JOIN (SELECT app_id, MAX(checked_at) AS latest FROM purchase_options "
            f"WHERE checked_at <= ? AND app_id IN ({marks}) GROUP BY app_id) m "
            "ON p.app_id = m.app_id AND p.checked_at = m.latest ORDER BY p.app_id, position, option_row_id",
            (to_db(as_of), *wanted))
        for r in rows:
            out.setdefault(r[0], []).append(_option_record(r))
        return out

    def option_steps(self, app_id: int, kind: str, option_id: int, start: datetime,
                     end: datetime) -> list[OptionRecord]:
        """Feature 013: one purchase option's rows with start <= checked_at < end, oldest first (the daily price
        the store showed for exactly that package or bundle). No rows: an empty list."""
        rows = self.conn.execute(
            f"SELECT {OPTION_COLUMNS} FROM purchase_options p "
            "WHERE app_id = ? AND kind = ? AND option_id = ? AND checked_at >= ? AND checked_at < ? "
            "ORDER BY checked_at, option_row_id", (app_id, kind, option_id, to_db(start), to_db(end)))
        return [_option_record(r) for r in rows]

    def option_keys(self, choices: Mapping[int, tuple[str, int]], as_of: datetime,
                    default_keys: Mapping[int, HistoryKey]) -> dict[int, OptionKey]:
        """Resolve each choice with the purchase options recorded at or before as_of (research R4). An edition
        whose ITAD product no longer has a Steam price is still followed, its known-until capped (006 FR-009)."""
        from sweetspot.choices import resolve_choice

        records = self.purchase_options(list(choices), as_of)
        out: dict[int, OptionKey] = {}
        for app, choice in choices.items():
            default = default_keys.get(app) or HistoryKey(self.own_keys([app])[app], "own", "no-record")
            result = resolve_choice(records.get(app), choice)
            if not result.active:
                out[app] = OptionKey(default, "user-fallback", choice, result.record, result.code, result.detail)
                continue
            record = result.record
            if record.role == "default" or record.external_id == default.external_id:
                out[app] = OptionKey(default, "user", choice, record, same_as_default=True)
                continue
            stopped = record.itad_steam_deals == 0 and record.final_cents is not None
            last = self._option_last_confirmed(app, record, as_of) if stopped else None
            out[app] = OptionKey(HistoryKey(record.external_id, "user", None, None, None, stopped, last), "user",
                                 choice, record)
        return out

    def _option_last_confirmed(self, app_id: int, record: "OptionRecord", as_of: datetime) -> datetime | None:
        """Latest of: the edition's newest TW history row, and the newest purchase-option step that still saw a
        Steam price for it (the 006 rule, research R4)."""
        row = self.conn.execute(
            "SELECT MAX(observed_at) FROM price_observations WHERE app_id = ? AND region = 'TW' AND source = ? "
            "AND external_id = ? AND observed_at <= ?",
            (app_id, OPTION_HISTORY_SOURCE, record.external_id, to_db(as_of))).fetchone()
        seen = self.conn.execute(
            "SELECT MAX(checked_at) FROM purchase_options WHERE app_id = ? AND kind = ? AND option_id = ? "
            "AND external_id = ? AND itad_steam_deals >= 1 AND checked_at <= ?",
            (app_id, record.kind, record.option_id, record.external_id, to_db(as_of))).fetchone()
        times = [from_db(t) for t in (row[0], seen[0]) if t]
        return max(times) if times else None

    def option_lows(self, requests: Sequence[tuple[int, str, str]], as_of: datetime) -> dict[tuple[int, str], OptionLow]:
        """(app, ITAD product, source) -> the lowest TW price, when it was first seen, and the first row's time, from
        rows observed at or before as_of. Editions read `itad-option-history`; the default version reads its own
        rows (`itad-history`, `legacy-itad`, rows without a product counting as the app's own). No rows: absent."""
        out: dict[tuple[int, str], OptionLow] = {}
        own = self.own_keys(sorted({app for app, _, _ in requests}))
        for app, product, source in requests:
            sources = (OPTION_HISTORY_SOURCE,) if source == OPTION_HISTORY_SOURCE else ITAD_SOURCES
            marks = ",".join("?" * len(sources))
            rows = self.conn.execute(
                "SELECT observed_at, price_cents, external_id FROM price_observations WHERE app_id = ? AND region = 'TW' "
                f"AND source IN ({marks}) AND anomaly IS NULL AND observed_at <= ? ORDER BY observed_at, obs_id",
                (app, *sources, to_db(as_of))).fetchall()
            rows = [(from_db(t), p) for t, p, ext in rows if (ext if ext is not None else own.get(app)) == product]
            priced = [(p, t) for t, p in rows if p is not None]
            if not priced:
                continue
            low = min(priced, key=lambda x: (x[0], x[1]))
            out[(app, product)] = OptionLow(low[0], low[1], rows[0][0])
        return out

    # --- point-in-time queries -----------------------------------------------------------------

    def observations(self, app_id: int, as_of: datetime, region: str = "TW",
                     include_tracking_start: bool = True, keys: Keys | None = None) -> list[Observation]:
        """Price states observed up to `as_of`. A tracking-start row is the first snapshot of a series: the
        state already held before its observed_at, so callers must not read it as a price change. With `keys`,
        ITAD rows of other products are left out (store snapshots are always kept)."""
        sql = (
            "SELECT app_id, region, source, observed_at, retrieved_at, regular_cents, price_cents, cut_pct, "
            "is_tracking_start, external_id FROM price_observations "
            "WHERE app_id = ? AND region = ? AND observed_at <= ? AND anomaly IS NULL"
        )
        if not include_tracking_start:
            sql += " AND is_tracking_start = 0"
        sql += " ORDER BY observed_at, source"
        keep = self._row_filter(keys)
        return [_observation(r) for r in self.conn.execute(sql, (app_id, region, to_db(as_of))) if keep(r[0], r[2], r[9])]

    def series_rows(self, app_ids: Sequence[int], region: str, as_of: datetime,
                    keys: Keys | None = None, sources: Sequence[str] = ITAD_SOURCES) -> dict[int, list[Observation]]:
        """ITAD history (itad-history and legacy-itad, never steam-current) for many apps at once, observed_at <=
        as_of and not quarantined; same semantics as observations() filtered to those sources (feature 002 R7).
        With `keys` only the given ITAD product of each app is returned (feature 006). Feature 009: an edition's
        history is read with sources=(OPTION_HISTORY_SOURCE,) and the edition's key."""
        wanted = set(app_ids)
        keep = self._key_filter(keys)
        out: dict[int, list[Observation]] = {}
        marks = ",".join("?" * len(sources))
        rows = self.conn.execute(
            "SELECT app_id, region, source, observed_at, retrieved_at, regular_cents, price_cents, cut_pct, "
            "is_tracking_start, external_id FROM price_observations WHERE region = ? AND observed_at <= ? "
            f"AND anomaly IS NULL AND source IN ({marks}) ORDER BY app_id, observed_at, source",
            (region, to_db(as_of), *sources))
        for r in rows:
            if r[0] in wanted and keep(r[0], r[9]):
                out.setdefault(r[0], []).append(_observation(r))
        return out

    def latest_observations(self, app_ids: Sequence[int], region: str, as_of: datetime,
                            keys: Keys | None = None) -> dict[int, Observation]:
        """The latest non-quarantined observation of any source per app, observed_at <= as_of (feature 003 R3:
        the current price). On a tie the steam-current snapshot wins, being a direct store reading. With `keys`,
        ITAD rows of other products are ignored."""
        wanted = set(app_ids)
        keep = self._row_filter(keys)
        out: dict[int, Observation] = {}
        rows = self.conn.execute(
            "SELECT app_id, region, source, observed_at, retrieved_at, regular_cents, price_cents, cut_pct, "
            "is_tracking_start, external_id FROM price_observations WHERE region = ? AND observed_at <= ? "
            "AND anomaly IS NULL ORDER BY app_id, observed_at, CASE source WHEN 'steam-current' THEN 1 ELSE 0 END, "
            "obs_id", (region, to_db(as_of)))
        for r in rows:
            if r[0] in wanted and keep(r[0], r[2], r[9]):
                out[r[0]] = _observation(r)
        return out

    def latest_snapshot_times(self, region: str, as_of: datetime) -> dict[int, datetime]:
        """Latest steam-current snapshot time per app, observed_at <= as_of, not quarantined (feature 003 R3)."""
        rows = self.conn.execute(
            "SELECT app_id, MAX(observed_at) FROM price_observations WHERE region = ? AND source = 'steam-current' "
            "AND observed_at <= ? AND anomaly IS NULL GROUP BY app_id", (region, to_db(as_of)))
        return {a: from_db(t) for a, t in rows if t}

    def history_known_until(self, app_id: int, region: str = "TW", keys: Keys | None = None) -> datetime | None:
        """Last time the ITAD history of this app/region was confirmed: the latest history fetch, or the latest
        legacy import retrieval. For scoring only; models never see it (feature 002 R3). With `keys`, only fetches
        of the given ITAD product count (feature 006)."""
        return self.history_known_until_all(region, keys={app_id: keys[app_id]} if keys and app_id in keys
                                            else None, apps=(app_id,)).get(app_id)

    def history_known_until_all(self, region: str = "TW", keys: Keys | None = None,
                                apps: Sequence[int] | None = None) -> dict[int, datetime]:
        """history_known_until() for every app with a value, in one query (optionally only `apps`)."""
        where, params = "", [region, region]
        if apps is not None:
            marks = ",".join("?" * len(apps))
            where = f" AND app_id IN ({marks})"
            params = [region, *apps, region, *apps]
        rows = self.conn.execute(
            "SELECT app_id, ext, MAX(t) FROM (SELECT app_id, external_id AS ext, MAX(fetched_at) AS t FROM history_fetches "
            f"WHERE region = ?{where} GROUP BY app_id, external_id UNION ALL SELECT app_id, external_id, MAX(retrieved_at) "
            f"FROM price_observations WHERE region = ?{where} AND source = 'legacy-itad' GROUP BY app_id, external_id) "
            "GROUP BY app_id, ext", params)
        keep = self._key_filter(keys)
        out: dict[int, datetime] = {}
        for app, ext, t in rows:
            if t and keep(app, ext):
                moment = from_db(t)
                if app not in out or moment > out[app]:
                    out[app] = moment
        return out

    def itad_mapping_state(self, app_id: int) -> str | None:
        """Latest ITAD mapping verification: verified | verified-legacy | rejected | pending, or None."""
        row = self.conn.execute(
            "SELECT verification FROM source_mappings WHERE app_id = ? AND source = 'itad' "
            "ORDER BY checked_at DESC, mapping_id DESC LIMIT 1", (app_id,)).fetchone()
        return row[0] if row else None

    def sample_pools(self) -> dict[int, str]:
        """Why each product is in the data: wishlist > related > broad > legacy (feature 002 R4 grouping)."""
        pools: dict[int, str] = {}
        for (app_id,) in self.conn.execute("SELECT app_id FROM wishlist_membership"):
            pools[app_id] = "wishlist"
        for app_id, pool in self.conn.execute(
                "SELECT app_id, pool FROM reference_candidates WHERE status IN ('accepted', 'fetched') "
                "ORDER BY CASE WHEN pool LIKE 'related-%' THEN 0 ELSE 1 END"):
            pools.setdefault(app_id, "related" if pool.startswith("related-") else "broad")
        for app_id, via in self.conn.execute("SELECT app_id, first_seen_via FROM products"):
            pools.setdefault(app_id, "wishlist" if via == "wishlist" else "legacy")
        return pools

    def _fact(self, app_id: int, field: str, as_of: datetime) -> Fact[Any]:
        sql = "SELECT value_json, source, retrieved_at FROM product_facts WHERE app_id = ? AND field = ?"
        params: list[Any] = [app_id, field]
        if schema.FACT_VOLATILITY[field] == "volatile":
            sql += " AND retrieved_at <= ?"
            params.append(to_db(as_of))
        row = self.conn.execute(sql + " ORDER BY retrieved_at DESC, fact_id DESC LIMIT 1", params).fetchone()
        if row is None:
            return UNKNOWN
        return Fact(json.loads(row[0]) if row[0] is not None else None, row[1], from_db(row[2]))

    def release_dates(self, app_ids: Iterable[int]) -> dict[int, date | None]:
        """Latest known release date of each app in one query (a static fact; feature 008 research R3). Missing,
        null or unparseable values are None (constitution I)."""
        wanted = sorted(set(app_ids))
        out: dict[int, date | None] = dict.fromkeys(wanted)
        if not wanted:
            return out
        rows = self.conn.execute(
            "SELECT app_id, value_json FROM product_facts WHERE field = 'release_date' "
            "ORDER BY app_id, retrieved_at, fact_id").fetchall()
        for app_id, value_json in rows:           # ascending: the last row of an app is its latest value
            if app_id not in out:
                continue
            value = json.loads(value_json) if value_json is not None else None
            try:
                out[app_id] = date.fromisoformat(value) if isinstance(value, str) else None
            except ValueError:
                out[app_id] = None
        return out

    def facts(self, app_id: int, as_of: datetime) -> ProductFacts:
        """Static fields: latest known value. Volatile fields: only values retrieved at or before as_of."""
        to_db(as_of)  # rejects naive datetimes
        get = lambda field: self._fact(app_id, field, as_of)  # noqa: E731
        release = get("release_date")
        release_date = date.fromisoformat(release.value) if release.value else None
        return ProductFacts(
            app_id=app_id,
            name=get("name"),
            product_type=get("product_type"),
            parent_app_id=get("parent_app_id"),
            publishers=get("publishers"),
            developers=get("developers"),
            release_date=Fact(release_date, release.source, release.retrieved_at),
            released_as_of=None if release_date is None else release_date <= as_of.date(),
            genres=get("genres"),
            is_indie=get("is_indie"),
            review_count_total=get("review_count_total"),
            publisher_catalog_size=get("publisher_catalog_size"),
            release_state=get("release_state"),
        )

    # --- sales -------------------------------------------------------------------------------------

    def _events(self) -> list[SaleEvent]:
        """The calendar file plus official sales adopted from the seasonal sales page that the file lacks (feature
        012; the file always wins)."""
        if self._calendar is None:
            from sweetspot.calendar_sync import load_effective

            self._calendar = load_effective(self.conn, self.calendar_path, now=now_utc())
        return self._calendar

    def sales(self, as_of: datetime, include_estimates: bool = True) -> list[SaleEvent]:
        """Sales known at `as_of`.

        Past sales (start <= as_of) are always returned, with status relative to as_of. Future sales are
        returned only when as_of is the present: we do not record when Valve announced each sale, so a
        backtest must not see later announcements (no look-ahead). Backtests estimate future sales
        themselves with calendar.estimate_sale() over the past sales returned here. Official sales adopted from
        the seasonal sales page (feature 012) pass the same filter; when they were first seen is not used.
        """
        to_db(as_of)  # rejects naive datetimes
        events = [replace(e, status="ended" if e.end <= as_of else "announced")
                  for e in self._events() if e.start <= as_of]
        if as_of >= now_utc() - LIVE_WINDOW:
            events += [e for e in self._events() if e.start > as_of]
            if include_estimates:
                known = {(e.year, e.season) for e in events if e.kind == "seasonal"}
                events += [e for e in current_estimates(self.conn) if e.start > as_of
                           and (e.year, e.season) not in known]
        return sorted(events, key=lambda e: e.start)

    def calendar_events(self) -> list[SaleEvent]:
        """Every sale in the calendar file, with status relative to now. For backtest *scoring* only (real
        sale dates); forecasts must use sales(as_of), which hides later announcements."""
        return list(self._events())

    def sales_for(self, obs: Observation) -> list[SaleEvent]:
        """Sales in effect when the observation was made; empty means outside any known sale."""
        return sales_at(self._events(), obs.observed_at)

    # --- coverage and consistency ------------------------------------------------------------------

    def coverage(self, app_id: int, aux_region: str = "US") -> "Coverage":
        from sweetspot.coverage import coverage

        return coverage(self.conn, app_id, now_utc(), aux_region)

    def region_consistency(self, scope: int | str) -> dict | None:
        """Latest stored TW-vs-aux consistency for an app id or 'ALL'."""
        row = self.conn.execute(
            "SELECT aux_region, overlap_start, overlap_end, days_compared, days_same_cut, sales_tw, sales_matched, "
            "computed_at FROM region_consistency WHERE scope = ? ORDER BY computed_at DESC, row_id DESC LIMIT 1",
            (str(scope),)).fetchone()
        if row is None:
            return None
        keys = ("aux_region", "overlap_start", "overlap_end", "days_compared", "days_same_cut", "sales_tw",
                "sales_matched", "computed_at")
        return dict(zip(keys, row))


def _observation(r) -> Observation:
    """A price_observations row selected as (app_id, region, source, observed_at, retrieved_at, regular_cents,
    price_cents, cut_pct, is_tracking_start, external_id)."""
    return Observation(app_id=r[0], region=r[1], source=r[2], observed_at=from_db(r[3]), retrieved_at=from_db(r[4]),
                       regular_cents=r[5], price_cents=r[6], cut_pct=r[7], is_tracking_start=bool(r[8]),
                       external_id=r[9])


# purchase_options columns as _option_record reads them (the table aliased as p)
OPTION_COLUMNS = ("p.app_id, p.checked_at, kind, option_id, name, original_cents, final_cents, position, is_default, "
                  "role, external_id, verification, verified_at, reason_code, reason_detail, itad_steam_deals, "
                  "bundle_discount_pct, before_bundle_cents, contents_json")


def _option_record(r) -> OptionRecord:
    return OptionRecord(
        app_id=r[0], checked_at=from_db(r[1]), kind=r[2], option_id=r[3], name=r[4], original_cents=r[5],
        final_cents=r[6], position=r[7], is_default=bool(r[8]), role=r[9], external_id=r[10],
        verification=r[11], verified_at=from_db(r[12]) if r[12] else None, reason_code=r[13],
        reason_detail=r[14], itad_steam_deals=r[15], bundle_discount_pct=r[16], before_bundle_cents=r[17],
        contents=json.loads(r[18]) if r[18] else None)


def own_keys(conn: sqlite3.Connection, app_ids: Sequence[int]) -> dict[int, str | None]:
    """Each app's own ITAD product: the latest non-null id of its 001 mapping, or None (feature 006)."""
    wanted = set(app_ids)
    out: dict[int, str | None] = {a: None for a in app_ids}
    rows = conn.execute(
        "SELECT app_id, external_id FROM source_mappings WHERE source = 'itad' AND external_id IS NOT NULL "
        "ORDER BY app_id, checked_at, mapping_id")
    for app, ext in rows:
        if app in wanted:
            out[app] = ext
    return out


def single_own_id(conn: sqlite3.Connection, app_id: int) -> str | None:
    """The app's ITAD id when it was only ever mapped to one; the same rule as the v3 backfill (research R3)."""
    rows = conn.execute("SELECT DISTINCT external_id FROM source_mappings WHERE app_id = ? AND source = 'itad' "
                        "AND external_id IS NOT NULL", (app_id,)).fetchall()
    return rows[0][0] if len(rows) == 1 else None


def product_clause(conn: sqlite3.Connection, app_id: int, key: str | None) -> tuple[str, tuple]:
    """SQL fragment and parameters that keep only ITAD rows of product `key` (rows without a product count as the
    app's own). No key: no filter."""
    if key is None:
        return "", ()
    return " AND IFNULL(external_id, ?) = ?", (own_keys(conn, [app_id])[app_id], key)
