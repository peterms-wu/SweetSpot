"""US5: the record's as_of recomputed with today's database (feature 013 research R7, FR-015, FR-016).

The current model goes through the whole decision path (as the report does, but never official: no record, no
report); the baseline model only forecasts. Both read data with cutoff = as_of, the backtest's leak protection.
"""

from datetime import datetime
from typing import Any

from sweetspot.config import Preferences
from sweetspot.decision.contract import batch_to_dict as decision_to_dict
from sweetspot.decision.engine import run_decisions
from sweetspot.forecast.contract import batch_to_dict as forecast_to_dict
from sweetspot.forecast.engine import run_forecast
from sweetspot.forecast.models import build_model, current_model
from sweetspot.store.query import PriceStore

BASELINE = ("seasonal-freq", {"min_sales": 2, "history": "TW"})


def _preferences(record: dict) -> Preferences:
    known = set(Preferences().as_dict())
    return Preferences(**{k: v for k, v in (record.get("preferences") or {}).items() if k in known})


def recompute(store: PriceStore, record: dict, as_of: datetime) -> dict[str, Any]:
    """{"current": decision contract dict, "baseline": forecast contract dict, "note": str | None}."""
    apps = [d["app_id"] for d in record.get("decisions") or []]
    choices = {d["app_id"]: (d["version"]["option"]["kind"], d["version"]["option"]["id"])
               for d in record.get("decisions") or []
               if (d.get("version") or {}).get("source") == "user" and (d["version"].get("option") or {}).get("kind")}
    model = current_model()
    current = decision_to_dict(run_decisions(store, apps, as_of, model, _preferences(record), now=as_of,
                                             official=False, choices=choices))
    baseline = forecast_to_dict(run_forecast(store, apps, as_of, build_model(*BASELINE), now=as_of))
    recorded = (record.get("forecast") or {}).get("model") or {}
    note = None
    if (recorded.get("name"), recorded.get("version")) != (model.name, model.version):
        note = f"紀錄的模型是 {recorded.get('name')} {recorded.get('version')}，重算用現行的 {model.name} {model.version}"
    return {"current": current, "baseline": baseline, "note": note}
