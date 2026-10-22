# Data Model: 回測框架與基準模型（feature 002）

本 feature 不改動資料庫 schema。以下實體都是記憶體中的值物件（`frozen dataclass`），或寫到檔案的 JSON。
時間一律使用帶時區的 UTC `datetime`。折扣以整數百分比表示（0–100）。

## 分析核心（`steamsage.forecast`）

### PriceState（R1）

| 欄位 | 型別 | 說明 |
|---|---|---|
| start | datetime | 這個狀態開始生效的時間（`observed_at`） |
| cut | int | 折扣百分比；NULL 的觀測不產生狀態 |
| is_tracking_start | bool | 序列的第一筆；不是新折扣事件 |

`PriceSeries`：一款遊戲、一個區域的狀態清單，依 `start` 升冪排列、去重，並附 `known_until`（R3）。

- `truncate(as_of)`：回傳 `start <= as_of` 的狀態，`known_until` 改為 `min(known_until, as_of)`。
- `events_after(as_of)`：回傳 `start > as_of` 且非追蹤起點的狀態，也就是新折扣事件。

### SaleOutcome

一場**已結束**的季節特賣，在某個區域的結果。

| 欄位 | 型別 | 說明 |
|---|---|---|
| sale_key | (season, year) | 例如 ("spring", 2027) |
| label | str | 「2027 春特」 |
| region | str | "TW" 或 "US" |
| max_cut | int | 特賣期間的最大折扣（R1 的規則）；0 表示有資料但沒打折 |

序列沒有完整涵蓋的特賣不產生 SaleOutcome。「沒有資料」與「0%」因此不會混在一起（憲章 I）。

### SalePoint（R2）

曲線上的一個未來時點。

| 欄位 | 型別 | 說明 |
|---|---|---|
| index | int | 從 1 開始，分析時點之後的第幾場季節特賣 |
| sale_key | (season, year) | |
| label | str | 「2027 春特」 |
| start / end | datetime | 已公告的日期，或預估日期 |
| status | str | `announced`（官方公告）或 `estimated`（預估） |
| basis | dict \| None | 預估的依據（參考年份、原始起訖）；已公告的為 None |

規則：只列 `start > as_of` 的特賣，到 as_of + 60 個月為止；只列 as_of 前 18 個月內舉辦過的季節。

### GameEvidence（R3）

模型對一款遊戲能看到的全部資料，已截斷到 as_of。

| 欄位 | 型別 | 說明 |
|---|---|---|
| app_id | int | |
| as_of | datetime | |
| target_region | str | "TW" 或 "US" |
| series | dict[region, PriceSeries] | 已截斷。target 是 US 時只有 US |
| sale_history | dict[region, list[SaleOutcome]] | 只含 end ≤ as_of 的特賣 |
| facts | ProductFacts | `PriceStore.facts(app_id, as_of)` |

### PopulationView

同一個分析時點、同一個 target 下，資料集所有遊戲的 `sale_history`，已截斷。
模型在每個分析時點呼叫一次 `prepare()`，用它計算整體比例並快取。

### ModelOutput

| 欄位 | 型別 | 說明 |
|---|---|---|
| probabilities | list[list[float]] | `[point][level]`，累積機率 |
| confidence | str | `normal` 或 `low` |
| reasons | list[str] | 人類可讀的原因（繁體中文） |
| evidence | dict | 證據摘要：用了哪一區、幾場特賣、期間、整體比例的樣本數 |

框架會驗證維度、範圍（0–1）與單調性（FR-004）。不合法的輸出記為該遊戲的 `model-error`，不影響其他遊戲。

### Forecast（對外輸出，contracts/forecast-output.md）

| 欄位 | 說明 |
|---|---|
| app_id、name | |
| status | `ok`、`unreleased`、`free`、`unsupported-bundle`、`no-history`、`unverified`、`model-error` |
| status_reason | 狀態不是 ok 時的說明 |
| confidence | `normal` 或 `low`（只在 status = ok 時） |
| reasons、evidence | 取自 ModelOutput |
| regular_price_cents | 分析時點的台灣區原價，供 003 換算台幣；只有台灣區 |
| curve | `levels`（5–95）、`points`（SalePoint）、`probabilities` |

預測批次（ForecastBatch）另外記錄：契約版本、模型名稱與版本與參數、分析時點、資料截止時間、產生時間。

**狀態判定順序**（第一個符合的就是結果）：

1. 套裝 → `unsupported-bundle`
2. 分析時點尚未發行 → `unreleased`
3. 台灣區原價為 0 → `free`
4. 商品核對失敗 → `unverified`
5. 沒有 ITAD 台灣區歷史 → `no-history`
6. 模型例外或輸出不合法 → `model-error`

## 回測（`steamsage.forecast.backtest`）

### BacktestDataset（R6）

| 欄位 | 說明 |
|---|---|
| dataset_ids | 每個區域一個 SHA-256（十六進位），由該區的下列欄位與該區目標可以看到的觀測計算（research R6） |
| cutoff | 資料截止時間；預設為最新的資料已知時間，取到當天 00:00 UTC |
| apps | 排序後的 app_id 清單，以及每款的樣本來源（wishlist、related、broad、legacy） |
| known_until | 每款遊戲、每個區域的資料已知時間 |
| schedules | 每個區域的分析時點清單 |
| levels | [5, 10, …, 95] |
| windows | 台灣區：預測結束時間在 (as_of, as_of + 12 個月]；美國區：在 (as_of + 12 個月, as_of + 60 個月] |
| calendar_hash | 評分用的實際季節特賣起訖 |

### ScoringUnit（只在記憶體中，不保存）

遊戲 × 分析時點 × 折扣等級 × 時點。`outcome` 為以下其中之一：

| outcome | 條件 | 計分 |
|---|---|---|
| `occurred` | 第一次新折扣事件 t\* < 實際結束時間 | 是（o = 1） |
| `not-occurred` | 實際結束時間 ≤ 資料已知時間，且沒有事件 | 是（o = 0） |
| `censored` | 實際結束時間 > 資料已知時間，且目前還沒有事件 | 否 |
| `not-held` | 行事曆中沒有這場特賣，而且預估結束時間 ≤ 資料已知時間 | 否 |

行事曆中沒有、而且預估結束時間 > 資料已知時間的特賣，還不知道會不會舉辦：已知時間內已經出現新折扣的算 `occurred`（那場特賣若舉辦，一定在事件之後結束），否則算 `censored`。這是美國區實跑時發現的：60 個月的時點會延伸到行事曆還沒有的年份。

### BacktestResult（contracts/backtest-result.md）

| 欄位 | 說明 |
|---|---|
| schema | `steamsage.backtest/1` |
| model | 名稱、版本、參數 |
| dataset | BacktestDataset 的摘要與識別碼（不含觀測本身） |
| per_region | 每個區域：Brier、參照分數、評分與截斷與未舉辦的數量、遊戲數、分組結果、校準表、命中率、時間誤差 |
| per_game | 每個區域、每款遊戲：評分單位數與平方誤差總和。供 `compare` 做成對重抽樣 |
| errors | 模型錯誤：遊戲、分析時點、原因 |
| run | 開始與結束時間、耗時、程式版本 |

### ComparisonRecord（附加寫入 `docs/model/comparisons.md`）

- 日期與資料集識別碼
- 模型 A（現行）與模型 B（候選）：名稱、版本、參數、結果檔名
- 每個區域：兩者的 Brier、差距（B − A）、95% 區間、遊戲數
- 判定：`優於`、`未優於`、`建立下限`（第一筆），以及理由

**驗證**（逐區域，FR-028）：

- 台灣區必須兩份都有。兩份都有的區域，`dataset_ids[區域]` 必須相同，而且每款遊戲的評分單位數都相同。
- 只有一份有美國區時：兩個模型的名稱與版本相同，而且參數差異全部屬於模型的 `tw_only_params`，才可以比較；
  美國區差距視為 0，並在紀錄中註明。
- 其他情況一律拒絕，並列出第一個不同的地方。
