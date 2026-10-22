"""Reference-sample rules: reproducible ranking, strata and eligibility (FR-016, FR-016a; research R5).

These are engineering choices, not model facts (constitution VI); feature 002 may retune them, which
changes `sample_version` and starts a new sample while keeping the old one.
"""

import hashlib
import json
from datetime import datetime

from sweetspot.config import ReferenceConfig
from sweetspot.products import is_indie, product_type
from sweetspot.sources import AppDetails, ItemSummary

REJECT_REASONS = {"free", "unreleased", "few-reviews", "no-tw-price", "not-game", "stratum-full", "publisher-cap"}
GAME_TYPE_CODE = 0
# GetItems reports a filtered review count that is never above the total. Below this share of the
# threshold we reject without asking for the total; closer to it we confirm with the total count.
FILTERED_REVIEW_MARGIN = 0.8


def sample_version(ref: ReferenceConfig) -> str:
    settings = {"seed": ref.seed, "per_publisher_cap": ref.per_publisher_cap,
                "broad_per_stratum": ref.broad_per_stratum, "min_total_reviews": ref.min_total_reviews,
                "year_bins": list(ref.year_bins), "price_bins_twd": list(ref.price_bins_twd)}
    return hashlib.sha256(json.dumps(settings, sort_keys=True).encode()).hexdigest()[:12]


def rank(seed: int, app_id: int) -> int:
    """Seeded pseudo-random rank. Depends only on (seed, app), so growing lists never reorder old members."""
    return int.from_bytes(hashlib.sha256(f"{seed}:{app_id}".encode()).digest()[:8], "big")


def _bin_labels(edges: tuple[int, ...], prefix: str, inclusive_upper: bool) -> list[tuple[int | None, str]]:
    labels = []
    lower = None
    for edge in edges:
        if inclusive_upper:   # year bins: (lower, edge]
            labels.append((edge, f"{prefix}{'' if lower is None else lower + 1}-{edge}"))
            lower = edge
        else:                 # price bins: [lower, edge)
            labels.append((edge, f"{prefix}{0 if lower is None else lower}-{edge - 1}"))
            lower = edge
    labels.append((None, f"{prefix}{lower + 1 if inclusive_upper else lower}-"))
    return labels


def stratum_prefix(release_year: int, regular_price_twd: float, ref: ReferenceConfig) -> str:
    """'year-bin/price-bin' — the part of the stratum known before the indie genre is looked up."""
    year_label = next(label for edge, label in _bin_labels(ref.year_bins, "y", True)
                      if edge is None or release_year <= edge)
    price_label = next(label for edge, label in _bin_labels(ref.price_bins_twd, "p", False)
                       if edge is None or regular_price_twd < edge)
    return f"{year_label}/{price_label}"


def stratum_key(release_year: int, regular_price_twd: float, indie: bool, ref: ReferenceConfig) -> str:
    return f"{stratum_prefix(release_year, regular_price_twd, ref)}/{'indie' if indie else 'nonindie'}"


def likely_prefix(item: ItemSummary, ref: ReferenceConfig) -> str | None:
    """Year/price bins from a batched store-item summary, or None when either is unknown.

    The summary's price is the best purchase option, which can differ from the app's own package; it is
    used only to skip apps whose year/price strata are both full, never to place an accepted app.
    """
    if item.release_date is None or item.regular_price_cents is None:
        return None
    return stratum_prefix(item.release_date.year, item.regular_price_cents / 100, ref)


def all_strata(ref: ReferenceConfig) -> list[str]:
    return [f"{y}/{p}/{i}" for _, y in _bin_labels(ref.year_bins, "y", True)
            for _, p in _bin_labels(ref.price_bins_twd, "p", False) for i in ("indie", "nonindie")]


def prefilter(item: ItemSummary, ref: ReferenceConfig, now: datetime) -> str | None:
    """Cheap rejection from a batched store-item summary; None means 'look closer'."""
    if item.app_type is not None and item.app_type != GAME_TYPE_CODE:
        return "not-game"
    if item.is_free:
        return "free"
    if item.coming_soon or (item.release_date is not None and item.release_date > now.date()):
        return "unreleased"
    if item.review_count_filtered is not None and \
            item.review_count_filtered < ref.min_total_reviews * FILTERED_REVIEW_MARGIN:
        return "few-reviews"
    return None


def evaluate(details: AppDetails, total_reviews: int | None, ref: ReferenceConfig,
             now: datetime) -> tuple[str | None, str | None]:
    """Full eligibility check. Returns (reject_reason, stratum_key); exactly one is None."""
    if product_type(details.type, details.parent_app_id) != "game":
        return "not-game", None
    if details.is_free:
        return "free", None
    if details.coming_soon or details.release_date is None or details.release_date > now.date():
        return "unreleased", None
    if details.quote is None or details.quote.currency != "TWD":
        return "no-tw-price", None
    if total_reviews is None or total_reviews < ref.min_total_reviews:
        return "few-reviews", None
    indie = bool(is_indie(details.genres))
    return None, stratum_key(details.release_date.year, details.quote.initial_cents / 100, indie, ref)
