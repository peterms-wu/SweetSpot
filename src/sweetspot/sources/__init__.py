"""External data sources.

Pipelines depend only on the Protocols and value types defined here (FR-010), never on a concrete
client module, so a source can be replaced without touching the analysis pipeline.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol, runtime_checkable


class WishlistFetchError(Exception):
    """The wishlist could not be fetched completely. `reason` is a data-model reject_reason code."""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class WishlistEntry:
    app_id: int
    priority: int | None
    date_added: datetime | None


@dataclass(frozen=True)
class PriceQuote:
    currency: str
    initial_cents: int
    final_cents: int
    discount_pct: int


@dataclass(frozen=True)
class PriceLookup:
    """Result of a batched current-price query. `found` is False when the store has no such app."""

    app_id: int
    found: bool
    quote: PriceQuote | None


@dataclass(frozen=True)
class AppDetails:
    app_id: int
    name: str | None
    type: str | None                      # game, dlc, music, ...
    is_free: bool | None
    coming_soon: bool | None
    release_date: date | None
    publishers: list[str] = field(default_factory=list)
    developers: list[str] = field(default_factory=list)
    genres: list[dict] = field(default_factory=list)
    parent_app_id: int | None = None
    package_ids: list[int] = field(default_factory=list)
    quote: PriceQuote | None = None


@dataclass(frozen=True)
class ReviewSummary:
    total_reviews: int
    total_positive: int


@dataclass(frozen=True)
class ItemSummary:
    app_id: int
    name: str | None
    review_count_filtered: int | None
    percent_positive: int | None
    tag_ids: list[int] = field(default_factory=list)
    app_type: int | None = None            # IStoreBrowseService type code; 0 = game
    is_free: bool | None = None
    release_date: date | None = None
    coming_soon: bool | None = None
    regular_price_cents: int | None = None   # best purchase option: original price if discounted, else final


@dataclass(frozen=True)
class CatalogPage:
    """One page of a publisher/developer store search."""

    app_ids: list[int]
    total_count: int
    start: int
    rows: int | None = None      # result rows on the page incl. packages/bundles; paging advances by this

    @property
    def row_count(self) -> int:
        return len(self.app_ids) if self.rows is None else self.rows


@dataclass(frozen=True)
class AppListPage:
    apps: list[tuple[int, str, int | None]]   # (app_id, name, last_modified)
    have_more: bool
    last_appid: int | None


@dataclass(frozen=True)
class PackageDetails:
    package_id: int
    app_ids: list[int]
    quote: PriceQuote | None


@dataclass(frozen=True)
class PurchaseOption:
    """One way to buy an app on the Taiwan store (feature 006): a package (Steam sub) or a bundle. Prices are the
    option's own; `original_cents` is the final price when there is no discount."""
    package_id: int | None
    bundle_id: int | None
    name: str | None
    original_cents: int
    final_cents: int
    bundle_discount_pct: int | None = None       # feature 010: bundles only; None when Steam did not say
    before_bundle_cents: int | None = None       # feature 010: Steam's price_before_bundle_discount


@dataclass(frozen=True)
class VersionPackage:
    """A Steam package's contents (feature 006). `public` is False when the store does not describe it."""
    package_id: int
    public: bool
    app_ids: list[int]
    name: str | None


@dataclass(frozen=True)
class ContentPrice:
    """Feature 010: an app's Taiwan store price (its best purchase option) and name, for the contents of bundles
    holding several wishlist games. None = unknown, never 0 (constitution I)."""
    app_id: int
    final_cents: int | None
    name: str | None


@dataclass(frozen=True)
class BundleContents:
    """A Steam bundle's apps (feature 009). `found` is False when the store does not describe it: its contents are
    unknown, not empty (constitution I)."""
    bundle_id: int
    found: bool
    app_ids: list[int]
    name: str | None


@dataclass(frozen=True)
class AppKind:
    """Store item type (4 = DLC) and the parent game of a DLC (feature 006)."""
    app_id: int
    type: int | None
    parent_app_id: int | None


@dataclass(frozen=True)
class ItadPrice:
    """ITAD's current Steam price of one product (feature 006). `steam_deals` = 0 means ITAD no longer has a
    Steam price for it; `quote` is set only when there is exactly one."""
    quote: PriceQuote | None
    steam_deals: int


@dataclass(frozen=True)
class HistoryEntry:
    observed_at: datetime                 # UTC
    raw_timestamp: str
    currency: str | None
    price_cents: int | None
    regular_cents: int | None
    cut_pct: int | None



@dataclass(frozen=True)
class OfficialSale:
    """Feature 012: one seasonal sale listed with dates on the official seasonal sales page. Dates only: the page has
    no time of day; `end_date` is the day prices return to normal (research R0.2)."""
    season: str                           # spring | summer | autumn | winter
    year: int                             # the title's year; a winter sale uses its start year
    start_date: date
    end_date: date


@dataclass(frozen=True)
class RejectedLine:
    line: str
    reason: str


@dataclass(frozen=True)
class ParsedSales:
    found_dates_section: bool
    sales: list[OfficialSale] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)          # listed without dates ("TBD")
    rejected: list[RejectedLine] = field(default_factory=list)


@dataclass(frozen=True)
class SeasonalSalesPage:
    url: str
    fetched_at: datetime                  # UTC
    http_status: int
    bytes: int
    sha256: str
    found_dates_section: bool
    sales: list[OfficialSale] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    rejected: list[RejectedLine] = field(default_factory=list)

@runtime_checkable
class WishlistSource(Protocol):
    def get_wishlist(self, steamid: str) -> list[WishlistEntry]: ...


@runtime_checkable
class CurrentPriceSource(Protocol):
    def current_prices(self, app_ids: list[int]) -> dict[int, PriceLookup]: ...


@runtime_checkable
class MetadataSource(Protocol):
    def app_details(self, app_id: int) -> AppDetails | None: ...

    def canonical_app_id(self, app_id: int) -> int | None: ...

    def item_summaries(self, app_ids: list[int]) -> dict[int, ItemSummary]: ...

    def review_summary(self, app_id: int) -> ReviewSummary | None: ...

    def package_details(self, package_id: int) -> PackageDetails | None: ...

    def package_details_batch(self, package_ids: list[int]) -> dict[int, PackageDetails | None]: ...


@runtime_checkable
class CatalogSource(Protocol):
    def search_catalog(self, kind: str, name: str, start: int) -> CatalogPage: ...


@runtime_checkable
class AppListSource(Protocol):
    def app_list(self, last_appid: int | None, max_results: int) -> AppListPage: ...


@runtime_checkable
class HistorySource(Protocol):
    def lookup_steam(self, app_ids: list[int]) -> dict[int, str | None]: ...

    def reverse_lookup(self, external_ids: list[str]) -> dict[str, list[str]]: ...

    def history(self, external_id: str, country: str, since: datetime) -> list[HistoryEntry]: ...

    def current_prices(self, external_ids: list[str], country: str) -> dict[str, PriceQuote | None]: ...


@runtime_checkable
class ItadPriceSource(Protocol):
    """Feature 006: ITAD current prices with the Steam price count (ids missing from the result are unknown),
    and the ITAD product of a Steam package."""

    def price_summaries(self, external_ids: list[str], country: str) -> dict[str, ItadPrice]: ...

    def lookup_packages(self, package_ids: list[int]) -> dict[int, str | None]: ...


@runtime_checkable
class VersionSource(Protocol):
    """Feature 006: what the Taiwan store sells for an app, batched (GetItems)."""

    def purchase_options(self, app_ids: list[int]) -> dict[int, list[PurchaseOption]]: ...

    def version_packages(self, package_ids: list[int]) -> dict[int, VersionPackage]: ...

    def app_kinds(self, app_ids: list[int]) -> dict[int, AppKind]: ...


@runtime_checkable
class BundleSource(Protocol):
    """Feature 009: what a Steam bundle contains (GetItems bundleid), batched."""

    def bundle_contents(self, bundle_ids: list[int]) -> dict[int, BundleContents]: ...


@runtime_checkable
class ContentPriceSource(Protocol):
    """Feature 010: current prices and names of the apps inside wishlist bundles (GetItems), batched."""

    def content_prices(self, app_ids: list[int]) -> dict[int, ContentPrice]: ...


@runtime_checkable
class OptionLookupSource(Protocol):
    """Feature 009: the ITAD product of Steam packages and bundles, in one request per 200 ids."""

    def lookup_ids(self, ids: list[tuple[str, int]]) -> dict[tuple[str, int], str | None]: ...


@runtime_checkable
class SeasonalSalesSource(Protocol):
    """Feature 012: the official seasonal sales page. Raises SourceError (SourceDisabled, RateLimited) on failure."""

    def seasonal_sales_page(self) -> SeasonalSalesPage: ...
