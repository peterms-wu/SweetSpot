# Contract: 決策輸出 `steamsage.decision/2`（feature 005）

> **2026-10-22 稽核補記：規則 3.0.0 沒有採用。** 2026-09-26 的驗證組判定中，`sweet-price` 3.0.0 沒有通過換版的硬門檻
> （spec FR-015：c = 20、每月重新評估，平均淨效益差距 +1.7 [−0.7, +4.2]，區間含 0），使用者決定不換版
> （[validation.md](../validation.md) 第 2 節；005 T030–T032 跳過、005 T033）。現行規則是 2.1.0（feature 006；
> `src/sweetspot/decision/rule.py` 的 `CURRENT_RULE`）。3.0.0 與 006 加的 3.1.0 只留在程式中，供預覽
> （`sweetspot report --rule`）與回測（`sweetspot backtest-rule --rule/--wait-cost`、`sweetspot compare-rule`）；
> 偏好 `wait_cost_twd` 只在這些情況使用。下文規則 3.0.0 的範例與欄位只出現在這些輸出；`/2` 本身仍是現行的決策輸出格式。

延伸 [003 的 `steamsage.decision/1`](../../003-sweet-price-report/contracts/decision-output.md)
與 [004 的新增欄位](../../004-deeper-discount-model/contracts/results-and-decisions.md)。

**升版原因**：規則 3.0.0 沒有容許差距，容許差距欄位為 null（research R9）。其他既有欄位的名稱與意義不變。

## 範例（規則 3.0.0）

```json
{
  "schema": "steamsage.decision/2",
  "rule": {"name": "sweet-price", "version": "3.0.0",
           "constants": {"p_min_months": 12, "timing_threshold": 0.5, "p_min_threshold": 0.5,
                         "low_confidence_months": 12, "stale_hours": 24, "miss_price": "regular",
                         "month_days": 30.4167}},
  "preferences": {"wait_cost_twd": 20, "soon_sales": 1},
  "rule_backtest": {"rule": "3.0.0", "wait_cost_twd": 20, "hit_rate": {"soon": 0.86, "wait": 0.8, "low": 0.1},
                    "now_deeper_within_12m": 0.4, "model": {"…": "…"}, "…": "…"},
  "notes": ["…"],
  "decisions": [
    {
      "app_id": 1091500, "name": "Cyberpunk 2077", "group": "soon", "status": "ok",
      "confidence": "normal", "basis": "own", "horizon_points": 4,
      "regular_cents": 159900, "regular_twd": 1599, "current": {"price_cents": 159900, "…": "…"},
      "p_min_pct": 70, "p_min_cents": 47970, "p_min_twd": 480,
      "gap_pp": null, "tolerance_cents": null, "tolerance_twd": null, "tolerance_bound": null, "target_cents": null,
      "sweet_pct": 65, "sweet_cents": 55965, "sweet_twd": 560,
      "sweet_point": {"index": 1, "label": "2026 秋特", "…": "…"}, "sweet_probability": 0.93,
      "deadline_point": {"index": 4, "label": "2027 夏特", "…": "…"},
      "expected": {"deadline_index": 4, "target_pct": 65, "target_twd": 560, "reach_probability": 1.0,
                   "likely_index": 1, "likely_label": "2026 秋特", "likely_probability": 0.93,
                   "expected_saving_cents": 103900, "expected_saving_twd": 1039, "expected_wait_months": 0.4,
                   "wait_cost_cents": 800, "wait_cost_twd": 8, "net_cents": 103100, "net_twd": 1031, "chosen": true},
      "wait_options": [
        {"deadline_index": 0, "deadline_label": null, "target_pct": null, "target_twd": 1599,
         "expected_saving_twd": 0, "expected_wait_months": 0.0, "wait_cost_twd": 0, "net_twd": 0, "chosen": false, "…": "…"},
        {"deadline_index": 1, "deadline_label": "2026 秋特", "target_pct": 65, "reach_probability": 0.93, "…": "…"},
        "…"
      ],
      "ladder": ["…同 /1，列到甜蜜時點…"],
      "tags": ["…"], "reasons": ["…"], "change": null
    }
  ]
}
```

`expected` 與 `wait_options` 的每一列都同時有 `*_cents` 與 `*_twd`，範例省略了一部分。

## 保證事項（contract tests）

`/1` 的保證 1、2、4–10 不變，另外：

1. **`schema`**：值是 `steamsage.decision/2`。讀取紀錄時接受 `/1` 與 `/2`；變動比較只用兩邊都有的欄位。
2. **`preferences`**：只包含當次規則用到的偏好。
   - 3.0.0：`wait_cost_twd`、`soon_sales`。
   - 2.0.0：003 的六個偏好。
3. **容許差距欄位**：3.0.0 的 `gap_pp`、`tolerance_*`、`target_cents` 為 null；2.0.0 的值和 `/1` 相同。
4. **只在 3.0.0**：`group ≠ na` 時一定有 `wait_options`、`expected`；`group ≠ now` 時一定有 `deadline_point`。
5. **`wait_options`**：
   - 第一列是現在買（`deadline_index = 0`），淨效益 0；現價未知時沒有這一列。
   - 之後每場一列，列到範圍內的最後一場。
   - 恰好一列 `chosen`，而且等於 `expected`。
6. **選擇的一致性**：
   - `expected.net_cents` 是所有列中最大的；相同時選 `deadline_index` 較小的那一列。
   - `group = now` 若且唯若選中的是第 0 列。
   - `net_cents = expected_saving_cents − wait_cost_cents`。
7. **甜蜜時點與最晚時點**：
   - `group ≠ now` 時：`sweet_point.index = expected.likely_index` ≤ `deadline_point.index`，`sweet_probability = expected.likely_probability`。
   - `group = now` 時：`expected` 是第 0 列。`sweet_*` 取自淨效益最高的等待列 R，`sweet_point.index = R.likely_index`，
     `sweet_probability = R.likely_probability`。
   - 沒有任何等待列有目標等級時：甜蜜價 = 現價，`sweet_point` 為下一場，`sweet_probability` 為 null（data-model.md）。
8. **`sweet_pct ≤ p_min_pct` 只對 2.0.0 保證**。3.0.0 的目標可以比 12 個月內最低價更深，例如低機率、高金額的選項。
9. **現價未知時**：`group ≠ now`；`wait_options` 沒有第 0 列；期望多省以原價為基準；有 `price-unknown` 標籤。
10. **可重現**：同一份預測、現價、規則版本與偏好，`decisions` 完全相同，包括 `wait_options` 的每一個整數分。

## `comparison.version_changes` 的新措辭

| 情況 | 措辭 |
|---|---|
| c 改變 | 「等待成本從 NT$20 改成 NT$30」（spec FR-023） |
| 規則改變 | 「規則 sweet-price 2.0.0 → 3.0.0」（照舊） |
| 其他偏好改變 | 照舊，只比較兩邊都有的鍵 |
