# Data Model: 事後對照

**Feature**: 013-post-sale-comparison | **Date**: 2026-10-12

本 feature 不改資料庫（schema 仍是 v6）、不改預測紀錄與行事曆檔。下面是**記憶體中的結構**與輸出的 JSON（契約見 [contracts/review.md](contracts/review.md)）。

## 1. 對照對象 `ReviewTarget`

| 欄位 | 說明 |
|---|---|
| `sale` | 季節、年份、標籤、實際開始與結束（行事曆，UTC）；`days_since_end` |
| `record` | 檔名、`as_of`、schema、模型與規則版本、`hours_before_start` |
| `during` | 特賣期間的正式紀錄檔名（FR-010a）；缺漏的日期 |
| `today` | 執行對照的時點（非季節的到期判斷用；預設現在） |
| `forced` | 結束不到 3 天仍執行時為 true（FR-002） |

驗證：特賣必須是 `kind = seasonal` 且已結束；紀錄的 `as_of` < 特賣開始、`official = true`。

> 2026-10-22 稽核補記：上面是沒有給 `--record` 時的選法。給 `--record`（spec FR-003「MAY 指定其他紀錄」）時只要求紀錄讀得到、`as_of` 早於特賣**結束**；
> 也接受非正式紀錄，`as_of` 在特賣開始之後時 `hours_before_start` 是負的（review/target.py）。

## 2. 逐款結果 `GameReview`

| 欄位 | 說明 |
|---|---|
| `app_id`、`name` | |
| `status` | `reviewed`／`no-actual`（價格序列沒有涵蓋到特賣結束、沒有序列）／`not-scored`（紀錄中沒有預測：尚未發行、無法預測、決策出錯） |
| `reason` | `status` 不是 `reviewed` 時的原因（例如「價格歷史只到 2026-10-05」） |
| `series` | 讀的商品：`itad_id`、`basis`（`default`／`user`）、`option`（kind、id、名稱）、`known_until` |
| `actual` | `max_cut`（特賣期間最深折扣）、`min_cents`（最低價）、`running_cut_at_as_of`（分析時點正在打的折扣）、`daily_max_cut`、`daily_min_cents`（購買選項的每日紀錄）、`corrected`（D2：依每日紀錄補正時為 true）、`regular_changed` |
| `seasonal` | 這一場的 19 個機率、每個等級的兩種結果（`sale_max`、`crossing`）、信心等級 |
| `decision` | 分組、甜蜜價、甜蜜時點（標籤、季節、年份）、甜蜜時點的機率、紀錄當時的現價；`hit`（最低價 ≤ 甜蜜價）、`gap_cents`（最低價 − 甜蜜價） |
| `timing` | `on-time`（甜蜜時點是這一場）／`early`（之後的時點、這一場就到價）／`not-yet`／`n/a` |
| `switch` | 只對 `early`：`first_now`（第一份判為「現在買」的特賣期間紀錄的 `as_of`）或 `missed`／`unknown`（紀錄缺漏） |
| `now_vs_sale` | 只對「現在買」：`lower`／`same`／`higher` 與金額 |
| `recomputed` | US5：重算的現行模型與基準模型的這一場機率；和紀錄不同的分組、甜蜜價 |

規則：

- 實際價格只讀紀錄當時追蹤的商品（`version.itad_id`；`version.source = user` 時讀 `itad-option-history`）。
- `no-actual` 與 `not-scored` 不進任何分母（FR-006）。
- 特賣期間最深折扣：特賣開始時有效的狀態＋開始到結束之間的狀態（`sale_outcomes`）；再依 D2 和每日紀錄比較。

## 3. 彙總 `ReviewSummary`

每個比例或分數：`value`、`n`（分母；遊戲數或單位數）、`interval`（依遊戲重抽樣 2,000 次的 2.5%／97.5%）、
`backtest`（對應的回測數字與出處章節）、`differs`（回測數字在區間外時為 true）。

| 區塊 | 內容 |
|---|---|
| `seasonal` | Brier（兩種定義）、依信心等級、校準表；並列 `seasonal-record` v1.1.0 的回測數字 |
| `decisions` | 依分組：準時到價率（並列 `rule_backtest.hit_rate`）、提早到價與改口／錯過、現在買 vs 特賣最低價、未到價的差額 |
| `bundles` | 逐個列出（不算比例） |
| `non_seasonal` | 依期間：已計分單位、Brier、尚未到期的單位與最早到期日；`earlier` 的結果 |
| `recompute` | 正式紀錄／重算現行／基準的 Brier 與區間；不同的遊戲 |
| `mismatches` | 依每日紀錄補正的遊戲、價格歷史比每日紀錄深的遊戲（只註記） |

## 4. 非季節單位 `NSUnit`

| 欄位 | 說明 |
|---|---|
| `app_id`、`h`（30／60／90）、`level` | |
| `due` | as_of + h |
| `state` | `scored`／`pending`（today < due，或價格歷史還沒到 due）／`no-actual` |
| `p`、`arrived` | 只對 `scored` |

## 5. 組合包結果 `BundleReview`

| 欄位 | 說明 |
|---|---|
| `id`、`name`、`grade`（`pure`／`mixed`） | |
| `advice` | 紀錄中的 `kind`、推算價、同時到價機率、各內容需要的等級 |
| `actual` | 特賣期間每日紀錄的最低價、組合包折扣（是否和紀錄當時相同）；沒有每日紀錄時為 null 並寫原因 |
| `joint_hit` | 每個內容是否到需要的等級（R1 的特賣最深折扣） |
| `estimate_gap_cents` | 實際最低價 − 推算價 |
| `separate_plan` | 「各自在甜蜜時點分開買」到目前為止的實際花費；有未到的甜蜜時點時 `complete = false` |
