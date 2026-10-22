# Contract: 預測與決策輸出的版本欄位（feature 006）

延伸 [002 的預測輸出 `steamsage.forecast/1`](../../002-backtest-baseline/contracts/forecast-output.md)
與 [005 的決策輸出 `steamsage.decision/2`](../../005-waiting-cost/contracts/decision-output-v2.md)。

**不升版**：只新增選用欄位與標籤（沿用 003 的契約規則）。舊紀錄沒有這些欄位，讀取與變動比較照常。

實作時的調整（T039，2026-09-26）：

- ITAD 不提供批次的商品名稱，所以不輸出 `itad_title`；顯示用的名稱是 Steam 購買選項的名稱 `package_name`。
- 新增 `own_itad_id`：App 本身 001 對應的商品。報告只在 `itad_id ≠ own_itad_id`（真的換了版本）時顯示「追蹤 …」。
  真實資料中有 18 款套件名稱和 App 名稱不同（語言、Standard Edition），但商品相同。
- 新增 `checked_at`（版本紀錄的時間）、`reason_code`、`reason_detail`。
- 不另設 `version-changed` 標籤：版本更換只出現在變動物件 `change.version`。
- 資料庫還沒有任何版本紀錄時（本 feature 之前的資料），`version` 為 null。

## 預測輸出：每款遊戲新增 `version`

```json
{
  "app_id": 239140, "name": "Dying Light", "status": "ok", "confidence": "normal",
  "regular_price_cents": 67000,
  "version": {
    "basis": "version", "basis_reason": null,
    "package_id": 1345940, "package_name": "Dying Light Essentials Edition",
    "itad_id": "0197ad38-0c21-73fa-bb69-9c7b41676553", "own_itad_id": "018d937e-f022-7110-a507-755f61a998cc",
    "history_start": "2025-06-26T23:26:51Z", "known_until": "2026-09-26T11:12:31Z",
    "tracking": "ok", "last_confirmed": null,
    "change": {"from_itad_id": "018d937e-f022-7110-a507-755f61a998cc", "from_title": "Dying Light",
               "to_itad_id": "0197ad38-0c21-73fa-bb69-9c7b41676553", "to_title": "Dying Light Essentials Edition",
               "detected_at": "2026-09-26T11:12:31Z"},
    "reason_code": null, "reason_detail": null, "checked_at": "2026-09-26T11:12:31Z"
  },
  "…": "…"
}
```

驗證失敗的例子：

```json
{
  "app_id": 9500003, "name": "範例分季作品 - Season 1", "status": "unverified",
  "status_reason": "ITAD 把 Steam 目前的購買選項（範例分季作品）和組合包 bundle/99003 算成同一個商品，價格歷史混了不同商品的價格，無法使用",
  "version": {"basis": "rejected", "reason_code": "bundle", "reason_detail": "bundle/99003",
              "package_id": 9900011, "package_name": "範例分季作品",
              "itad_id": "018d937f-69a7-7354-bfff-7fcc53f11a27", "own_itad_id": "018d97d5-c528-73a8-8851-841b47155f86",
              "history_start": null, "known_until": null, "tracking": null, "last_confirmed": null, "…": "…"}
}
```

## 決策輸出

- `version`：和預測輸出的同一款遊戲**完全相同**（決策核心複製，不重算）。
- 標籤 `history-stopped`：`version.tracking = stopped`。規則 2.1.0 與 3.1.0 會讓決策降為低信心；原因寫出最後確認日期（台北日期）。
- `change`（003 的變動物件）在版本更換時多一個 `version: {"from": "舊名稱", "to": "新名稱", "detected_at": "…"}`；
  前一次紀錄沒有 `version` 時，以 App 本身的商品（`own_itad_id`，名稱用 App 名稱）為舊值；商品相同時沒有這個鍵。
  （2026-10-22 稽核補記：已被 009 的 [contracts/outputs-options.md](../../009-purchase-options/contracts/outputs-options.md)「變動物件」取代）`change.version` 現在多一個 `cause`（`user`、`unset`、`fallback`、`steam`）；
  `cause` 是 `user`、`unset`、`fallback`（因使用者的指定而換）時 `detected_at` 為 null；`steam`（本 feature 的版本更換）取 `version.change.detected_at`（`decision/changes.py`）。

## 保證事項（contract tests，`tests/contract/test_version_contract.py`）

1. 資料庫有版本紀錄時，`status` 不是 `unreleased`、`free`、`unsupported-bundle` 的遊戲，一定有 `version`。
2. `version.basis ∈ {version, own, rejected}`；`basis = own` 時 `basis_reason ∈ {no-record, no-option, ambiguous, not-in-itad}`。
   （2026-10-22 稽核補記：已被 009 的 [contracts/outputs-options.md](../../009-purchase-options/contracts/outputs-options.md) 取代）`basis` 另有 `user`（使用者指定的版本，歷史來自它的 ITAD 商品）；
   `version` 也多了 `source`、`option`、`fallback`、`aux_pending` 四個欄位（`forecast/contract.py`）。
3. `basis = rejected` ⇔ 預測狀態 `unverified`，而且 `status_reason` 寫出 `reason_code` 對應的原因。
4. `tracking = stopped` ⇔ `last_confirmed` 不是 null，而且 `known_until = last_confirmed`。
5. 決策的 `version` 和預測的 `version` 逐欄相同（憲章 VII）。
6. 時間一律 UTC、ISO 8601、`Z` 結尾；`history_start`、`known_until`、`last_confirmed`、`checked_at`、`change.detected_at` ≤ `generated_at`。
7. 讀取沒有 `version` 的舊紀錄（`/1`、`/2`）不出錯；變動比較以 App 本身的商品為舊值。
