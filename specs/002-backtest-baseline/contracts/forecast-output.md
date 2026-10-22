# Contract: 預測輸出 `steamsage.forecast/1`

分析核心的對外輸出（憲章 VII）。feature 003 的報告與未來的 Chrome 擴充功能都只讀這份資料，不得自行重算。
欄位改變時遞增契約版本（`/2`），新增選用欄位不算改變。

```json
{
  "schema": "steamsage.forecast/1",
  "model": {"name": "seasonal-freq", "version": "1.0.0", "params": {"min_sales": 1, "history": "TW"}},
  "as_of": "2026-09-25T00:00:00Z",
  "data_cutoff": "2026-09-24T17:26:00Z",
  "generated_at": "2026-09-25T03:10:00Z",
  "levels": [5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95],
  "confidence_levels": {
    "normal": "本身至少有 N 場已結束的季節特賣資料，用本身的經驗頻率",
    "low": "本身已結束的季節特賣少於 N 場，改用參考資料集的整體比例"
  },
  "games": [
    {
      "app_id": 1145360,
      "name": "Hades",
      "status": "ok",
      "status_reason": null,
      "confidence": "normal",
      "regular_price_cents": 42000,
      "reasons": ["台灣區過去 7 場季節特賣中，5 場達到 -50% 以上、2 場達到 -60% 以上"],
      "evidence": {"regions": ["TW"], "sales_used": 7, "first_sale": "2024 冬特", "last_sale": "2026 夏特",
                   "population_sales": null},
      "curve": {
        "points": [
          {"index": 1, "label": "2026 秋特", "season": "autumn", "year": 2026,
           "start": "2026-09-29T17:00:00Z", "end": "2026-10-06T17:00:00Z", "status": "announced", "basis": null},
          {"index": 2, "label": "2026 冬特", "season": "winter", "year": 2026,
           "start": "2026-12-17T18:00:00Z", "end": "2027-01-04T18:00:00Z", "status": "announced", "basis": null}
        ],
        "probabilities": [[1.0, 1.0, "…每個 level 一個值…"], ["…每個 point 一列…"]]
      }
    },
    {"app_id": 2000000, "name": "…", "status": "unreleased", "status_reason": "預定 2027-03 發售",
     "confidence": null, "regular_price_cents": null, "reasons": [], "evidence": {}, "curve": null}
  ],
  "summary": {"ok": 64, "low_confidence": 3, "unreleased": 2, "free": 0, "no_history": 1, "model_error": 0}
}
```

## 保證事項（以 contract tests 驗證）

1. `probabilities[i][j]` 是 `points[i]` 結束以前、分析時點之後，至少出現一次折扣 ≥ `levels[j]` 的機率，範圍 0–1。
2. 同一個 j，隨 i 不遞減；同一個 i，隨 j 不遞增（FR-004）。
3. `points` 只包含分析時點之後才開始的季節特賣，依時間排序，到分析時點 + 60 個月為止。
4. `status = "ok"` 時，`confidence`、`reasons`、`curve` 一定存在；其他狀態時，`curve` 為 null，`status_reason` 一定存在。
5. 不包含任何美國區的金額。`regular_price_cents` 只來自台灣區，未知時為 null（不是 0）。
6. 同一個模型版本、同一個分析時點、同一份資料，輸出（`generated_at` 除外）完全相同。
7. `model`、`as_of`、`data_cutoff` 一定存在（憲章 II、V）。
8. 價格以分為單位的整數。台幣價格 = `regular_price_cents` × (100 − level) / 100。
   這個換算由 feature 003 的決策核心負責，並註明「以分析時點的原價換算」；呈現層不得自行計算（憲章 VII）。
   （2026-10-22 稽核補記：「註明以分析時點的原價換算」從來沒有實作。決策的原因清單只在原價和價格歷史不一致時提到原價（「…以目前原價換算，決策改為低信心」）。使用者 2026-10-22 同意維持程式，只在文件註記。）

## 選用欄位 `no_history`（feature 003 新增，契約版本不變）

最上層可以有 `no_history`：「沒有任何本身歷史時」現行模型給出的曲線，時點與整批相同。
格式為 `{"confidence": "low", "reasons": [...], "probabilities": [[...]]}`；沒有未來時點或模型出錯時為 null。
feature 003 的決策核心在一款遊戲的本身曲線得不到任何折扣（P_min 為 0）時使用它
（見 [003 research R2](../../003-sweet-price-report/research.md)）。上面 8 條保證事項不變。
