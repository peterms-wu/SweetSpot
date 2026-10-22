# Contract: 規則回測結果的新增欄位（feature 005）

> **2026-10-22 稽核補記：規則 3.0.0 沒有採用。** 2026-09-26 的驗證組判定中，`sweet-price` 3.0.0 沒有通過換版的硬門檻
> （spec FR-015：c = 20、每月重新評估，平均淨效益差距 +1.7 [−0.7, +4.2]，區間含 0），使用者決定不換版
> （[validation.md](../validation.md) 第 2 節；005 T030–T032 跳過、005 T033）。現行規則是 2.1.0（feature 006；
> `src/sweetspot/decision/rule.py` 的 `CURRENT_RULE`）。3.0.0 與 006 加的 3.1.0 只留在程式中，供預覽
> （`sweetspot report --rule`）與回測（`sweetspot backtest-rule --rule/--wait-cost`、`sweetspot compare-rule`）；
> 偏好 `wait_cost_twd` 只在這些情況使用。下文的新增欄位（淨效益、`follow_advice_monthly`、`cases`）所有規則版本都有，
> `longer_horizon` 只在 wait-cost 規則（3.0.0、3.1.0）。

`steamsage.rule-backtest/1` 只**新增**欄位，schema 版本不變；缺少新欄位的舊結果，視為沒有淨效益與逐案資料。
延伸 [003](../../003-sweet-price-report/contracts/rule-backtest-result.md) 與
[004](../../004-deeper-discount-model/contracts/results-and-decisions.md)。

```json
{
  "rule": {"name": "sweet-price", "version": "3.0.0", "constants": {"miss_price": "regular", "…": "…"}},
  "preferences": {"wait_cost_twd": 20, "soon_sales": 1},
  "evaluation_costs_twd": [0, 10, 20, 30, 50, 80],
  "follow_advice": {
    "overall": {"evaluated": 20000, "censored": 2600, "saving_twd": {"…": "…"}, "wait_days": {"…": "…"},
                "net_twd": [{"cost_twd": 0, "mean": 202.1, "median": 110, "p25": 0, "p75": 300}, "…"]},
    "by_group": ["…同上，每組…"], "by_confidence": ["…"]
  },
  "follow_advice_monthly": {"overall": {"…": "同 follow_advice 的格式"}, "by_group": ["…"], "by_confidence": ["…"]},
  "longer_horizon": {"24": {"decisions": 22683, "beyond_12m": 4708, "mean_expected_wait_months": 3.7},
                     "60": {"…": "…"}},
  "cases": [[1091500, "2025-02-01", "monthly", 103900, 12], "…"]
}
```

## 定義

- **`evaluation_costs_twd`**：`[0, 10, 20, 30, 50, 80]`，再加上規則本身的 c（如果不在清單中），由小到大排序。2.0.0 也照樣計算。
- **淨效益**：每次決策的多省（元）− cost × 多等天數 ÷ (365/12)。彙總方式和 `saving_twd` 相同，另外加上 p25。
  （2026-10-22 稽核補記：實際的 `net_twd` 每個 cost 一筆，只有 `mean`、`median`、`p25`、`p75`，沒有 `saving_twd` 的 `p90`；
  百分位四捨五入到小數 2 位，`mean` 不四捨五入。`src/sweetspot/decision/backtest.py` 的 `net_summary`。）
- **`follow_advice_monthly`**：定義見 research R6 第 2 點。截斷規則和 `follow_advice` 相同，只看資料已知時間。
- **`longer_horizon`**：只在 3.0.0 出現。範圍改成 24 個月與 60 個月（其他都不變）時：
  - `beyond_12m`：選中選項的最晚一場結束時間超過 12 個月的決策數。
  - `mean_expected_wait_months`：這些決策的平均期望等待。
- **`cases`**：每次可評估的決策、每種模式一列，依 (app_id, as_of, mode) 排序。截斷的決策不列。

## 保證（測試驗證）

1. 人工價格路徑上，每個 case 的多省、天數與淨效益和手算一致（spec SC-003）。
2. `cases` 的筆數等於兩種模式的 `overall.evaluated` 相加。
3. 同一份資料集、模型、規則與偏好，重跑的結果除了 `run` 以外完全相同。
4. 同一次執行產生的多個 c 結果，預測部分完全相同（每個分析時點只預測一次）。
5. 決策只用分析時點以前的資料；竄改分析時點之後的價格，只會改變計分，不會改變任何決策（research R14）。
