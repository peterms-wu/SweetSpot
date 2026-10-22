"""The other editions of each game (feature 009, contracts/outputs-options.md `editions`).

The core builds the list, the display amounts and the config line; presentation layers only show them
(constitution VII). An edition is a purchase option whose contents are the app plus its own DLC (role `edition`);
when the user chose one, the Steam default version joins the list so it can be chosen back.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from sweetspot.choices import option_ref, rejection_text, resolve_choice
from sweetspot.decision.contract import twd
from sweetspot.forecast.contract import iso
from sweetspot.store.query import ITAD_SOURCES, OPTION_HISTORY_SOURCE, HistoryKey, OptionRecord, PriceStore


def _cut(record: OptionRecord) -> int:
    if not record.original_cents or record.final_cents >= record.original_cents:
        return 0
    return round(100 - 100 * record.final_cents / record.original_cents)


def build_editions(store: PriceStore, app_ids: Sequence[int], as_of, keys: Mapping[int, HistoryKey],
                   choices: Mapping[int, tuple[str, int]] | None = None) -> dict[int, list[dict[str, Any]] | None]:
    """app -> its editions other than the tracked one (None when nothing was recorded for the app)."""
    choices = choices or {}
    records = store.purchase_options(app_ids, as_of)
    plan: dict[int, list[tuple[OptionRecord, bool]]] = {}     # (record, is the chosen app's default row)
    lows_wanted: list[tuple[int, str, str]] = []
    for app in app_ids:
        rows = records.get(app)
        if rows is None:
            continue
        choice = choices.get(app)
        chosen = resolve_choice(rows, choice) if choice else None
        tracked = (chosen.record.kind, chosen.record.option_id) if chosen and chosen.active else None
        listed = []
        for r in rows:
            if tracked is not None and (r.kind, r.option_id) == tracked:
                continue
            if r.role == "edition":
                listed.append((r, False))
                if r.external_id and r.verification == "verified":
                    lows_wanted.append((app, r.external_id, OPTION_HISTORY_SOURCE))
            elif r.role == "default" and tracked is not None:
                listed.append((r, True))
                key = keys.get(app)
                if key is not None and key.external_id and key.basis != "rejected":
                    lows_wanted.append((app, key.external_id, ITAD_SOURCES[0]))
        plan[app] = listed
    lows = store.option_lows(lows_wanted, as_of)
    out: dict[int, list[dict[str, Any]] | None] = {app: None for app in app_ids}
    for app, listed in plan.items():
        entries = []
        for r, default_of_choice in listed:
            if default_of_choice:
                key = keys.get(app)
                product = key.external_id if key is not None and key.basis != "rejected" else None
                verification = "rejected" if key is not None and key.basis == "rejected" else "verified"
                reason_code = key.record.reason_code if verification == "rejected" and key.record else None
                reason_detail = key.record.reason_detail if verification == "rejected" and key.record else None
            else:
                product, verification = r.external_id, r.verification
                reason_code, reason_detail = r.reason_code, r.reason_detail
            low = lows.get((app, product)) if product and verification == "verified" else None
            choosable = not default_of_choice and r.verification == "verified"
            entries.append({
                "kind": r.kind, "id": r.option_id, "name": r.name, "is_default": r.is_default,
                "price_cents": r.final_cents, "price_twd": twd(r.final_cents), "regular_cents": r.original_cents,
                "regular_twd": twd(r.original_cents), "cut_pct": _cut(r), "checked_at": iso(r.checked_at),
                "verification": verification, "reason_code": reason_code, "reason_detail": reason_detail,
                "reason_text": rejection_text(reason_code, reason_detail) if verification == "rejected" else None,
                "itad_id": product, "history_start": iso(low.first_at) if low else None,
                "low_cents": low.low_cents if low else None, "low_twd": twd(low.low_cents) if low else None,
                "low_at": iso(low.low_at) if low else None,
                "config_line": f'{app} = "{option_ref(r.kind, r.option_id)}"' if choosable else None,
                "unset_hint": default_of_choice,
            })
        out[app] = entries
    return out
