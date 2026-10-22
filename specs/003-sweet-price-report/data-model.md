# Data Model: 甜蜜價決策與 HTML 報告（feature 003）

所有金額以「分」為整數儲存。顯示用的「元」由決策核心四捨五入後放進契約（research R1），呈現層不計算。
時間一律是 UTC 的 ISO 字串；只有「比較基準的日期」用台北時間（UTC+8）判斷（research R6）。

## Preferences（使用者偏好，`steamsage.toml` 的 `[preferences]`）

| 欄位 | 型別 | 預設 | 驗證 |
|---|---|---|---|
| `gap_pp_shallow` | int | 10 | 1–50 |
| `gap_pp_deep` | int | 5 | 1–50 |
| `gap_boundary_pct` | int | 75 | 5–95，5 的倍數 |
| `tolerance_min_twd` | int | 30 | ≥ 0，≤ `tolerance_max_twd` |
| `tolerance_max_twd` | int | 100 | ≥ 1 |
| `soon_sales` | int | 1 | 1–4 |

每份決策契約都記錄當次的值（FR-036）。

## Rule（決策規則，程式常數，改變時遞增版本）

| 欄位 | 值 |
|---|---|
| `name` | `sweet-price` |
| `version` | `1.0.0` |
| `p_min_threshold` | 0.5 |
| `timing_threshold` | 0.5 |
| `low_confidence_months` | 12 |
| `stale_hours` | 24 |

## CurrentPrice（現價，research R3）

| 欄位 | 說明 |
|---|---|
| `price_cents` | 最新一筆台灣區觀測的價格；未知時為 null |
| `regular_cents` | 同一筆的原價；沒有時用預測的原價 |
| `cut_pct` | 同一筆的折扣 |
| `source` | `steam-current`、`itad-history` 或 `legacy-itad` |
| `observed_at` | 該筆觀測的時間 |
| `confirmed_at` | 最新的 steam-current 觀測時間與 ITAD 歷史確認時間中較晚者（≤ 分析時點） |
| `stale` | 分析時點 − `confirmed_at` > 24 小時 |
| `history_regular_cents` | 預測所用 ITAD 序列在分析時點的原價 |
| `regular_mismatch` | `regular_cents` ≠ `history_regular_cents`，且兩者都已知 |

## Decision（每款遊戲一筆）

| 欄位 | 說明 |
|---|---|
| `app_id`、`name` | 來自預測 |
| `group` | `now` \| `soon` \| `wait` \| `low` \| `na` |
| `status` | 預測狀態；決策出錯時為 `decision-error` |
| `status_reason` | `group = na` 時一定有 |
| `confidence` | `normal` \| `low`：決策所用的信心，會因 P_min=0 或原價不一致而變成 low |
| `basis` | `own`（本身曲線）\| `no-history`（改用無本身歷史曲線） |
| `horizon_points` | 用了曲線上的前幾個時點 |
| `regular_cents` / `regular_twd` | 換算用的原價 |
| `current` | CurrentPrice；`group = na` 時可為 null |
| `p_min_pct` / `p_min_cents` / `p_min_twd` | 長期最深折扣與其價格 |
| `gap_pp` | 用了哪一段折扣差距 |
| `tolerance_cents` / `tolerance_twd` | 容許差距 |
| `tolerance_bound` | `null` \| `min` \| `max`：哪個限制生效 |
| `target_cents` | P_min 價 + 容許差距（內部門檻） |
| `sweet_pct` / `sweet_cents` / `sweet_twd` | 目標折扣與甜蜜價 |
| `sweet_point` | 甜蜜時點：`index`、`label`、`start`、`end`、`status`（announced \| estimated） |
| `sweet_probability` | 甜蜜時點的累積到價機率 |
| `ladder` | 等待對照表：每列有 `index`、`label`、`pct`、`twd`、`probability` |
| `tags` | 見下表 |
| `reasons` | 人讀的原因（繁體中文），依序排列 |
| `change` | Change，或 null |

`tags` 的值：

| tag | 條件 |
|---|---|
| `low-confidence` | `confidence = low` |
| `no-history-curve` | `basis = no-history` |
| `regular-mismatch` | 原價不一致（FR-037） |
| `stale-price` | 現價可能已變（FR-014） |
| `price-unknown` | 現價未知 |
| `tolerance-min` / `tolerance-max` | 容許差距下限或上限生效 |
| `below-history` | 現價低於 P_min 價 |
| `deeper-possible` | P_min 等於過去見過的最深折扣（FR-008） |
| `non-seasonal-deeper` | 季節特賣以外出現過更深的折扣（research R4） |

**驗證規則**（建構時檢查，失敗記為 `decision-error`）：

- `group ≠ na` 時，`sweet_point`、`sweet_cents`、`ladder`、`reasons` 都必須存在。
- `sweet_pct ≤ p_min_pct`，而且 `sweet_cents ≥ p_min_cents`。
- `ladder` 的最後一列就是甜蜜時點。
- `group = now` 時，`current.price_cents ≤ sweet_cents`。

## Change（相對比較基準的變動）

| 欄位 | 說明 |
|---|---|
| `group` | `{from, to}` 或 null |
| `sweet_point` | `{from, to}`（時點名稱；現在買為「現在」）或 null |
| `sweet_twd` | `{from, to}` 或 null |

三項都是 null 時，`change` 為 null。比較基準中沒有這款遊戲時也是 null。

## Comparison（整批的比較說明）

| 欄位 | 說明 |
|---|---|
| `baseline` | `{file, as_of}`，或 null（沒有比較基準） |
| `version_changes` | 例如 `["規則 1.0.0 → 1.1.0", "偏好 gap_pp_deep 5 → 10"]` |
| `skipped_records` | 略過的損壞紀錄檔名 |
| `changed_games` | 有任一變動的款數 |

## DecisionBatch（`steamsage.decision/1`，也就是預測紀錄）

見 [contracts/decision-output.md](contracts/decision-output.md)。包含：

- `forecast`：完整的 `steamsage.forecast/1`
- `rule`、`preferences`、`decisions`、`comparison`、`data_refresh`、`rule_backtest`、`summary`
- `official`：是否為正式執行

## RuleBacktestResult（`steamsage.rule-backtest/1`）

見 [contracts/rule-backtest-result.md](contracts/rule-backtest-result.md)。

## 狀態轉換

每款遊戲在每次執行中都獨立決定分組，沒有跨執行的狀態機。「變動」只是本次和比較基準的差異。

預測紀錄的生命週期：

1. 寫入中：`.tmp`，不算紀錄。
2. 改名為 `.json.gz` 後才算正式紀錄。
3. 永不修改或刪除。
