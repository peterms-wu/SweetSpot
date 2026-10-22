# Data Model: 等待成本

> **2026-10-22 稽核補記：規則 3.0.0 沒有採用。** 2026-09-26 的驗證組判定中，`sweet-price` 3.0.0 沒有通過換版的硬門檻
> （spec FR-015：c = 20、每月重新評估，平均淨效益差距 +1.7 [−0.7, +4.2]，區間含 0），使用者決定不換版，以「未優於」結束
> （[validation.md](validation.md) 第 2 節；005 T030–T032 跳過、005 T033）。現行規則是 2.1.0（feature 006；
> `src/sweetspot/decision/rule.py` 的 `CURRENT_RULE`），`CURRENT_RULE` 沒有改成 `"3.0.0"`。3.0.0 與 006 加的 3.1.0
> 只留在程式中，供預覽（`sweetspot report --rule`）與回測（`sweetspot backtest-rule --rule/--wait-cost`、`sweetspot compare-rule`）；
> 偏好 `wait_cost_twd` 只在這些情況使用。

不改資料庫。只有設定、程式內的資料結構與輸出檔案改變。金額一律是整數分（`*_cents`），顯示用的 `*_twd` 以元四捨五入。

## 設定：`Preferences`（`steamsage.toml` 的 `[preferences]`）

| 欄位 | 型別與範圍 | 預設 | 使用的規則 | 性質 |
|---|---|---|---|---|
| `wait_cost_twd` | 整數，0–10,000 | 20 | 3.0.0 | **使用者偏好**（spec FR-001） |
| `soon_sales` | 整數，1–4 | 1 | 2.0.0、3.0.0 | 使用者偏好 |
| `gap_pp_shallow`、`gap_pp_deep`、`gap_boundary_pct`、`tolerance_min_twd`、`tolerance_max_twd` | 同 003 | 同 003 | 只有 2.0.0（並列回測用） | 使用者偏好 |

- `Preferences.for_rule(version) -> dict`：只回傳該規則用到的偏好。決策輸出、規則回測結果與報告都用它（research R5）。
- 驗證失敗時拋出 `ConfigError`，例如「preferences.wait_cost_twd 必須是 0 到 10000 的整數」。

## 規則常數（`decision/rule.py`，寫進模型定義）

| 常數 | 值 | 3.0.0 | 說明 |
|---|---|---|---|
| `p_min_months` | 12 | ✓ | 範圍（同 2.0.0） |
| `timing_threshold` | 0.5 | ✓ | 甜蜜時點：第一次 ≥ 50%（research R3） |
| `p_min_threshold` | 0.5 | ✓ | 只用於參考用的 12 個月內最低價與「P_min 為 0」的路徑判斷 |
| `low_confidence_months` | 12 | ✓ | 同 2.0.0 |
| `stale_hours` | 24 | ✓ | 同 2.0.0 |
| `miss_price` | `"regular"` | ✓ | 到期沒達到時以原價計算（research R2） |
| `month_days` | 365 / 12 | ✓ | 月數換算 |

`RULES["3.0.0"] = {"constants": {…}, "p_min_months": 12, "kind": "wait-cost"}`；`CURRENT_RULE` 只在換版時改成 `"3.0.0"`。

## `WaitOption`（`decision/rule.py`，frozen dataclass）

每一場（最晚時點）的最佳選項，也就是等待對照表的一列。

| 欄位 | 型別 | 說明 |
|---|---|---|
| `deadline_index` | int | 最晚等到第幾場（1 = 下一場）；現在買的那一列為 0 |
| `deadline_label` | str \| None | 例如 "2027 夏特"；現在買為 None |
| `target_pct` | int \| None | 目標折扣；沒有候選等級時為 None |
| `target_cents` | int \| None | price(target_pct) |
| `reach_probability` | float \| None | F_K(target)：到期前達到的機率 |
| `likely_index`、`likely_label` | int、str \| None | 最可能到價的那一場（research R3） |
| `likely_probability` | float \| None | F_T(target) |
| `expected_saving_cents` | int | 期望多省，四捨五入成整數分；可為負 |
| `expected_wait_months` | float | 期望多等的月數 |
| `wait_cost_cents` | int | c × 期望等待，四捨五入成整數分 |
| `net_cents` | int | 期望多省 − 等待成本 |
| `chosen` | bool | 是否為選中的選項 |

**不變式**：

- 現在買的那一列，`net_cents` = `expected_saving_cents` = 0。
- `net_cents` = `expected_saving_cents` − `wait_cost_cents`。
- `reach_probability` 隨 `deadline_index` 不遞減（同一目標時）；`likely_index` ≤ `deadline_index`。
- 恰好一列 `chosen`。

## `RuleResult` 的新增欄位（3.0.0；2.0.0 為 None 或空）

| 欄位 | 型別 | 說明 |
|---|---|---|
| `wait_options` | tuple[WaitOption, ...] | 對照表（research R4） |
| `deadline_index` | int \| None | 選中選項的最晚時點；現在買為 None |
| `expected` | WaitOption \| None | 選中的那一列（現在買時為第 0 列） |
| `wait_cost_twd` | int \| None | 當次的 c |

- 3.0.0 的 `gap_pp`、`tolerance_cents`、`tolerance_bound`、`target_cents` 為 None。
- `sweet_pct`、`sweet_cents`、`sweet_index`（= 甜蜜時點 T）、`sweet_probability`（= F_T）照舊有值。
  - **現在買時**：取淨效益最高的等待選項，也就是原因中「不划算」的那一個，讓報告的甜蜜價欄位有參考值。分組是 now。
  - **沒有任何候選等級時**（現價已經比 -95% 還低）：甜蜜價 = 現價，甜蜜時點 = 下一場，`sweet_probability` 為 None，
    原因寫「沒有比現價更低的折扣等級可以等」。
- `ladder`：同 2.0.0 的定義，列到甜蜜時點。

## 規則回測結果：`FollowScore` 與新的彙總

| 結構 | 欄位 | 說明 |
|---|---|---|
| `FollowScore`（既有） | `saving_cents`、`wait_days`、`censored`、`hindsight_cents` | 固定決策 |
| `MonthlyScore`（新） | `saving_cents`、`wait_days`、`censored`、`steps` | 每月重新評估；`steps` 是換了幾次決策，供診斷 |
| `NetSummary`（新） | `cost_twd`、`mean`、`median`、`p25`、`p75` | 淨效益 = 多省 − c × 天數 ÷ (365/12)，單位 NT$ |
| `CaseRow`（新，寫進結果檔） | `[app_id, as_of, mode, saving_cents, wait_days]` | `mode` 是 `fixed` 或 `monthly`；只列可評估的決策 |

## 規則回測對照：`RULE_BACKTESTS` 的新增鍵

```python
{"rule": "3.0.0", "model": {...}, "wait_cost_twd": 20, "date": "…", "region": "TW", "window_months": 12,
 "hit_rate": {"soon": …, "wait": …, "low": …}, "now_deeper_within_12m": …, "source": "docs/model/model-definition.md"}
```

`lookup_backtest(rule, model, wait_cost_twd)`：規則、模型與參數、c 都要相同。2.0.0 的條目 `wait_cost_twd = None`，查詢時忽略 c。

## 並列結果：`compare_rule_results(base, *candidates)`

| 欄位 | 說明 |
|---|---|
| `rows` | 004 的所有指標，每個候選一欄 |
| `net` | 每個候選 × 模式（`monthly`、`fixed`）：共同評估數、雙方的平均多省、多等、以候選 c 計算的淨效益、差距與 95% 區間 |
| `net_by_cost` | 每個評估成本 × 每份結果的平均淨效益 |
| `verdict` | 只在符合 research R7 的判定條件時為 `pass` 或 `fail`，否則為 None |
| `longer_horizon` | 候選結果中的 FR-017 計數（2026-10-22：使用者決定不做；程式只在 `backtest-rule` 的摘要輸出 `longer_horizon`，`compare-rule` 輸出願望清單的 `longer_24`／`longer_60`） |

## 狀態轉換

規則版本：`2.0.0`（現行）→ 驗證組判定通過且使用者同意 →`3.0.0`。

（2026-10-22 稽核補記：這裡的「現行」是 2026-09-26 當時。3.0.0 沒有通過，維持 2.0.0；之後 006 換成 2.1.0，現行是 2.1.0。）

- 不通過或使用者不同意時維持 2.0.0，3.0.0 仍保留在程式中，可以用 `backtest-rule --rule 3.0.0` 執行。
- 換版時一起改：
  - `CURRENT_RULE`
  - `RULE_BACKTESTS`（新增 3.0.0 那一筆）
  - 模型定義
  - 設定檔範本的註解
