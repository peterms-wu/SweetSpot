"""The non-seasonal part of a decision (feature 007 spec FR-013, FR-014, FR-016; tasks T023)."""

from dataclasses import replace
from datetime import timedelta

import pytest

from sweetspot.decision.nonseasonal import attach, batch_block, earlier
from sweetspot.forecast.nonseasonal.evidence import NSBasis
from sweetspot.forecast.nonseasonal.model import NSOutput
from tests.decision_builders import AS_OF, decision, points
from tests.forecast_builders import dt

LEVELS = tuple(range(5, 100, 5))
FIGURES = {"earlier_hit_rate": 0.736, "earlier_threshold": 0.5, "brier": 0.1213}
BASIS = NSBasis(dt("2025-06-26"), "TW+US", 456, 6, 58, 50, dt("2026-08-10T02:00"), 50, 46, False)
DAY = timedelta(days=1)


def output(p30=0.35, p60=0.72, p90=0.81, confidence="normal", basis=BASIS, sources=("own",) * 3):
    rows = tuple(tuple(p if d <= 50 else p / 4 for d in LEVELS) for p in (p30, p60, p90))
    return NSOutput(rows, confidence, sources, basis)


def soon_in(days, group="soon", sweet_pct=50):
    """A decision whose sweet sale starts `days` after AS_OF."""
    d = decision(1, group, sweet_pct=sweet_pct, current=20000 if group == "now" else 50000)
    point = replace(d.sweet_point, start=AS_OF + days * DAY, end=AS_OF + (days + 7) * DAY)
    return replace(d, sweet_point=point)


@pytest.mark.parametrize("days, horizon", [(29, None), (30, 30), (45, 30), (75, 60), (90, 90), (120, 90)])
def test_the_judging_horizon_ends_before_the_sweet_sale(days, horizon):
    e = earlier(soon_in(days), output(0.9, 0.9, 0.9), AS_OF, FIGURES)
    assert (e["horizon_days"] if e else None) == horizon


def test_earlier_conditions():
    assert earlier(soon_in(75), output(p60=0.5), AS_OF, FIGURES)["probability"] == 0.5        # the threshold counts
    assert earlier(soon_in(75), output(p60=0.49), AS_OF, FIGURES) is None
    assert earlier(soon_in(75, "now"), output(0.9, 0.9, 0.9), AS_OF, FIGURES) is None
    assert earlier(soon_in(75), output(0.9, 0.9, 0.9, confidence="low"), AS_OF, FIGURES) is None
    for group in ("soon", "wait", "low"):
        assert earlier(soon_in(75, group), output(0.9, 0.9, 0.9), AS_OF, FIGURES) is not None
    assert earlier(soon_in(75), output(0.9, 0.9, 0.9), AS_OF, None) is None                   # no figure to quote
    e = earlier(soon_in(75), output(p60=0.72), AS_OF, FIGURES)
    assert e == {"horizon_days": 60, "probability": 0.72, "threshold": 0.5, "sale_label": soon_in(75).sweet_point.label,
                 "hit_rate": 0.736}


def test_attach_when_adopted():
    d = soon_in(75)
    new = attach(d, output(), adopted=True, as_of=AS_OF, tw_start=dt("2025-06-26"), figures=FIGURES)
    ns = new.non_seasonal
    assert ns["status"] == "ok" and ns["confidence"] == "normal"
    assert ns["sweet"] == {"30": 0.35, "60": 0.72, "90": 0.81}
    assert len(ns["probabilities"]) == 3 and len(ns["probabilities"][0]) == 19
    assert ns["earlier"]["horizon_days"] == 60 and "earlier-possible" in new.tags
    text = "\n".join(ns["reasons"])
    assert "過去一年季節特賣以外有 6 次促銷，約每 58 天一次，常見 -50%；上一次 2026-08-10（-50%），46 天前" in text
    assert "季節特賣以外降到甜蜜價 NT$250（-50%）以下的機率：30 天內 35%、60 天內 72%、90 天內 81%" in text
    assert f"可能比 {d.sweet_point.label}更早到價：60 天內有 72% 的機率在季節特賣以外降到甜蜜價以下" \
           "（回測中這類說法有 74% 實際到價）" in text
    # everything that existed before is untouched
    assert (new.reasons, new.group, new.sweet_cents, new.sweet_point, new.ladder) == \
           (d.reasons, d.group, d.sweet_cents, d.sweet_point, d.ladder)
    assert new.tags == d.tags + ("earlier-possible",)


def test_attach_before_adoption_shows_only_the_basis():
    new = attach(soon_in(75), output(), adopted=False, as_of=AS_OF, tw_start=dt("2025-06-26"), figures=None)
    ns = new.non_seasonal
    assert ns["status"] == "not-adopted"
    assert ns["sweet"] is None and ns["probabilities"] is None and ns["earlier"] is None
    assert ns["basis"]["promos_365d"] == 6
    assert not any("機率" in r for r in ns["reasons"]) and "earlier-possible" not in new.tags


def test_wording_of_special_cases():
    def reasons(basis, **kw):
        out = output(basis=basis, **{k: v for k, v in kw.items() if k in ("confidence", "sources")})
        return "\n".join(attach(soon_in(75), out, adopted=True, as_of=AS_OF, tw_start=dt("2025-06-26"),
                                figures=FIGURES).non_seasonal["reasons"])
    none = replace(BASIS, promos_365d=0, interval_days=None, common_depth=None, last_start=None, last_depth=None,
                   days_since=None)
    assert "過去一年季節特賣以外沒有促銷" in reasons(none)
    one = replace(BASIS, promos_365d=1, interval_days=None, common_depth=30, last_start=dt("2026-05-02"),
                  last_depth=30, days_since=146)
    assert "過去一年季節特賣以外有 1 次促銷：2026-05-02（-30%）" in reasons(one)
    assert "台灣區的價格歷史從 2025-06-26 開始，之前以美國區同一商品的折扣日期補足" in reasons(BASIS)
    assert "美國區" not in reasons(replace(BASIS, history_source="TW"))
    short = reasons(replace(BASIS, history_source="TW", history_days=80), confidence="low",
                    sources=("own", "population", "population"))
    assert "價格歷史不到 120 天，60 天、90 天的機率改用所有遊戲的整體比例（低信心）" in short
    running = reasons(replace(BASIS, in_promo_now=True, last_start=dt("2026-09-20"), days_since=5))
    assert "目前正在季節特賣以外的促銷（-50%，2026-09-20 開始）；以下機率是這次結束之後再次到價" in running


def test_statuses():
    err = attach(decision(1), "RuntimeError: boom", adopted=True, as_of=AS_OF, tw_start=dt("2025-06-26"),
                 figures=FIGURES).non_seasonal
    assert err["status"] == "model-error" and err["status_reason"] == "RuntimeError: boom"
    assert err["reasons"] == ["非季節預測暫時無法計算：RuntimeError: boom"]
    from sweetspot.decision.contract import na_decision
    na = attach(na_decision(2, "Gone", "no-history", "沒有台灣區的 ITAD 價格歷史"), "沒有台灣區的價格歷史",
                adopted=True, as_of=AS_OF, tw_start=None, figures=FIGURES).non_seasonal
    assert na["status"] == "na" and na["reasons"] == [] and na["basis"] is None


def test_history_stopped_lowers_the_confidence():
    d = replace(soon_in(75), version={"tracking": "stopped"})
    ns = attach(d, output(0.9, 0.9, 0.9), adopted=True, as_of=AS_OF, tw_start=dt("2025-06-26"),
                figures=FIGURES).non_seasonal
    assert ns["confidence"] == "low" and ns["earlier"] is None


def test_batch_block():
    from sweetspot.forecast.nonseasonal import build_ns_model
    model = build_ns_model("non-seasonal")
    block = batch_block(model, adopted=True, figures=FIGURES)
    assert block["adopted"] and block["model"]["name"] == "non-seasonal" and block["threshold"] == 0.5
    assert block["horizons_days"] == [30, 60, 90] and block["backtest"] == FIGURES
    assert set(block["confidence_levels"]) == {"normal", "low"}
    off = batch_block(model, adopted=False, figures=None)
    assert off["adopted"] is False and off["model"] is None and off["backtest"] is None


def test_points_helper_is_consistent():
    assert points(2)[0].index == 1
