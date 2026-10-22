"""Append-only writes to the local price database (FR-011, FR-013, FR-014, FR-015)."""

import json
import os
import sqlite3
import uuid
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sweetspot.store import schema
from sweetspot.timeutil import now_utc, to_db

PRIMARY_REGION = "TW"


@dataclass(frozen=True)
class NewObservation:
    app_id: int
    source: str
    region: str
    currency: str | None
    regular_cents: int | None
    price_cents: int | None
    cut_pct: int | None
    observed_at: datetime
    raw_observed_at: str | None
    retrieved_at: datetime
    is_tracking_start: bool = False
    external_id: str | None = None     # ITAD product of a history row (feature 006); None for store snapshots


@dataclass(frozen=True)
class NewPurchaseOption:
    """One purchase_options row (feature 009, data-model §1). `contents` is [{app_id, type, parent_app_id}]."""
    app_id: int
    kind: str                       # sub | bundle
    option_id: int
    name: str | None
    original_cents: int
    final_cents: int
    position: int
    is_default: bool
    role: str                       # default | edition | other-games | without-app | unknown
    contents: list[dict] | None = None
    contents_checked_at: datetime | None = None
    external_id: str | None = None
    verification: str | None = None
    verified_by: str | None = None
    verified_at: datetime | None = None
    reason_code: str | None = None
    reason_detail: str | None = None
    warnings: list[str] | None = None
    aliases: list[str] | None = None
    itad_steam_deals: int | None = None
    bundle_discount_pct: int | None = None      # feature 010 (schema v5)
    before_bundle_cents: int | None = None


def detect_anomaly(obs: NewObservation) -> str | None:
    """Return the anomaly code for a primary-region observation, or None when it looks valid."""
    if obs.currency != "TWD":
        return "currency-mismatch"
    if (obs.price_cents is not None and obs.price_cents < 0) or (
        obs.regular_cents is not None and obs.regular_cents < 0
    ):
        return "negative-price"
    if obs.cut_pct is not None and not 0 <= obs.cut_pct <= 100:
        return "invalid-cut"
    if obs.price_cents is not None and obs.regular_cents is not None and obs.price_cents > obs.regular_cents:
        return "price-above-regular"
    if obs.observed_at > obs.retrieved_at:
        return "observed-after-retrieved"
    return None


def _detect_aux_anomaly(obs: NewObservation) -> str | None:
    if obs.currency is not None or obs.price_cents is not None or obs.regular_cents is not None:
        raise ValueError("aux-region observations must not carry currency or amounts (constitution IX)")
    if obs.cut_pct is not None and not 0 <= obs.cut_pct <= 100:
        return "invalid-cut"
    if obs.observed_at > obs.retrieved_at:
        return "observed-after-retrieved"
    return None


def _check(value: str, allowed: tuple[str, ...], name: str) -> None:
    if value not in allowed:
        raise ValueError(f"invalid {name}: {value!r}")


class StoreWriter:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._depth = 0
        self.migration: dict | None = None      # what opening the database upgraded (feature 006)

    @classmethod
    def open(cls, path: Path) -> "StoreWriter":
        conn = schema.connect(path)
        writer = cls(conn)
        writer.migration = schema.migrate(conn)
        return writer

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """BEGIN IMMEDIATE ... COMMIT; ROLLBACK on error. Nested calls join the outer transaction."""
        if self._depth:
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
            return
        self.conn.execute("BEGIN IMMEDIATE")
        self._depth = 1
        try:
            yield
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")
        finally:
            self._depth = 0

    # --- runs -------------------------------------------------------------------------------

    def start_run(self, kind: str) -> str:
        _check(kind, schema.RUN_KINDS, "run kind")
        run_id = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO runs (run_id, kind, started_at, status, pid) VALUES (?, ?, ?, 'running', ?)",
            (run_id, kind, to_db(now_utc()), os.getpid()),
        )
        return run_id

    def finish_run(self, run_id: str, status: str, summary: Mapping[str, Any] | None = None) -> None:
        _check(status, schema.RUN_STATUSES, "run status")
        self.conn.execute(
            "UPDATE runs SET status = ?, finished_at = ?, summary_json = ? WHERE run_id = ?",
            (status, to_db(now_utc()), json.dumps(summary, ensure_ascii=False) if summary is not None else None,
             run_id),
        )

    def mark_interrupted_runs(self) -> list[str]:
        """Mark runs left 'running' by other processes as interrupted.

        Call only while holding the writer lock: no other process can be writing then, so any
        'running' run not owned by this process was cut short (crash, kill, power loss).
        """
        stale = [
            run_id
            for run_id, pid in self.conn.execute("SELECT run_id, pid FROM runs WHERE status = 'running'")
            if pid != os.getpid()
        ]
        for run_id in stale:
            self.conn.execute(
                "UPDATE runs SET status = 'interrupted', finished_at = ? WHERE run_id = ?",
                (to_db(now_utc()), run_id),
            )
        return stale

    def record_item_result(self, run_id: str, app_id: int | None, stage: str, status: str,
                           reason_code: str | None = None, message: str | None = None) -> None:
        _check(stage, schema.STAGES, "stage")
        _check(status, schema.ITEM_STATUSES, "item status")
        self.conn.execute(
            "INSERT INTO run_item_results (run_id, app_id, stage, status, reason_code, message, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, app_id, stage, status, reason_code, message, to_db(now_utc())),
        )

    # --- products & facts --------------------------------------------------------------------

    def ensure_product(self, app_id: int, via: str, seen_at: datetime) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO products (app_id, first_seen_at, first_seen_via) VALUES (?, ?, ?)",
            (app_id, to_db(seen_at), via),
        )

    def add_facts(self, run_id: str | None, app_id: int, values: Mapping[str, Any], *, source: str,
                  retrieved_at: datetime) -> None:
        unknown = set(values) - set(schema.FACT_VOLATILITY)
        if unknown:
            raise ValueError(f"unknown fact field(s): {sorted(unknown)}")
        self.conn.executemany(
            "INSERT INTO product_facts (app_id, field, value_json, volatility, source, retrieved_at, run_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (app_id, field, json.dumps(value, ensure_ascii=False), schema.FACT_VOLATILITY[field], source,
                 to_db(retrieved_at), run_id)
                for field, value in values.items()
            ],
        )

    # --- mappings ---------------------------------------------------------------------------

    def add_mapping(self, run_id: str | None, app_id: int, source: str, external_id: str | None,
                    verification: str, *, checked_at: datetime, reason_code: str | None = None,
                    warnings: Iterable[str] = (), aliases: Iterable[str] = ()) -> None:
        _check(verification, schema.VERIFICATIONS, "verification")
        self.conn.execute(
            "INSERT INTO source_mappings (app_id, source, external_id, verification, reason_code, warnings_json, "
            "aliases_json, checked_at, run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (app_id, source, external_id, verification, reason_code, json.dumps(list(warnings)),
             json.dumps(list(aliases)), to_db(checked_at), run_id),
        )

    # --- observations -----------------------------------------------------------------------

    def add_observations(self, run_id: str | None, observations: Iterable[NewObservation]) -> int:
        """Insert observations, ignoring exact duplicates. Returns the number of new rows."""
        rows = []
        for obs in observations:
            anomaly = detect_anomaly(obs) if obs.region == PRIMARY_REGION else _detect_aux_anomaly(obs)
            rows.append((
                obs.app_id, obs.source, obs.region, obs.currency, obs.regular_cents, obs.price_cents, obs.cut_pct,
                to_db(obs.observed_at), obs.raw_observed_at, to_db(obs.retrieved_at), int(obs.is_tracking_start),
                anomaly, run_id, obs.external_id,
            ))
        before = self.conn.total_changes
        with self.transaction():
            self.conn.executemany(
                "INSERT OR IGNORE INTO price_observations (app_id, source, region, currency, regular_cents, "
                "price_cents, cut_pct, observed_at, raw_observed_at, retrieved_at, is_tracking_start, anomaly, run_id, "
                "external_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        return self.conn.total_changes - before

    # --- purchase options (feature 009, data-model §1) ----------------------------------------

    def add_purchase_options(self, run_id: str | None, options: Iterable[NewPurchaseOption], *,
                             checked_at: datetime) -> int:
        """Insert one daily step's rows (append-only). Returns the number of rows written."""
        rows = []
        for o in options:
            _check(o.kind, schema.OPTION_KINDS, "option kind")
            _check(o.role, schema.OPTION_ROLES, "option role")
            if o.verification is not None:
                _check(o.verification, schema.VERSION_VERIFICATIONS, "option verification")
            if o.verified_by is not None:
                _check(o.verified_by, schema.VERSION_VERIFIED_BY, "option verified_by")
            rows.append((
                o.app_id, to_db(checked_at), run_id, o.kind, o.option_id, o.name, o.original_cents, o.final_cents,
                o.position, int(o.is_default), o.role,
                json.dumps(o.contents, ensure_ascii=False) if o.contents is not None else None,
                to_db(o.contents_checked_at) if o.contents_checked_at else None, o.external_id, o.verification,
                o.verified_by, to_db(o.verified_at) if o.verified_at else None, o.reason_code, o.reason_detail,
                json.dumps(o.warnings, ensure_ascii=False) if o.warnings is not None else None,
                json.dumps(o.aliases) if o.aliases is not None else None, o.itad_steam_deals,
                o.bundle_discount_pct, o.before_bundle_cents))
        with self.transaction():
            self.conn.executemany(
                "INSERT INTO purchase_options (app_id, checked_at, run_id, kind, option_id, name, original_cents, "
                "final_cents, position, is_default, role, contents_json, contents_checked_at, external_id, "
                "verification, verified_by, verified_at, reason_code, reason_detail, warnings_json, aliases_json, "
                "itad_steam_deals, bundle_discount_pct, before_bundle_cents) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        return len(rows)

    # --- versions (feature 006, data-model §1) -------------------------------------------------

    def add_version(self, run_id: str | None, app_id: int, *, checked_at: datetime, status: str,
                    package_id: int | None = None, package_name: str | None = None,
                    regular_cents: int | None = None, price_cents: int | None = None,
                    external_id: str | None = None, itad_title: str | None = None,
                    verification: str | None = None, verified_by: str | None = None,
                    verified_at: datetime | None = None, reason_code: str | None = None,
                    reason_detail: str | None = None, warnings: Iterable[str] | None = None,
                    aliases: Iterable[str] | None = None, itad_steam_deals: int | None = None) -> int:
        _check(status, schema.VERSION_STATUSES, "version status")
        if verification is not None:
            _check(verification, schema.VERSION_VERIFICATIONS, "version verification")
        if verified_by is not None:
            _check(verified_by, schema.VERSION_VERIFIED_BY, "version verified_by")
        cursor = self.conn.execute(
            "INSERT INTO app_versions (app_id, checked_at, run_id, status, package_id, package_name, regular_cents, "
            "price_cents, external_id, itad_title, verification, verified_by, verified_at, reason_code, reason_detail, "
            "warnings_json, aliases_json, itad_steam_deals) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (app_id, to_db(checked_at), run_id, status, package_id, package_name, regular_cents, price_cents,
             external_id, itad_title, verification, verified_by, to_db(verified_at) if verified_at else None,
             reason_code, reason_detail, json.dumps(list(warnings), ensure_ascii=False) if warnings is not None else None,
             json.dumps(list(aliases)) if aliases is not None else None, itad_steam_deals),
        )
        return cursor.lastrowid
