# Implementation Plan: 回測框架與基準模型

**Branch**: `002-backtest-baseline` | **Date**: 2026-09-25 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/002-backtest-baseline/spec.md`

## Summary

新增分析核心 `steamsage.forecast`：

- 把價格觀測整理成「價格狀態序列」與「每場季節特賣的最大折扣」。
- 由**框架**決定預測格子：未來季節特賣時點 × 19 個折扣等級。**模型**只負責填入累積機率。
- 回測框架在每月 1 日的分析時點，只把當時看得到的資料交給模型，再用之後實際發生的折扣評分。
  台灣區評估 12 個月內，美國區評估 1–5 年。
- 評分以 Brier 分數為主，每款遊戲同權重；另外輸出校準表、命中率、時間誤差與參照分數。
- 模型比較以依遊戲的成對重抽樣計算 95% 區間，依 FR-029 判定是否「優於」，並附加寫入版本化的比較文件。
- 基準模型「季節特賣經驗頻率」的參數（低信心門檻 N、是否合併美國區歷史）由正式回測決定。
  探索性回測的初步結果見 research R5。
- 特賣行事曆補齊 2012–2018 的季節特賣（FR-033）。

技術選擇與依據見 [research.md](research.md)。

## Technical Context

**Language/Version**: Python ≥3.12（開發機為 3.14.6）

**Primary Dependencies**: 不新增第三方套件。使用標準庫的 `random`（固定種子的重抽樣）、`hashlib`（資料集識別）、
`json`、`bisect`。探索性回測以純 Python 實測過效能，不需要 numpy（research R7）

**Storage**: 只讀取 `data/steamsage.db`，透過 `PriceStore`。新增的輸出：
- 回測結果：`data/backtests/*.json`，本機、不進版控。
- 模型定義文件：`docs/model/model-definition.md`，進版控。
- 模型比較紀錄：`docs/model/comparisons.md`，進版控，只附加不覆蓋。

**Testing**: pytest。模型、評分與指標的單元測試使用人工構造、答案已知的序列。洩漏測試（SC-001）竄改分析時點之後的資料，
確認預測逐位元相同。CLI 另有 contract tests

**Target Platform**: Windows 11 本機

**Project Type**: 單一 Python CLI 專案（套件 `steamsage`），新增子套件 `steamsage.forecast`

**Performance Goals**:
- 探索性實測（純 Python，research R7）：台灣區一個模型設定約 2 秒（2,590 款、20 個分析時點、278 萬個評分單位）；
  美國區約 6 秒（行事曆只到 2019、69 個分析時點、1,544 萬個評分單位）。
- 預估：行事曆補到 2012 後，美國區約 150 個分析時點，保守估 1–3 分鐘。
- 正式實作多了物件建立、分組統計與重抽樣，保守估計一次完整回測（兩區、一個模型設定）**5 分鐘以內**。
  SC-007 的上限是 30 分鐘，願望清單預測 1 分鐘內

**Constraints**:
- 分析核心只能透過 `PriceStore` 讀資料（憲章 VII）。
- 模型只能拿到分析時點以前的資料（憲章 IV）。
- 美國區永遠不換算成台幣（憲章 IX）。
- 不寫入價格資料庫（FR-035）。

**Scale/Scope**:
- 台灣區回測約 2,600 款遊戲 × 20 個分析時點 × 19 個折扣等級 × 約 4 場特賣。
- 美國區約 1,750 款遊戲 × 約 150 個分析時點 × 19 個折扣等級 × 約 16 場特賣。
- 願望清單約 70 款。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原則 | 本計畫的做法 | 結果 |
|---|---|---|
| I 未知不是零 | 資料少時仍給估計並標示「低信心」。沒有資料的季節特賣不算成 0%。最後一次抓取之後的期間算成截斷，不當作「沒有打折」（R3）。無法預測的遊戲有明確狀態 | ✅ |
| II 證據可追溯 | 每份預測附模型名稱、版本、參數、分析時點、資料截止時間、原因與證據摘要（用到哪幾場特賣、哪一區）。回測結果附資料集識別 | ✅ |
| III 逐項隔離失敗 | 單一遊戲的模型例外或輸出不合法，記為該遊戲的錯誤狀態，不中斷整批。回測結果先寫暫存檔，完成後才改名 | ✅ |
| IV 預測必須可驗證 | 本 feature 的核心。回測框架只把截斷後的證據交給模型，並以洩漏測試驗證。基準模型是比較下限。比較結果寫入版本化文件。信心等級附回測分數。未經回測的準確率不宣稱 | ✅ |
| V 規則單一正本 | 規則只寫在 `docs/model/model-definition.md` 與對應程式碼。參數改變就遞增版本。模型名稱、版本、參數出現在每份輸出中 | ✅ |
| VI 簡單優先 | 基準模型只有 2 個參數（N、歷史來源），都由回測決定（R5）。不新增第三方套件。不預先實作 004 的模型 | ✅ |
| VII 核心與呈現分離 | 預測輸出為版本化 JSON（`steamsage.forecast/1`），不含 HTML。只透過 `PriceStore` 讀資料，並新增兩個唯讀方法（R3、R7） | ✅ |
| VIII 遵守資料來源條款 | 不連網。行事曆補齊只用 Valve 官方或媒體來源，不用 SteamDB | ✅ |
| IX 本機與安全 | 美國區只用折扣百分比，輸出中沒有美國區的金額。所有輸出都在本機。本 feature 不需要金鑰 | ✅ |
| 開發流程 | 測試先行：序列建構、特賣最大折扣、評分結果判定、指標、重抽樣判定、洩漏測試都先寫測試。功能測試與預測準確度分開報告 | ✅ |

**Post-design re-check（Phase 1 後）**：data-model 與 contracts 都符合上表，沒有違反項目。

設計中有兩個「規格沒寫、但由設計補上」的決定，列在這裡請使用者確認：

1. 回測的分析時點排程從「第一場已結束的季節特賣之後」開始：台灣區是 2025-02-01。之前的時點沒有任何歷史可以用，
   兩種歷史來源的變體也會因此比較不同的評分單位（R6）。
2. 預測使用的價格序列只採 ITAD 歷史（含舊專案匯入），不含本工具的 `steam-current` 現價快照（R1）。

## Project Structure

### Documentation (this feature)

```text
specs/002-backtest-baseline/
├── plan.md
├── research.md
├── research-calendar-2012-2018.toml   # R8：待加入行事曆的 21 場季節特賣與研究註記
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── forecast-output.md      # 預測 JSON 契約 steamsage.forecast/1
│   ├── backtest-result.md      # 回測結果 JSON 與比較紀錄格式
│   ├── model-api.md            # 模型介面（給 feature 004）
│   ├── cli.md                  # forecast / backtest / compare 指令
│   └── store-api-additions.md  # PriceStore 新增的唯讀方法
├── checklists/requirements.md
└── tasks.md                    # /speckit-tasks 產生
```

### Source Code (repository root)

```text
data/
├── steam_sales.toml             # 補齊 2012–2018 季節特賣（FR-033）
└── backtests/                   # 回測結果 JSON（本機，.gitignore 排除）
docs/model/
├── model-definition.md          # 模型定義正本（憲章 V），含參數依據與已知限制
└── comparisons.md               # 模型比較紀錄，只附加
src/steamsage/
├── store/query.py               # 新增 history_known_until()、series_rows()（唯讀）
├── cli.py / commands.py         # 新增 forecast、backtest、compare 指令（唯讀，不取鎖）
└── forecast/
    ├── __init__.py
    ├── series.py                # 價格狀態序列、季節特賣最大折扣、新折扣事件（R1）
    ├── salepoints.py            # 未來季節特賣時點：已知 + 預估；進行中的特賣不列入（R2）
    ├── evidence.py              # 截斷到分析時點的證據：GameEvidence、PopulationView（R3）
    ├── contract.py              # Forecast、SalePoint、Curve；JSON 序列化；FR-004 驗證
    ├── engine.py                # 對一組遊戲在一個分析時點產生預測（forecast 與 backtest 共用）
    ├── models/
    │   ├── __init__.py          # 模型註冊表與 CURRENT_MODEL
    │   ├── base.py              # Model 介面、ModelOutput
    │   └── seasonal_freq.py     # 基準模型
    └── backtest/
        ├── dataset.py           # 回測資料集定義、排程、識別碼（R6）
        ├── scoring.py           # 評分單位與結果判定：已發生 / 未發生 / 截斷 / 未舉辦（R3）
        ├── metrics.py           # Brier（每款遊戲同權重）、校準表、命中率、時間誤差、分組（R4）
        ├── runner.py            # 執行回測、進度、原子寫入結果
        └── compare.py           # 成對重抽樣、FR-029 判定、附加比較紀錄
tests/
├── unit/forecast/               # series、salepoints、scoring、metrics、seasonal_freq、compare
├── contract/                    # forecast JSON 契約、無洩漏（SC-001）、CLI、store 新方法
└── integration/                 # 在人工資料庫上端到端跑 forecast → backtest → compare
```

**Structure Decision**：分析核心 `forecast` 只依賴 `store.query` 與 `calendar`，不依賴 sources 或 pipeline。
`backtest` 依賴 `forecast`，但 `forecast` 不依賴 `backtest`，這樣 feature 003 只需要 `forecast`。

預測格子由框架（`salepoints` 與 `engine`）決定，模型只填機率，所以不同模型在同一份資料集上一定得到相同的評分單位，
可以成對比較。

## Phasing（給 /speckit-tasks 參考）

1. **基礎**：`series.py`（序列、特賣最大折扣、新折扣事件）、`salepoints.py`、`PriceStore.history_known_until()` 與 `series_rows()`、`contract.py`，
   全部測試先行。
2. **P1 使用情境 1**：模型介面、基準模型、`engine.py`、`steamsage forecast`。在真實願望清單上執行。
3. **P1 使用情境 2**：`scoring.py`、`metrics.py`、`dataset.py`、`runner.py`、`steamsage backtest`、洩漏測試（SC-001）。
4. **行事曆補齊**（FR-033）：把 R8 的 2012–2018 季節特賣加入 `steam_sales.toml`，跑 `calendar --check`。
   必須在美國區正式回測之前完成。
5. **P2 使用情境 3**：`compare.py`、`steamsage compare`、比較紀錄文件。
6. **P2 使用情境 4 與正式回測**：用真實資料跑 N 的網格與兩種歷史來源，決定基準模型 v1 的參數。
   寫 `model-definition.md` 與第一筆比較紀錄，設定 CURRENT_MODEL。
7. **收尾**：README、validation.md（實測耗時、分數、已知限制）、SC 逐項驗收。

## Complexity Tracking

沒有違反憲章的項目。
