# Contract: 決策輸出 `steamsage.decision/1`

決策核心的對外輸出（憲章 VII）。HTML 報告與未來的 Chrome 擴充功能只讀這份資料，不得自行計算價格、機率或分組。
每次正式執行都以 gzip 壓縮保存成預測紀錄（`data/forecasts/*.json.gz`，research R6）。
欄位改變時遞增版本（`/2`）；新增選用欄位不算改變。

```json
{
  "schema": "steamsage.decision/1",
  "official": true,
  "as_of": "2026-09-25T05:17:02Z",
  "generated_at": "2026-09-25T05:17:08Z",
  "rule": {"name": "sweet-price", "version": "1.0.0",
           "constants": {"p_min_threshold": 0.5, "timing_threshold": 0.5, "low_confidence_months": 12,
                         "stale_hours": 24}},
  "preferences": {"gap_pp_shallow": 10, "gap_pp_deep": 5, "gap_boundary_pct": 75,
                  "tolerance_min_twd": 30, "tolerance_max_twd": 100, "soon_sales": 1},
  "data_refresh": {"update_exit": 0, "note": null},
  "rule_backtest": {"date": "2026-09-25", "region": "TW", "window_months": 12,
                    "hit_rate": {"soon": 0.95, "wait": 0.88, "low": 0.20},
                    "now_deeper_within_12m": 0.51, "source": "docs/model/model-definition.md"},
  "comparison": {"baseline": {"file": "20260924T161500Z.json.gz", "as_of": "2026-09-24T16:15:00Z"},
                 "version_changes": [], "skipped_records": [], "changed_games": 3},
  "decisions": [
    {
      "app_id": 239140, "name": "Dying Light", "group": "now", "status": "ok", "status_reason": null,
      "confidence": "low", "basis": "own", "horizon_points": 20,
      "regular_cents": 67000, "regular_twd": 670,
      "current": {"price_cents": 13400, "regular_cents": 67000, "cut_pct": 80, "source": "steam-current",
                  "observed_at": "2026-09-25T02:53:00Z", "confirmed_at": "2026-09-25T02:53:00Z", "stale": false,
                  "history_regular_cents": 30000, "regular_mismatch": true},
      "p_min_pct": 80, "p_min_cents": 13400, "p_min_twd": 134,
      "gap_pp": 5, "tolerance_cents": 3350, "tolerance_twd": 34, "tolerance_bound": null,
      "target_cents": 16750, "sweet_pct": 75, "sweet_cents": 16750, "sweet_twd": 168,
      "sweet_point": {"index": 5, "label": "2027 秋特", "start": "…", "end": "…", "status": "estimated"},
      "sweet_probability": 0.537,
      "ladder": [{"index": 1, "label": "2026 秋特", "pct": 70, "twd": 201, "probability": 1.0}, "…"],
      "tags": ["low-confidence", "regular-mismatch", "deeper-possible"],
      "reasons": ["…繁體中文…"],
      "change": {"group": {"from": "wait", "to": "now"}, "sweet_point": null, "sweet_twd": null}
    }
  ],
  "summary": {"now": 16, "soon": 27, "wait": 11, "low": 11, "na": 3, "decision_error": 0, "changed": 3},
  "forecast": {"schema": "steamsage.forecast/1", "…": "完整的預測輸出，含 no_history（research R2）"}
}
```

## 保證事項（以 contract tests 驗證）

1. 每款願望清單遊戲在 `decisions` 中恰好出現一次，`group` 是 `now`、`soon`、`wait`、`low`、`na` 之一（FR-023、SC-002）。
2. `group ≠ na` 時一定有 `sweet_point`、`sweet_cents`、`sweet_twd`、`ladder`、`reasons`；`group = na` 時一定有 `status_reason`。
3. `sweet_pct ≤ p_min_pct`；`sweet_cents ≥ p_min_cents`；`ladder` 最後一列等於甜蜜時點。
4. `group = now` 時，`current.price_cents` 不為 null，而且 `≤ sweet_cents`。
5. 所有 `*_twd` 都等於對應的 `*_cents` 以元四捨五入（0.5 進位）。報告只顯示 `*_twd`。
6. 沒有任何美國區金額（憲章 IX）；`regular_*` 與 `current` 只來自台灣區。
7. `rule`、`preferences`、`as_of`、`forecast.model` 一定存在（憲章 II、V）。
8. 同一份預測、現價、規則版本與偏好，`decisions` 完全相同（FR-011）。`generated_at` 與 `comparison` 除外。
9. `official = false`（以過去時點執行）時，`comparison.baseline` 為 null，每筆 `change` 為 null。
   （2026-10-22 稽核補記：實際上是整個 `comparison` 為 null，不是 `comparison.baseline`；建構時 `official = false` 卻帶了 `comparison` 或 `change` 會丟出錯誤（`decision/contract.py`，`tests/contract/test_decision_contract.py` 鎖住）。正式執行但沒有比較基準時，才是 `comparison.baseline` 為 null。005 起 `report --rule` 的預覽也是 `official = false`。）
10. `forecast` 欄位本身符合 `steamsage.forecast/1` 契約。

## `forecast` 的選用新欄位（`steamsage.forecast/1`，不改版本）

```json
"no_history": {"confidence": "low", "reasons": ["…"], "probabilities": [[…每個 level…], […每個時點…]]}
```

- 意義：「沒有任何本身歷史時」現行模型給出的曲線，時點與整批相同（research R2）。
- 沒有任何未來時點，或模型出錯時，這個欄位為 null。
- 002 的契約保證不變。
