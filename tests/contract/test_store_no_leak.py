"""SC-003: randomized interleaved data never leaks anything after as_of (guarantees 1 and 4)."""

import random
from datetime import UTC, datetime, timedelta

from sweetspot.store.query import PriceStore
from sweetspot.store.writer import NewObservation, StoreWriter

START = datetime(2024, 12, 1, tzinfo=UTC)
SPAN_DAYS = 660


def test_no_leak_over_random_as_of_points(db_path):
    rng = random.Random(20260925)
    w = StoreWriter.open(db_path)
    run = w.start_run("daily")
    for app_id in (1, 2, 3):
        observations = []
        for _ in range(60):
            observed = START + timedelta(days=rng.randrange(SPAN_DAYS), seconds=rng.randrange(86400))
            retrieved = observed + timedelta(days=rng.randrange(0, 400))
            region = rng.choice(["TW", "US"])
            source = rng.choice(["itad-history", "steam-current", "legacy-itad"])
            cut = rng.choice([0, 25, 50, 75, 90])
            tw = region == "TW"
            observations.append(NewObservation(
                app_id=app_id, source=source, region=region, currency="TWD" if tw else None,
                regular_cents=50000 if tw else None, price_cents=50000 * (100 - cut) // 100 if tw else None,
                cut_pct=cut, observed_at=observed, raw_observed_at=None, retrieved_at=retrieved))
        w.add_observations(run, observations)
        for _ in range(10):
            w.add_facts(run, app_id, {"review_count_total": rng.randrange(10_000)}, source="steam-appreviews",
                        retrieved_at=START + timedelta(days=rng.randrange(SPAN_DAYS)))
    w.close()

    store = PriceStore.open(db_path)
    try:
        for _ in range(50):
            as_of = START + timedelta(days=rng.randrange(-30, SPAN_DAYS + 30), seconds=rng.randrange(86400))
            for app_id in (1, 2, 3):
                for region in ("TW", "US"):
                    assert all(o.observed_at <= as_of for o in store.observations(app_id, as_of, region=region))
                fact = store.facts(app_id, as_of).review_count_total
                assert fact.value is None or fact.retrieved_at <= as_of
    finally:
        store.close()
