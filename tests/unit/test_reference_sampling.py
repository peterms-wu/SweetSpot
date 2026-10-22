"""US4 sampling rules (FR-016, FR-016a, FR-018; research R5)."""

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from sweetspot.config import load_config
from tests.config_builders import TEST_TOML
from sweetspot.pipeline import sampling
from sweetspot.sources import AppDetails, ItemSummary, PriceQuote

NOW = datetime(2026, 9, 25, tzinfo=UTC)


@pytest.fixture
def ref(tmp_path):
    path = tmp_path / "s.toml"
    path.write_text(TEST_TOML, encoding="utf-8")
    return load_config(path)[0].reference


@pytest.mark.parametrize(
    "year,price,indie,key",
    [
        (2019, 350, True, "y2019-2020/p300-599/indie"),
        (2015, 299, False, "y-2015/p0-299/nonindie"),
        (2016, 600, False, "y2016-2018/p600-999/nonindie"),
        (2024, 1000, True, "y2023-2024/p1000-/indie"),
        (2025, 999, False, "y2025-/p600-999/nonindie"),
    ],
)
def test_stratum_key(ref, year, price, indie, key):
    assert sampling.stratum_key(year, price, indie, ref) == key


def test_there_are_48_strata(ref):
    assert len(sampling.all_strata(ref)) == 48


def test_rank_is_reproducible_and_seed_dependent(ref):
    ids = list(range(1, 200))
    order = sorted(ids, key=lambda a: sampling.rank(ref.seed, a))
    assert order == sorted(ids, key=lambda a: sampling.rank(ref.seed, a))
    assert order != sorted(ids, key=lambda a: sampling.rank(ref.seed + 1, a))
    # adding apps never reorders the ones already there (stable as catalogs grow)
    grown = sorted(ids + [500, 501], key=lambda a: sampling.rank(ref.seed, a))
    assert [a for a in grown if a < 200] == order


def test_sample_version_changes_with_any_sampling_setting(ref):
    base = sampling.sample_version(ref)
    assert base == sampling.sample_version(ref)
    for change in (dict(seed=1), dict(broad_per_stratum=10), dict(per_publisher_cap=5),
                   dict(min_total_reviews=100), dict(year_bins=(2010, 2020)), dict(price_bins_twd=(500,))):
        assert sampling.sample_version(replace(ref, **change)) != base
    assert sampling.sample_version(replace(ref, daily_budget_seconds=5)) == base   # not a sampling setting


def item(**kw):
    base = dict(app_id=1, name="x", review_count_filtered=500, percent_positive=90, tag_ids=[], app_type=0,
                is_free=False, release_date=date(2020, 1, 1), coming_soon=False)
    base.update(kw)
    return ItemSummary(**base)


@pytest.mark.parametrize(
    "summary,reason",
    [
        (item(app_type=4), "not-game"),
        (item(is_free=True), "free"),
        (item(coming_soon=True), "unreleased"),
        (item(release_date=date(2027, 1, 1)), "unreleased"),
        (item(review_count_filtered=3), "few-reviews"),
        (item(), None),
        (item(review_count_filtered=45), None),     # borderline: must be confirmed with the total count
        (item(release_date=None), None),            # unknown: needs the full details
    ],
)
def test_prefilter(ref, summary, reason):
    assert sampling.prefilter(summary, ref, NOW) == reason


def details(**kw):
    base = dict(app_id=1, name="x", type="game", is_free=False, coming_soon=False, release_date=date(2020, 5, 1),
                genres=[{"id": "23", "description": "獨立"}], quote=PriceQuote("TWD", 35000, 35000, 0))
    base.update(kw)
    return AppDetails(**base)


@pytest.mark.parametrize(
    "d,total,result",
    [
        (details(), 120, (None, "y2019-2020/p300-599/indie")),
        (details(type="dlc"), 120, ("not-game", None)),
        (details(is_free=True, quote=None), 120, ("free", None)),
        (details(coming_soon=True), 120, ("unreleased", None)),
        (details(quote=None), 120, ("no-tw-price", None)),
        (details(quote=PriceQuote("USD", 999, 999, 0)), 120, ("no-tw-price", None)),
        (details(), 49, ("few-reviews", None)),
        (details(), None, ("few-reviews", None)),
        (details(genres=[{"id": "1", "description": "動作"}]), 50, (None, "y2019-2020/p300-599/nonindie")),
        (details(quote=PriceQuote("TWD", 35000, 17500, 50)), 50, (None, "y2019-2020/p300-599/indie")),  # regular price
    ],
)
def test_evaluate_details(ref, d, total, result):
    assert sampling.evaluate(d, total, ref, NOW) == result


def test_reject_reasons_are_the_documented_set():
    assert sampling.REJECT_REASONS == {"free", "unreleased", "few-reviews", "no-tw-price", "not-game",
                                       "stratum-full", "publisher-cap"}


def test_likely_prefix_from_item_summary(ref):
    assert sampling.likely_prefix(item(release_date=date(2019, 5, 1), regular_price_cents=45000), ref) == \
        "y2019-2020/p300-599"
    assert sampling.likely_prefix(item(regular_price_cents=None), ref) is None
    assert sampling.stratum_key(2019, 450, True, ref).startswith(sampling.stratum_prefix(2019, 450, ref))


def test_dataset_size_ignores_edition_histories(db_path):
    """Feature 009: an edition's rows (itad-option-history) do not make an app part of the reference dataset."""
    from datetime import UTC, datetime

    from sweetspot.pipeline.reference import dataset_size
    from sweetspot.store.writer import NewObservation, StoreWriter

    now = datetime(2026, 9, 25, tzinfo=UTC)
    w = StoreWriter.open(db_path)
    run = w.start_run("daily")
    w.add_observations(run, [NewObservation(app_id=7, source="itad-option-history", region="TW", currency="TWD",
                                            regular_cents=1000, price_cents=1000, cut_pct=0, observed_at=now,
                                            raw_observed_at=None, retrieved_at=now, external_id="ed-7")])
    assert dataset_size(w) == 0
    w.close()
