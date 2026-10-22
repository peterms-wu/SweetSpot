# Data Model: 能預測更深折扣的模型（feature 004）

本 feature 不改資料庫。以下是程式中的結構，以及版本化輸出的新增欄位。沿用 002、003 的實體（GameEvidence、PopulationView、
SalePoint、Forecast、RuleResult、Decision），只列出新增或改變的部分。

## SeasonalRecord（模型，`seasonal-record` v1.0.0）

| 欄位 | 型別 | 說明 |
|---|---|---|
| `name`、`version` | str | `seasonal-record`、`1.0.0` |
| `min_sales` | int ≥ 1 | 本身少於這麼多場時改用整體比例（信心 low） |
| `half_life` | float ≥ 0（場） | 近期加權；0 = 不加權 |
| `hazard_history` | `TW` 或 `TW+US` | 台灣區目標的創新低機率表是否加入美國區紀錄；`tw_only_params` |
| `predicts_deeper` | bool = True | R9 |
| `deeper_caveat` | str 範本 | R9，可引用 `{now_deeper_within_12m}` |

**驗證**：`min_sales` 是 ≥ 1 的整數；`half_life` ≥ 0；`hazard_history` 是兩者之一；未知參數拒絕（沿用 `from_params`）。

## RecordState（每款遊戲在分析時點的狀態）

| 欄位 | 說明 |
|---|---|
| `max_cut` | 本身已結束季節特賣的最深折扣（原值，放進 evidence） |
| `m5` | `max_cut` 取到 5 的倍數，狀態鏈用 |
| `record_sale` | 首次達到 `m5` 的那場特賣（標籤，例如「2026 夏特」） |
| `since_record` | 那之後又過了幾場，上限 4（4 表示 4 場以上） |
| `weights` | 各場的近期權重（`half_life`） |

## HazardTable（每次 `prepare()` 建立，只含分析時點以前已結束的特賣）

| 欄位 | 說明 |
|---|---|
| `cells[(m_group, s_group)]` | 樣本數、創新低次數、平滑後的機率 h |
| `m_rates[m_group]`、`overall` | M 組與全體的比例，供平滑用 |
| `m_groups` | 淺於 -50%、-50% 到 -70%、-75% 到 -85%、-90% 以上 |
| `s_groups` | 0、1、2–3、4 以上 |
| `jumps[m_group]` | 創新低時加深 1–5 級的比例；少於 20 次時改用全體 |
| `regions` | 樣本的區域（`TW`，或 `TW`、`US`） |
| `sales` | 全部樣本數 |
| `tables[k][(M, s, d)]` | 倒推表：從狀態 (M, s) 開始，k 場之後最深折扣 ≥ d 的機率 |

**規則**：

- 加法平滑，a = 20（research R1）：
  - `overall` = 創新低次數 / 場數；沒有樣本時為 0。
  - `m_rate` = (M 組次數 + a × `overall`) / (M 組場數 + a)。
  - h = (格子次數 + a × `m_rate`) / (格子場數 + a)。
- 全體沒有任何樣本時 h = 0，`hazard_basis = "none"`。
- `m5 = 95` 時 h = 0，因為沒有更深的等級。

## ModelOutput.evidence（`steamsage.forecast/1` 的 `evidence`，新增鍵）

`evidence` 在 002 的契約中是自由格式的物件，所以新增鍵不改契約版本。

| 鍵 | 說明 |
|---|---|
| `record_sale` | 首次達到目前最深折扣的特賣標籤 |
| `since_record` | 距上次創新低幾場（上限 4） |
| `hazard` | 下一場的創新低機率 |
| `hazard_basis` | `{cell_sales, cell_records, m_group_sales, overall_sales}`；全體沒有樣本時為 `"none"` |
| `recent_direction` | 最近 4 場（不足 4 場時用全部）第一場到最後一場的方向：`deeper`、`flat`、`shallower`；只有 1 場時為 null |
| `hazard_regions` | 創新低機率表的樣本區域 |
| `half_life` | 近期加權的半衰期 |

沿用的鍵：`regions`、`sales_used`、`first_sale`、`last_sale`、`max_cut`、`population_sales`。

## Split（回測資料集的切分）

| 欄位 | 說明 |
|---|---|
| `split` | `all`、`tuning` 或 `validation` |
| `salt` | 固定為 `steamsage-004-split` |
| `part(app_id)` | SHA-256(`{salt}:{app_id}`) 前 8 個十六進位字元的整數，偶數為 `tuning`，奇數為 `validation` |

`RegionDataset` 新增：

- `population_apps`：全部合格遊戲，用來算整體比例與創新低機率表。
- `apps`：計分的遊戲，也就是切分後的那一組。

`split = all` 時兩者相同，識別碼和 002 相同。

## 回測結果新增的分組（`steamsage.backtest/1`，新增欄位）

| 欄位 | 說明 |
|---|---|
| `dataset.split` | 切分與鹽 |
| `regions[R].deeper_than_past` | `{brier, games, units, calibration}`（R2） |
| `regions[R].by_own_sales` | 依分析時點本身已結束的季節特賣場數分組（0、1、2、3 以上）的 Brier（R11 第 5 點） |

## RuleVersion（規則版本）

| 版本 | `P_MIN_MONTHS` | 說明 |
|---|---|---|
| 1.0.0 | 一般信心看全部時點（最多 60 個月）；低信心 12 個月 | 003；只供並列比較 |
| **2.0.0** | 12（一般信心與低信心相同） | 004 現行規則 |

其他常數（50%、50%、24 小時）與使用者偏好不變。`decide()` 多一個 `rule` 參數，預設現行版本。

## RuleBacktestFigures（原 `RULE_BACKTEST`，改成對照表）

以 `(rule_version, model_name, model_version, params)` 為鍵，值和 003 相同：`date`、`region`、`window_months`、`hit_rate`、
`now_deeper_within_12m`、`source`。找不到現行組合時，決策契約的 `rule_backtest` 為 null，報告不引用任何準確率。

## 規則回測結果新增欄位（`steamsage.rule-backtest/1`，新增欄位）

| 欄位 | 說明 |
|---|---|
| `dataset.split` | 切分 |
| `sweet_timing` | `{next, within_1y, beyond_1y}` 的次數 |
| `follow_advice` | 依分組、信心與全體彙總：`evaluated`、`censored`、`saving_twd {mean, median, p75, p90}`、`wait_days {mean, median}` |
| `hindsight` | 同樣的決策，12 個月內事後最低價與現價的差距 `{mean, median}` |

## DecisionBatch.notes（`steamsage.decision/1`，新增選用欄位）

`notes`：字串清單，由決策核心產生。內容是現行模型的 `deeper_caveat`，已填入 RuleBacktestFigures 的數字；
沒有對應的數字時，改為「規則尚未以現行模型回測」。報告頁首顯示 `notes`，取代原本寫死的那句提示。

（2026-10-22 稽核補記：實際上需要數字的提示（`seasonal-record`）在沒有回測數字時直接省略，`notes` 不放替代句，例如 `notes = []`；
「甜蜜價規則尚未以現行模型與規則回測：本報告不引用任何準確率。」是報告在 `rule_backtest` 為 null 時自己寫的。
`src/sweetspot/decision/engine.py` 的 `model_notes`、`src/sweetspot/report/html.py` 的 `_backtest_note`；
`tests/integration/test_decision_engine.py` 的 `test_notes_and_figures_follow_the_model_and_rule`。）

## 比較文件的新紀錄類型（`docs/model/comparisons.md`，只附加）

| 類型 | 標題 | 內容 |
|---|---|---|
| 調參組網格 | `## 日期 · 模型 調參組網格` | 每個設定的兩區 Brier、差距、區間、是否排除、選中的設定 |
| 驗證組比較 | `## 日期 · 候選 vs 現行（驗證組 · 第 N 次）` | 002 的比較表，加上「更深」分組的 Brier、這次改了什麼 |
| 規則回測並列 | `## 日期 · 規則回測並列：A vs B` | R6 的指標與差距、願望清單差異 |
| 使用者的決定 | 附在並列紀錄之後 | 換或不換、日期 |

## 狀態轉換：現行模型與規則

```text
seasonal-freq 1.0.0 + sweet-price 1.0.0   （目前）
        │ 調參組網格 → 選參數（FR-011）
        │ 驗證組比較 第 1–3 次（FR-012、FR-013）
        ├─ 3 次都「未優於」→ 不變，本 feature 以「未優於」結束
        │ 「優於」→ 規則回測並列（FR-016–FR-021）→ 使用者決定
        ├─ 不換 → 不變
        └─ 換 → seasonal-record 1.0.0 + sweet-price 2.0.0（CURRENT_MODEL、CURRENT_RULE）
                 → 完整資料集重跑 backtest-rule → 更新 RuleBacktestFigures 與模型定義（FR-024）
```

規則 2.0.0 是使用者在 plan 階段確認的（R5），和模型一起換上；它本身不能讓未通過 FR-029 的模型換上（spec FR-023）。
