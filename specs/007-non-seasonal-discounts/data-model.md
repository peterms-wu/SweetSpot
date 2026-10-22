# Data Model: 季節特賣以外的折扣

資料庫 schema 不變（v3）。本 feature 只新增記憶體中的結構、輸出欄位與回測結果檔。

## 記憶體中的結構

### NonSeasonalArrival（非季節到價；spec FR-001）

| 欄位 | 型別 | 說明 |
|---|---|---|
| `at` | datetime | 價格變化的時間 |
| `from_cut` | int | 變化前的折扣 |
| `to_cut` | int | 變化後的折扣，`to_cut > from_cut` |

- 從一條 `PriceSeries` 的相鄰狀態產生。追蹤起點不算。
- `at` 落在任何季節特賣的 [start − TOL, end) 內時，不是非季節到價。
- 判定用的季節特賣由呼叫者提供：分析時點以前已開始的特賣，或評分時的完整行事曆（R1「資料的時點」）。
- 「d 的到價」：`from_cut < d ≤ to_cut`。

### NonSeasonalPromo（非季節促銷；只用於依據）

| 欄位 | 型別 | 說明 |
|---|---|---|
| `start` | datetime | 從無折扣進入折扣的時間 |
| `end` | datetime \| None | 回到無折扣的時間；仍在進行時為 None |
| `depth` | int | 期間內最深的折扣 |

一段促銷和任何季節特賣的 [start − TOL, end) 有重疊，就不是非季節促銷。還在進行的，只看到分析時點為止。

### NSEvidence（模型看到的一款遊戲；框架產生）

| 欄位 | 說明 |
|---|---|
| `app_id`, `as_of` | |
| `arrivals` | 分析時點以前的 NonSeasonalArrival。`history` 為 TW+US 時，台灣區開始追蹤以前改用美國區 |
| `promos` | 分析時點以前的 NonSeasonalPromo，來源同上 |
| `history_start`, `history_source` | 看得到的歷史從何時開始、來源 `TW` 或 `TW+US` |
| `discounted_now` | 分析時點台灣區是否正在折扣 |
| `seasonal_ahead` | 分析時點已知或估計的未來季節特賣期間（`sale_points`）加上正在進行的那一場 |

### NSPopulation（整體比例與時鐘表；框架產生）

| 欄位 | 說明 |
|---|---|
| `share[h][d]` | 整體比例 b(h, d)（R1）：population 中每款遊戲本身比例的平均 |
| `clock` | 時鐘樣本表，依期間與狀態記錄（樣本數, 有到價數）：`(h, kgroup, phase, discounted, seasonal)`，以及兩個逐層平滑用的邊際表 |
| `as_of` | |

回測時，時鐘樣本以遊戲 × 取樣時點 t 為單位，全部只算一次。每個分析時點只彙總 t ∈ [as_of − 365 天, as_of − h] 的樣本（R7）。
樣本的特徵只用 t 以前的資料，結果只用 (t, t + h]。

### NSOutput（模型輸出；contracts/ns-model-api.md）

| 欄位 | 型別 | 說明 |
|---|---|---|
| `probabilities` | tuple[3][19] of float | [h][d]，h = 30／60／90，d = 5..95 |
| `confidence` | `normal` \| `low` | R1 |
| `sources` | tuple[3] of `own` \| `population` | 每個 h 用本身比例或整體比例 |
| `basis` | NSBasis | 依據 |
| `factors` | dict | 除錯與原因用：每個 h 的本身比例、整體比例、權重、時鐘係數 |

**保證**：
- 0 ≤ p ≤ 0.99。
- 同一個 h，d 越深 p 不增加。
- 同一個 d，h 越長 p 不減少。

### NSBasis（依據；spec FR-006）

| 欄位 | 說明 |
|---|---|
| `history_start`, `history_source`, `history_days` | 看得到的歷史 |
| `promos_365d` | 過去 365 天的非季節促銷次數 |
| `interval_days` | 間隔中位數（至少 2 次才有），否則 None |
| `common_depth` | 最常見的深度，同票數時取較深；沒有促銷時 None |
| `last_start`, `last_depth`, `days_since` | 上一次；沒有時 None |
| `in_promo_now` | 分析時點是否正在非季節促銷 |

## 輸出（contracts/outputs-non-seasonal.md）

### 決策中的 `non_seasonal`（每款遊戲）

| 欄位 | 說明 |
|---|---|
| `status` | `ok`、`not-adopted`（只有依據）、`model-error`（附原因）、`na`（遊戲本身無法預測） |
| `confidence` | 模型信心；價格歷史停止更新時改為 `low`（spec Edge Cases） |
| `basis` | NSBasis |
| `sweet` | `{ "30": p, "60": p, "90": p }`：達到甜蜜價折扣的機率；未採用或沒有甜蜜價時為 null |
| `probabilities` | 3 × 19；未採用時為 null |
| `earlier` | 見下表；不符合條件時為 null |

**`earlier`**（spec FR-014）：

| 欄位 | 說明 |
|---|---|
| `horizon_days` | 判斷期間：在甜蜜時點那場特賣開始以前就結束的最長 h |
| `probability` | 判斷期間內達到甜蜜價折扣的機率 |
| `threshold` | 顯示門檻 |
| `sale_label` | 甜蜜時點那場特賣的名稱 |
| `hit_rate` | 引用的回測命中率 |

條件，全部都要成立：
- 決策為 soon、wait 或 low。
- `non_seasonal.status = ok`，而且信心為 normal。
- 有判斷期間。
- `probability ≥ threshold`。

### 批次中的 `non_seasonal`

| 欄位 | 說明 |
|---|---|
| `adopted` | bool：`CURRENT_NS_MODEL` 是否已設定 |
| `model` | `{name, version, params}` 或 null |
| `confidence_levels` | 各信心等級的含義 |
| `threshold` | 更早到價的門檻 |
| `backtest` | 引用的數字（`NS_BACKTESTS`）或 null |

## 回測結果 `steamsage.ns-backtest/1`（contracts/cli-and-report.md）

| 區塊 | 內容 |
|---|---|
| `model` | 名稱、版本、參數 |
| `dataset` | `cutoff`、`split`、`schedule`、`horizons`、`levels`、`ns_dataset_id`、`games` |
| `units` | 依 h 的計分數與不計分數 |
| `brier`、`reference_brier` | 全體；`by_horizon`、`by_confidence`、`by_count`（依過去 12 個月次數） |
| `calibration` | 每 0.1 一組：n、預測平均、實際比例 |
| `point_hit_rate` | 機率 ≥ 50% 的單位中實際發生的比例 |
| `earlier` | 門檻 0.3–0.7：說這句話的次數與實際到價次數；另列可判斷、特賣在 30 天內、資料不足的次數；可關掉 |
| `per_game` | `{app_id: [units, sse, reference_sse]}`，比較用 |
| `errors`、`run` | 同季節回測 |

`ns_dataset_id` = SHA-256 of 以下內容：
- 季節資料集的識別碼
- 期間、`TOL`、計分條件的名稱與版本
- 每款遊戲 TW 與 US 序列的「已知至」

## 常數與設定

| 名稱 | 值 | 性質 | 位置 |
|---|---|---|---|
| `TOL` | 1 天 | 結構常數（評分框架也用） | 程式與模型定義 |
| `LOOKBACK` | 365 天 | 結構常數 | 同上 |
| 時鐘取樣間隔、平滑強度、分組界線、上限 0.99 | 14 天、20、R1、0.99 | 結構常數 | 同上 |
| 期間 | 30、60、90 天 | 評分框架設定 | 模型定義「評分框架設定」 |
| `smoothing`、`history`、`clock` | 網格選定 | 模型參數 | `CURRENT_NS_MODEL` |
| 更早到價門檻 | 50%（使用者 2026-09-26 確認） | 顯示常數 | 程式與模型定義 |
| `CURRENT_NS_MODEL` | `None`，直到使用者同意 | 現行設定 | `forecast/nonseasonal/__init__.py` |
| `NS_BACKTESTS` | 採用後的完整資料集數字 | 引用常數 | 程式；測試和模型定義比對 |

## 狀態轉換

```text
未採用（CURRENT_NS_MODEL = None）
  ── 調參組網格 → 驗證組比較（最多 3 次）
      ├─ 未通過 / 使用者不同意 → 維持未採用，報告只顯示依據（spec FR-016）
      └─ 通過且使用者同意 → 採用：設定 CURRENT_NS_MODEL，完整資料集重跑，NS_BACKTESTS 與模型定義更新
```
