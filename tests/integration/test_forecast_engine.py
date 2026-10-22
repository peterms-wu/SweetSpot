"""Forecast engine on a synthetic store: statuses, isolation, determinism (tasks T015)."""

from dataclasses import replace

import pytest

from sweetspot.forecast.contract import LEVELS, batch_to_dict
from sweetspot.forecast.engine import run_forecast
from sweetspot.forecast.models import build_model
from sweetspot.forecast.models.base import ModelOutput
from sweetspot.store.query import PriceStore
from tests.forecast_builders import BASIC_CALENDAR, GameSpec, build_db, dt

AS_OF = dt("2025-08-01")
SALE_HISTORY = [("2024-12-11", 0), ("2024-12-19T18:00", 50), ("2025-01-02T18:00", 0),
                ("2025-03-13T17:00", 40), ("2025-03-20T17:00", 0), ("2025-06-26T17:00", 60),
                ("2025-07-10T17:00", 0, 45000)]


class Faulty:
    """Delegates to the baseline, but raises for app 7 and returns an invalid curve for app 8."""

    def __init__(self):
        self.inner = build_model("seasonal-freq")
        self.name, self.version, self.params = self.inner.name, self.inner.version, self.inner.params
        self.tw_only_params = self.inner.tw_only_params

    def confidence_levels(self):
        return self.inner.confidence_levels()

    def prepare(self, population):
        self.inner.prepare(population)

    def predict(self, game, points, levels):
        if game.app_id == 7:
            raise RuntimeError("boom")
        out = self.inner.predict(game, points, levels)
        if game.app_id == 8:
            bad = tuple(tuple(reversed(row)) for row in out.probabilities)
            return replace(out, probabilities=bad)
        return out


@pytest.fixture
def store(db_path):
    games = [
        GameSpec(1, tw=SALE_HISTORY, name="Good"),
        GameSpec(2, product_type="bundle", tw=SALE_HISTORY),
        GameSpec(3, release_date="2027-01-01"),
        GameSpec(4, tw=[("2024-12-11", 0)], regular_cents=0),
        GameSpec(5, tw=SALE_HISTORY, mapping="rejected"),
        GameSpec(6),
        GameSpec(7, tw=SALE_HISTORY),
        GameSpec(8, tw=SALE_HISTORY),
        GameSpec(9, tw=[("2025-07-01", 30), ("2025-07-10T17:00", 0)]),   # tracked from mid-sale: no covered sale → low
        GameSpec(10, release_date=None, release_state="coming_soon"),   # Steam shows "coming soon", no date
    ]
    build_db(db_path, games, calendar=BASIC_CALENDAR)
    s = PriceStore.open(db_path)
    yield s
    s.close()


def test_statuses_follow_the_decision_order(store):
    batch = run_forecast(store, list(range(1, 10)), AS_OF, Faulty(), now=dt("2026-09-25"))
    status = {g.app_id: (g.status, g.status_reason) for g in batch.games}
    assert status[1][0] == "ok"
    assert status[2][0] == "unsupported-bundle"
    assert status[3] == ("unreleased", "尚未發行（預定 2027-01-01）")
    assert status[4][0] == "free"
    assert status[5][0] == "unverified"
    assert status[6][0] == "no-history"
    assert status[7][0] == "model-error" and "boom" in status[7][1]
    assert status[8][0] == "model-error" and "機率" in status[8][1]
    assert status[9][0] == "ok"
    assert [g.app_id for g in batch.games] == list(range(1, 10))


def test_coming_soon_without_a_date_is_unreleased(store):
    (game,) = run_forecast(store, [10], AS_OF, build_model("seasonal-freq"), now=dt("2026-09-25")).games
    assert (game.status, game.status_reason) == ("unreleased", "尚未發行（發售日未定）")


def test_ok_forecast_content(store):
    batch = run_forecast(store, [1, 9], AS_OF, build_model("seasonal-freq"), now=dt("2026-09-25"))
    good, new = batch.games
    assert good.name == "Good" and good.confidence == "normal"
    assert good.regular_price_cents == 45000                     # TW regular price in effect at as_of
    assert good.points[0].label == "2025 秋特" and good.points[0].status == "estimated"
    assert good.probabilities[0][LEVELS.index(50)] == pytest.approx(2 / 3)   # winter 50, spring 40, summer 60
    assert new.confidence == "low"
    assert batch.data_cutoff <= AS_OF
    assert batch.model.name == "seasonal-freq" and batch.confidence_levels["low"]


def test_forecast_is_deterministic(store):
    a = batch_to_dict(run_forecast(store, list(range(1, 10)), AS_OF, Faulty(), now=dt("2026-09-25")))
    b = batch_to_dict(run_forecast(store, list(range(1, 10)), AS_OF, Faulty(), now=dt("2026-09-26")))
    a.pop("generated_at"), b.pop("generated_at")
    assert a == b
    assert a["summary"]["model_error"] == 2 and a["summary"]["ok"] == 2


# --- feature 003: the no-own-history curve (tasks T005, research R2) --------------------------------------

def test_batch_carries_the_no_history_curve(store):
    model = build_model("seasonal-freq", {"min_sales": 2})
    batch = run_forecast(store, [1, 9], AS_OF, model, now=dt("2026-09-25"))
    nh = batch.no_history
    assert nh is not None and nh.confidence == "low" and nh.reasons
    low = next(g for g in batch.games if g.app_id == 9)            # a low-confidence game uses the same curve
    assert low.confidence == "low"
    assert nh.probabilities == low.probabilities
    assert len(nh.probabilities) == len(batch.games[0].points)


def test_no_history_is_none_when_the_model_fails(store):
    class Broken(Faulty):
        def predict(self, game, points, levels):
            if game.app_id == 0:
                raise RuntimeError("no population")
            return super().predict(game, points, levels)

    batch = run_forecast(store, [1], AS_OF, Broken(), now=dt("2026-09-25"))
    assert batch.no_history is None
    assert batch.games[0].status == "ok"


# --- feature 006: the version decides which history is read (spec FR-007, FR-012) ------------------------------

from tests.forecast_builders import add_history, add_version  # noqa: E402

VERSION_AS_OF = dt("2025-08-01")
NEW_ROWS = [("2024-12-11", 0), ("2024-12-19T18:00", 80), ("2025-01-02T18:00", 0), ("2025-03-13T17:00", 85),
            ("2025-03-20T17:00", 0), ("2025-06-26T17:00", 90), ("2025-07-10T17:00", 0)]


@pytest.fixture
def two_products(db_path):
    build_db(db_path, [GameSpec(1, tw=SALE_HISTORY, us=SALE_HISTORY, name="Dying Light", wishlist=True)],
             calendar=BASIC_CALENDAR)
    add_history(db_path, 1, "itad-new", tw=NEW_ROWS, us=NEW_ROWS, regular_cents=67000, fetched="2025-07-31")
    return db_path


def forecast(db_path, apps=(1,)):
    s = PriceStore.open(db_path)
    try:
        return run_forecast(s, list(apps), VERSION_AS_OF, build_model("seasonal-freq"), now=VERSION_AS_OF)
    finally:
        s.close()


def test_without_a_version_row_the_apps_own_history_is_used(two_products):
    add_version(two_products, 999, "2025-07-31", external_id="itad-999")      # versions exist, just not for app 1
    game = forecast(two_products).games[0]
    assert game.regular_price_cents == 45000 and game.evidence["max_cut"] == 60   # SALE_HISTORY ends at 45000
    assert (game.version.basis, game.version.basis_reason, game.version.itad_id) == ("own", "no-record", "itad-1")


def test_a_verified_version_switches_every_region_to_its_history(two_products):
    add_version(two_products, 1, "2025-07-31", external_id="itad-new", package_id=1345940,
                package_name="Dying Light Essentials Edition", regular_cents=67000)
    game = forecast(two_products).games[0]
    assert game.regular_price_cents == 67000 and game.evidence["max_cut"] == 90
    v = game.version
    assert (v.basis, v.package_id, v.package_name, v.itad_id) == ("version", 1345940, "Dying Light Essentials Edition",
                                                                  "itad-new")
    assert v.history_start == dt("2024-12-11") and v.known_until == dt("2025-07-31")
    assert v.tracking == "ok"


def test_version_is_in_the_forecast_output(two_products):
    add_version(two_products, 1, "2025-07-31", external_id="itad-new", package_name="Essentials")
    data = batch_to_dict(forecast(two_products))
    version = data["games"][0]["version"]
    assert version["basis"] == "version" and version["itad_id"] == "itad-new"
    assert version["history_start"] == "2024-12-11T00:00:00Z" and version["known_until"] == "2025-07-31T00:00:00Z"


def test_a_rejected_version_is_unverified_even_when_the_own_mapping_is_fine(two_products):
    add_version(two_products, 1, "2025-07-31", external_id="itad-bad", verification="rejected",
                reason_code="bundle", reason_detail="bundle/99003", package_name="範例分季作品")
    game = forecast(two_products).games[0]
    assert game.status == "unverified" and "bundle/99003" in game.status_reason
    assert game.version.basis == "rejected"


# --- feature 006 US3: reasons when the version cannot be used (spec FR-011, FR-014) -----------------------------

@pytest.mark.parametrize("code,detail,expected", [
    ("bundle", "bundle/99003", "ITAD 把 Steam 目前的購買選項（範例分季作品）和組合包 bundle/99003 算成同一個商品，"
                               "價格歷史混了不同商品的價格，無法使用"),
    ("other-games", "534380", "Steam 目前的購買選項（範例分季作品）還包含其他遊戲（534380），不是這款遊戲本身"),
    ("price-mismatch", "sub/1265945", "ITAD 的商品同時對應到價格不同的購買選項（sub/1265945），價格歷史可能混了不同版本"),
])
def test_rejection_reasons(two_products, code, detail, expected):
    add_version(two_products, 1, "2025-07-31", external_id="itad-bad", verification="rejected", reason_code=code,
                reason_detail=detail, package_name="範例分季作品")
    game = forecast(two_products).games[0]
    assert (game.status, game.status_reason) == ("unverified", expected)
    assert (game.version.reason_code, game.version.reason_detail) == (code, detail)


def test_no_version_object_before_the_feature_has_recorded_anything(two_products):
    assert forecast(two_products).games[0].version is None


def test_a_missed_day_keeps_the_last_version_and_its_check_time(two_products):
    add_version(two_products, 1, "2025-07-30", external_id="itad-new", package_name="Essentials")
    game = forecast(two_products).games[0]          # no row on 2025-07-31 (source error that day)
    assert game.version.basis == "version" and game.version.checked_at == dt("2025-07-30")


# --- feature 006 US2: ITAD stopped tracking (spec FR-009, FR-010) -------------------------------------------------

STUCK = [("2024-12-11", 0), ("2024-12-19T18:00", 80), ("2025-01-02T18:00", 0), ("2025-01-27", 70)]   # Dying Light


@pytest.fixture
def stuck(db_path):
    build_db(db_path, [GameSpec(1, tw=STUCK, name="Dying Light", wishlist=True, known_until={"TW": "2025-07-31"})],
             calendar=BASIC_CALENDAR)
    return db_path


def test_a_stuck_history_counts_later_sales_as_known_until_tracking_stops(stuck):
    add_version(stuck, 999, "2025-07-31", external_id="itad-999")
    before = forecast(stuck).games[0]
    assert before.evidence["sales_used"] >= 3                      # spring and summer 2025 read as -70%
    add_version(stuck, 1, "2025-07-31", external_id="itad-1", itad_steam_deals=0)
    after = forecast(stuck).games[0]
    assert after.evidence["sales_used"] == 1                        # only the 2024 winter sale is known
    v = after.version
    assert (v.tracking, v.last_confirmed, v.known_until) == ("stopped", dt("2025-01-27"), dt("2025-01-27"))


def test_version_change_is_in_the_output(two_products):
    add_version(two_products, 1, "2025-07-31", external_id="itad-new", package_name="Essentials")
    change = forecast(two_products).games[0].version.change
    assert (change.from_itad_id, change.from_title, change.to_title, change.detected_at) == (
        "itad-1", "Dying Light", "Essentials", dt("2025-07-31"))


# --- feature 009: a chosen edition feeds only its own game (spec FR-010, FR-012) ------------------------------

def _population_db(db_path):
    """Game 1 (default: -50% every sale) has an edition going -30%, -60%, -90%; games 2-6 are the population."""
    from tests.forecast_builders import add_history
    cuts = [("2024-12-11", 0), ("2024-12-19T18:00", 50), ("2025-01-02T18:00", 0), ("2025-03-13T17:00", 50),
            ("2025-03-20T17:00", 0), ("2025-06-26T17:00", 50), ("2025-07-10T17:00", 0)]
    deeper = iter((30, 60, 90))                  # a new low at every sale: moves the population's new-low rate
    deep = [(t, next(deeper) if c else 0, 90000) for t, c in cuts]
    games = [GameSpec(1, tw=cuts, us=cuts, name="Chosen", wishlist=True)]
    games += [GameSpec(a, tw=cuts, us=cuts, name=f"Other {a}", wishlist=a == 2) for a in range(2, 7)]
    build_db(db_path, games, calendar=BASIC_CALENDAR)
    add_history(db_path, 1, "itad-edition", tw=deep, us=[(t, c) for t, c, _ in deep], regular_cents=90000,
                fetched="2025-07-31", source="itad-option-history", fetch_source="itad-option")


def _targets(store):
    from sweetspot.forecast.engine import load_games
    from sweetspot.store.query import OPTION_HISTORY_SOURCE, HistoryKey
    return load_games(store, [1], AS_OF, keys={1: HistoryKey("itad-edition", "user")}, sources=(OPTION_HISTORY_SOURCE,))


def test_the_chosen_game_reads_only_its_edition(db_path):
    from sweetspot.forecast.engine import all_apps, load_games
    _population_db(db_path)
    store = PriceStore.open(db_path)
    model = build_model("seasonal-record")
    games = load_games(store, all_apps(store), AS_OF)
    base = {f.app_id: f for f in run_forecast(store, [1, 2], AS_OF, model, games=games).games}
    chosen = {f.app_id: f for f in run_forecast(store, [1, 2], AS_OF, build_model("seasonal-record"), games=games,
                                                  targets=_targets(store)).games}
    assert chosen[1].regular_price_cents == 90000 and base[1].regular_price_cents == 50000
    assert chosen[1].probabilities != base[1].probabilities
    assert chosen[2] == base[2]                                   # the population still reads the default
    store.close()


def test_putting_the_edition_into_the_population_would_change_other_games(db_path):
    """Proves the previous test can fail: swapping game 1's series inside `games` moves game 2's forecast."""
    from sweetspot.forecast.engine import all_apps, load_games
    _population_db(db_path)
    store = PriceStore.open(db_path)
    games = load_games(store, all_apps(store), AS_OF)
    base = {f.app_id: f for f in run_forecast(store, [2], AS_OF, build_model("seasonal-record"), games=games).games}
    leaked = {**games, **_targets(store)}
    moved = {f.app_id: f for f in run_forecast(store, [2], AS_OF, build_model("seasonal-record"), games=leaked).games}
    assert moved[2].probabilities != base[2].probabilities
    store.close()
