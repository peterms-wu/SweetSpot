"""Synthetic databases and calendars for feature 002 tests (tasks T002).

Series are written the way ITAD history lands in the store: one row per price change, the first row of each
series flagged as the tracking start. Times are UTC; a bare date means 00:00 UTC.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sweetspot.store.writer import NewObservation, StoreWriter
from sweetspot.timeutil import now_utc, to_db

SEASON_NAMES = {"spring": ("Steam Spring Sale", "春季特賣"), "summer": ("Steam Summer Sale", "夏季特賣"),
                "autumn": ("Steam Autumn Sale", "秋季特賣"), "winter": ("Steam Winter Sale", "冬季特賣")}


def dt(text: str) -> datetime:
    """'2025-06-26' or '2025-06-26T17:00' → aware UTC datetime."""
    value = datetime.fromisoformat(text)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass(frozen=True)
class Sale:
    season: str | None
    year: int
    start: str
    end: str
    kind: str = "seasonal"
    name: str | None = None


def write_calendar(path: Path, sales: list[Sale]) -> Path:
    now = now_utc()
    lines = ['schema_version = 1', 'default_time = "10:00"', 'default_tz = "America/Los_Angeles"', ""]
    for sale in sales:
        name, name_zh = SEASON_NAMES.get(sale.season, (sale.name or "Themed Sale", "主題特賣"))
        start, end = dt(sale.start), dt(sale.end)
        lines += [
            "[[sale]]",
            f'name = "{sale.name or name}"',
            f'name_zh = "{name_zh}"',
            f'kind = "{sale.kind}"',
            *([f'season = "{sale.season}"'] if sale.season else []),
            f"year = {sale.year}",
            f'start = "{start.strftime("%Y-%m-%dT%H:%M:%SZ")}"',
            f'end = "{end.strftime("%Y-%m-%dT%H:%M:%SZ")}"',
            f'status = "{"ended" if end <= now else "announced"}"',
            f'source = "https://example.test/{sale.year}-{sale.season or "themed"}"',
            'confidence = "official"',
            "",
        ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


@dataclass
class GameSpec:
    """One app. `tw` / `us` rows are (time, cut) or (time, cut, regular_cents); the first row is the tracking
    start. `known_until` maps region → last history fetch time (defaults to the last row's time + 1 day)."""

    app_id: int
    tw: list[tuple] = field(default_factory=list)
    us: list[tuple] = field(default_factory=list)
    regular_cents: int = 50000
    name: str | None = None
    release_date: str | None = "2015-01-01"
    release_state: str | None = None
    product_type: str = "game"
    mapping: str | None = "verified"
    known_until: dict[str, str] = field(default_factory=dict)
    source: str = "itad-history"
    first_seen_via: str = "reference-broad"
    wishlist: bool = False
    pool: str | None = None        # reference_candidates pool: broad | related-publisher | related-developer
    extra_tw: list[NewObservation] = field(default_factory=list)
    external_id: str | None = None  # the app's own ITAD id; defaults to "itad-<app_id>" when it has a mapping

    @property
    def own_id(self) -> str | None:
        return self.external_id or (f"itad-{self.app_id}" if self.mapping else None)


def _observation(app_id: int, region: str, source: str, row: tuple, regular: int, first: bool,
                 retrieved: datetime, external_id: str | None = None) -> NewObservation:
    when, cut = dt(row[0]), row[1]
    reg = row[2] if len(row) > 2 else regular
    tw = region == "TW"
    return NewObservation(
        app_id=app_id, source=source, region=region, currency="TWD" if tw else None,
        regular_cents=reg if tw else None,
        price_cents=(None if cut is None else reg * (100 - cut) // 100) if tw else None,
        cut_pct=cut, observed_at=when, raw_observed_at=None, retrieved_at=max(retrieved, when),
        is_tracking_start=first, external_id=external_id)


def build_db(db_path: Path, games: list[GameSpec], *, calendar: list[Sale] | None = None) -> Path:
    """Create a store with the given apps. The calendar (if any) is written next to the database, which is
    where PriceStore.open() looks for it."""
    retrieved = dt("2026-09-24")
    writer = StoreWriter.open(db_path)
    run = writer.start_run("daily")
    try:
        with writer.transaction():
            for g in games:
                writer.ensure_product(g.app_id, g.first_seen_via, dt("2026-09-01"))
                facts = {"name": g.name or f"Game {g.app_id}", "product_type": g.product_type}
                if g.release_date:
                    facts["release_date"] = g.release_date
                if g.release_state:
                    facts["release_state"] = g.release_state
                writer.add_facts(run, g.app_id, facts, source="steam-appdetails", retrieved_at=retrieved)
                if g.mapping:
                    writer.add_mapping(run, g.app_id, "itad", g.own_id, g.mapping, checked_at=retrieved)
                if g.wishlist:
                    writer.conn.execute(
                        "INSERT INTO wishlist_membership (app_id, state, first_added_at, updated_at) "
                        "VALUES (?, 'in_wishlist', ?, ?)", (g.app_id, to_db(retrieved), to_db(retrieved)))
                if g.pool:
                    writer.conn.execute(
                        "INSERT INTO reference_candidates (app_id, pool, pool_detail, sample_version, status, "
                        "updated_at) VALUES (?, ?, 'test', 'v1', 'fetched', ?)", (g.app_id, g.pool, to_db(retrieved)))
                for region, rows in (("TW", g.tw), ("US", g.us)):
                    if not rows:
                        continue
                    writer.add_observations(run, [
                        _observation(g.app_id, region, g.source, row, g.regular_cents, i == 0, retrieved, g.own_id)
                        for i, row in enumerate(rows)])
                    until = g.known_until.get(region)
                    fetched = dt(until) if until else max(dt(r[0]) for r in rows) + timedelta(days=1)
                    if g.source == "itad-history":
                        writer.conn.execute(
                            "INSERT INTO history_fetches (app_id, source, region, fetched_at, entries, run_id, "
                            "external_id) VALUES (?, 'itad', ?, ?, ?, ?, ?)",
                            (g.app_id, region, to_db(fetched), len(rows), run, g.own_id))
                if g.extra_tw:
                    writer.add_observations(run, g.extra_tw)
        writer.finish_run(run, "completed")
    finally:
        writer.close()
    if calendar is not None:
        write_calendar(Path(db_path).parent / "steam_sales.toml", calendar)
    return Path(db_path)


def add_history(db_path: Path, app_id: int, external_id: str, *, tw: list[tuple] = (), us: list[tuple] = (),
                regular_cents: int = 50000, fetched: str | None = None, source: str = "itad-history",
                fetch_source: str = "itad") -> None:
    """Another ITAD product's history for an existing app (feature 006): rows tagged with `external_id`, the first
    row of each region the tracking start, one history fetch per region. Feature 009: an edition's history uses
    source `itad-option-history` and fetch source `itad-option`."""
    retrieved = dt("2026-09-24")
    writer = StoreWriter.open(db_path)
    try:
        run = writer.start_run("daily")
        with writer.transaction():
            for region, rows in (("TW", tw), ("US", us)):
                if not rows:
                    continue
                writer.add_observations(run, [
                    _observation(app_id, region, source, row, regular_cents, i == 0, retrieved, external_id)
                    for i, row in enumerate(rows)])
                when = dt(fetched) if fetched else max(dt(r[0]) for r in rows) + timedelta(days=1)
                writer.conn.execute(
                    "INSERT INTO history_fetches (app_id, source, region, fetched_at, entries, run_id, external_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)", (app_id, fetch_source, region, to_db(when), len(rows), run,
                                                     external_id))
        writer.finish_run(run, "completed")
    finally:
        writer.close()


def add_version(db_path: Path, app_id: int, checked_at: str, *, external_id: str | None, package_id: int | None = 100,
                status: str = "ok", verification: str | None = "verified", verified_by: str | None = "version-check",
                itad_steam_deals: int | None = 1, price_cents: int | None = 50000, regular_cents: int | None = 50000,
                reason_code: str | None = None, reason_detail: str | None = None, package_name: str | None = None,
                itad_title: str | None = None, verified_at: str | None = None) -> None:
    """One app_versions row (feature 006, data-model §1)."""
    writer = StoreWriter.open(db_path)
    try:
        ok = status == "ok"
        writer.add_version(None, app_id, checked_at=dt(checked_at), status=status,
                           package_id=package_id if status not in ("no-option", "ambiguous") else None,
                           package_name=package_name or (f"Package {package_id}" if package_id else None),
                           regular_cents=regular_cents, price_cents=price_cents, external_id=external_id,
                           itad_title=itad_title or (f"Title {external_id}" if external_id else None),
                           verification=verification if ok else None, verified_by=verified_by if ok else None,
                           verified_at=dt(verified_at or checked_at) if ok else None, reason_code=reason_code,
                           reason_detail=reason_detail, itad_steam_deals=itad_steam_deals)
    finally:
        writer.close()


# A small calendar used by many tests: 2024 winter .. 2027 spring (spring exists from 2023 on).
BASIC_CALENDAR = [
    Sale("summer", 2023, "2023-06-29T17:00", "2023-07-13T17:00"),
    Sale("autumn", 2023, "2023-11-21T18:00", "2023-11-28T18:00"),
    Sale("winter", 2023, "2023-12-21T18:00", "2024-01-04T18:00"),
    Sale("spring", 2024, "2024-03-14T17:00", "2024-03-21T17:00"),
    Sale("summer", 2024, "2024-06-27T17:00", "2024-07-11T17:00"),
    Sale("autumn", 2024, "2024-11-27T18:00", "2024-12-04T18:00"),
    Sale("winter", 2024, "2024-12-19T18:00", "2025-01-02T18:00"),
    Sale("spring", 2025, "2025-03-13T17:00", "2025-03-20T17:00"),
    Sale("summer", 2025, "2025-06-26T17:00", "2025-07-10T17:00"),
    Sale("autumn", 2025, "2025-09-29T17:00", "2025-10-06T17:00"),
    Sale("winter", 2025, "2025-12-18T18:00", "2026-01-05T18:00"),
    Sale("spring", 2026, "2026-03-19T17:00", "2026-03-26T17:00"),
    Sale("summer", 2026, "2026-06-25T17:00", "2026-07-09T17:00"),
]


# --- feature 004: evidence without a database (tasks T001) -------------------------------------------------

_ROTATION = ("winter", "spring", "summer", "autumn")
_SEASON_ZH = {"spring": "春特", "summer": "夏特", "autumn": "秋特", "winter": "冬特"}
_SEASON_MONTH = {"spring": 3, "summer": 6, "autumn": 9, "winter": 12}


def outcomes(cuts, region: str = "TW", first_year: int = 2019):
    """Ended seasonal sales with the given max cuts, oldest first: winter, spring, summer, autumn, …"""
    from sweetspot.forecast.series import SaleOutcome

    out = []
    for i, cut in enumerate(cuts):
        season = _ROTATION[i % 4]
        year = first_year + (i + 3) // 4 if season != "winter" else first_year + i // 4
        start = datetime(year, _SEASON_MONTH[season], 20, 17, tzinfo=UTC)
        out.append(SaleOutcome(season, year, f"{year} {_SEASON_ZH[season]}", region, start,
                               start + timedelta(days=10), cut))
    return tuple(out)


AFTER_OUTCOMES = dt("2030-01-01")


def evidence(cuts_by_region, *, as_of: datetime = AFTER_OUTCOMES, target: str = "TW", app_id: int = 1,
             release_date=None, first_year: int = 2019):
    """GameEvidence for a model: `cuts_by_region` is {"TW": [cuts], "US": [cuts]} or a plain list (TW).
    `release_date` (feature 008) is the target's static release date; None = unknown."""
    from sweetspot.forecast.evidence import GameEvidence, visible_regions

    if not isinstance(cuts_by_region, dict):
        cuts_by_region = {"TW": cuts_by_region}
    history = {r: outcomes(cuts_by_region.get(r, ()), r, first_year) for r in visible_regions(target)}
    return GameEvidence(app_id=app_id, as_of=as_of, target_region=target, series={}, sale_history=history,
                        release_date=release_date)


def population(histories, *, as_of: datetime = AFTER_OUTCOMES, target: str = "TW", release_dates=None,
               first_years=None):
    """PopulationView from {app_id: {"TW": [cuts], "US": [cuts]}} (a plain list means TW only).
    Feature 008: `release_dates` {app_id: date | None}; `first_years` {app_id: year of the first record}."""
    from sweetspot.forecast.evidence import PopulationView, visible_regions

    view = {}
    for app, h in histories.items():
        if not isinstance(h, dict):
            h = {"TW": h}
        year = (first_years or {}).get(app, 2019)
        view[app] = {r: outcomes(h.get(r, ()), r, year) for r in visible_regions(target)}
    return PopulationView(as_of, target, view, dict(release_dates or {}))


def future_points(n: int, first_year: int = 2030):
    """n future seasonal-sale points after AFTER_OUTCOMES, one per quarter."""
    from sweetspot.forecast.salepoints import SalePoint

    out = []
    for i in range(n):
        season = ("spring", "summer", "autumn", "winter")[i % 4]
        year = first_year + i // 4
        start = datetime(year, _SEASON_MONTH[season], 20, 17, tzinfo=UTC)
        out.append(SalePoint(i + 1, season, year, f"{year} {_SEASON_ZH[season]}", start, start + timedelta(days=10),
                             "estimated", None))
    return tuple(out)


def add_purchase_options(db_path: Path, app_id: int, checked_at: str, options: list[dict]) -> None:
    """One purchase-option step for an app (feature 009, data-model §1). Each dict needs kind, option_id,
    original_cents, final_cents and role; the rest defaults (position = list order)."""
    from sweetspot.store.writer import NewPurchaseOption

    writer = StoreWriter.open(db_path)
    try:
        rows = []
        for position, o in enumerate(options):
            o = dict(o)
            if o.get("verified_at"):
                o["verified_at"] = dt(o["verified_at"])
            rows.append(NewPurchaseOption(app_id=app_id, position=position, name=o.pop("name", None),
                                          is_default=o.pop("is_default", o["role"] == "default"), **o))
        writer.add_purchase_options(None, rows, checked_at=dt(checked_at))
    finally:
        writer.close()
