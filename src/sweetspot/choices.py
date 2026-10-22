"""Which purchase option a user's choice resolves to (feature 009, research R4). Shared by the daily update summary
and the forecast core, so both give the same answer for the same purchase-option records.

A record is anything with `kind`, `option_id`, `name`, `role`, `external_id`, `verification`, `reason_code` and
`reason_detail` (a new purchase_options row or one read back from the store).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

REJECTION_TEXT = {
    "bundle": "ITAD 的商品還對應到組合包 {detail}，價格歷史可能混了組合包的價格",
    "other-games": "ITAD 的商品還包含其他遊戲（{detail}）",
    "price-mismatch": "ITAD 的商品同時對應到價格不同的購買選項（{detail}）",
    "different-product": "ITAD 的商品是另一個產品（{detail}）",
    "package-mismatch": "ITAD 的商品對應到查不到內容、卻仍在販售的套件（{detail}）",
    "not-found": "ITAD 查不到這個商品的別名",
}


def rejection_text(code: str | None, detail: str | None) -> str:
    """A person-readable reason for a failed 006/009 verification."""
    text = REJECTION_TEXT.get(code or "", f"{code or ''} {{detail}}".strip())
    return text.format(detail=detail or "").replace("（）", "").strip()


ROLE_TEXT = {"other-games": "還包含其他遊戲", "without-app": "不含這款遊戲本身", "unknown": "查不到內容"}

FALLBACK_TEXT = {
    "not-offered": "指定的版本（{requested}）目前不在購買選項中，改用 Steam 預設版本",
    "not-edition": "指定的購買選項（{requested}）不是這款遊戲的版本（{detail}），改用 Steam 預設版本",
    "not-in-itad": "指定的版本（{requested}）在 ITAD 沒有對應的商品，沒有價格歷史，改用 Steam 預設版本",
    "rejected": "指定的版本（{requested}）在 ITAD 的商品核對未通過（{detail}），改用 Steam 預設版本",
    "no-record": "這個時點還沒有購買選項紀錄，使用 Steam 預設版本",
}


@dataclass(frozen=True)
class ChoiceResult:
    active: bool
    record: Any | None = None           # the chosen option's record when it is among the records
    code: str | None = None             # fallback code (research R4)
    detail: str | None = None

    def fallback_text(self, requested: str) -> str | None:
        if self.active:
            return None
        return FALLBACK_TEXT[self.code].format(requested=requested, detail=self.detail or "").replace("（）", "")


def option_ref(kind: str, option_id: int) -> str:
    return f"{kind}/{option_id}"


def resolve_choice(records: Sequence[Any] | None, choice: tuple[str, int]) -> ChoiceResult:
    """`records` is one app's latest purchase-option records (None: nothing recorded yet)."""
    if records is None:
        return ChoiceResult(False, code="no-record")
    kind, option_id = choice
    record = next((r for r in records if r.kind == kind and r.option_id == option_id), None)
    if record is None:
        return ChoiceResult(False, code="not-offered")
    if record.role == "default":
        return ChoiceResult(True, record)           # the Steam default itself: 006 verified it
    if record.role != "edition":
        return ChoiceResult(False, record, "not-edition", ROLE_TEXT.get(record.role, record.role))
    if record.external_id is None:
        return ChoiceResult(False, record, "not-in-itad")
    if record.verification != "verified":
        return ChoiceResult(False, record, "rejected", rejection_text(record.reason_code, record.reason_detail))
    return ChoiceResult(True, record)


def requested_label(records: Sequence[Any] | None, choice: tuple[str, int]) -> str:
    """How a choice is named in texts: the option's name when it is known, else sub/N or bundle/N."""
    ref = option_ref(*choice)
    record = next((r for r in records or () if (r.kind, r.option_id) == choice), None)
    return f"{record.name}，{ref}" if record is not None and record.name else ref


TRACKED_STATES = frozenset({"in_wishlist", "removed_tracking"})   # 009 FR-008: the daily update's tracking scope


def ignored_warning(app_id: int) -> str:
    """A choice for an app outside the tracked wishlist (spec FR-008, contracts/cli-and-report.md)."""
    return f"purchase_options.{app_id}：不在願望清單的追蹤範圍，已忽略"
