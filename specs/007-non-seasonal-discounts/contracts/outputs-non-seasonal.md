# Contract: 決策輸出與正式紀錄的非季節欄位

決策輸出 `steamsage.decision/2` 新增**選用**欄位，契約版本不變（同 006 的 `version`）。
既有欄位的名稱、意義與保證全部不變（spec FR-012、FR-013）。正式紀錄 `data/forecasts/*.json.gz` 就是這份輸出，所以也保存這些欄位（spec FR-015）。

## 批次

```json
"non_seasonal": {
  "adopted": true,
  "model": {"name": "non-seasonal", "version": "1.0.0", "params": {"smoothing": 2, "history": "TW+US", "clock": true}},
  "confidence_levels": {"normal": "…", "low": "…"},
  "horizons_days": [30, 60, 90],
  "threshold": 0.5,
  "backtest": {"date": "2026-09-25", "split": "all", "brier": 0.127, "reference_brier": 0.19,
               "earlier_hit_rate": 0.72, "source": "docs/model/model-definition.md"}
}
```

- 未採用時：`adopted = false`，`model = null`，`backtest = null`，其他照填。
- （2026-10-22 稽核補記）`backtest` 是 `NS_BACKTESTS` 那一筆的完整內容：上例之外還有 `model`、`ns_dataset_id`、`games`、`brier_by_horizon`、`earlier_threshold`、`earlier_said`、`earlier_hit`。
  （2026-10-22，014 T078）多一個 `seasonal_model`（例如 `"seasonal-record 1.1.0"`）：「可能更早到價」的決策用的季節模型。數字改成在現行季節模型上重跑的結果（74.9%），見 docs/model/model-definition.md；以前的紀錄留著當時的 73.6%。
- 整個區塊可能不存在（本 feature 以前的紀錄）。讀取時當作「沒有非季節預測」。

## 每筆決策

```json
"non_seasonal": {
  "status": "ok",
  "status_reason": null,
  "confidence": "normal",
  "basis": {"history_start": "2025-06-26T…Z", "history_source": "TW+US", "history_days": 457,
            "promos_365d": 6, "interval_days": 58, "common_depth": 50,
            "last_start": "2026-08-10T…Z", "last_depth": 50, "days_since": 47, "in_promo_now": false},
  "sweet": {"30": 0.35, "60": 0.72, "90": 0.81},
  "probabilities": [[…19…], […19…], […19…]],
  "earlier": {"horizon_days": 60, "probability": 0.72, "threshold": 0.5, "sale_label": "2026 冬特",
              "hit_rate": 0.72},
  "reasons": ["過去一年季節特賣以外有 6 次促銷，…", "季節特賣以外降到甜蜜價 NT$…", "可能比 2026 冬特更早到價：…"]
}
```

| `status` | 意義 | `sweet` / `probabilities` / `earlier` |
|---|---|---|
| `ok` | 模型已採用並成功預測 | 有值（`earlier` 依條件） |
| `not-adopted` | 未採用，只有依據（spec FR-016） | null |
| `model-error` | 這一款的模型出錯（憲章 III），`status_reason` 附原因 | null |
| `na` | 遊戲本身無法預測（決策 group = na） | null；`basis` 也可以是 null |

**保證**（輸出前檢查，有測試）：

1. `status = ok` ⇒ `probabilities` 是 3 × 19，符合 [ns-model-api](ns-model-api.md) 的保證；
   `sweet[h]` = `probabilities[h][sweet_pct 的位置]`，四捨五入到 6 位。
2. `earlier` 不是 null ⇒ 以下全部成立：
   - `status = ok`，而且 `confidence = normal`
   - 決策的 group ∈ {soon, wait, low}
   - 判斷期間到期時，甜蜜時點那場特賣還沒開始：`as_of + horizon_days ≤ sweet_point.start`
   - 沒有更長的 h 也符合上一條
   - `probability ≥ threshold`
3. 決策的所有既有欄位（group、甜蜜價、甜蜜時點、等待對照表、原因清單）和沒有非季節預測時完全相同，
   唯一的差別是 `tags` 多出 `earlier-possible`（spec SC-005）。非季節的句子放在 `non_seasonal.reasons`，
   報告另起一段「季節特賣以外」顯示（實作 T027–T030 時的調整：原本寫成附加在原因清單最後，改成分開，
   讓既有的原因清單逐字不變）。
4. 價格歷史停止更新（006）時，`confidence = low`，`earlier = null`。
5. 呈現層只讀這些欄位，不重算機率與條件（憲章 VII）。

## 標籤

| 標籤 | 條件 | 報告文字 |
|---|---|---|
| `earlier-possible` | `earlier` 不是 null | 可能提早 |

既有的 `non-seasonal-deeper` 標籤與原因不變。

## 和前一次紀錄的比較（003 FR-021）

- 變動標示只比較既有欄位，不比較 `non_seasonal`。
- 前一次紀錄沒有 `non_seasonal` 時不會出錯，也不標示變動。
- 模型從未採用變成採用時，報告頁首註明「非季節預測模型開始顯示機率（non-seasonal 1.0.0）」，寫法同模型版本改變。
