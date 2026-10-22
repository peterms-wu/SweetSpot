# Implementation Plan: 季節特賣以外的折扣

**Branch**: `007-non-seasonal-discounts` | **Date**: 2026-09-26 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/007-non-seasonal-discounts/spec.md`

## Summary

1. **新的預測模型 `non-seasonal` 1.0.0**（research R1）：
   - 本身過去 365 天的窗口比例：未來 h 天內出現 d 的非季節到價，佔過去窗口的比例。
   - 用本身歷史的月數向整體比例平滑。
   - 乘上從 population 樣本表查到的「時鐘係數」：過去一年的促銷次數、距上一次是典型間隔的幾倍、是否正在折扣、期間內是否有季節特賣。
   - 台灣區開始追蹤以前用美國區補。
   - 和季節模型分開，有自己的介面、註冊表與 `CURRENT_NS_MODEL`（未採用前為 `None`）。
2. **回測**（R2）：
   - 新格式 `steamsage.ns-backtest/1`。
   - 只計資料涵蓋整個期間的單位，參照分數是整體比例。
   - 另外計算「更早到價」這句話在各門檻的命中率。
   - 新指令 `ns-backtest`、`ns-grid`、`ns-compare`。
3. **採用流程**（R3）：調參組 12 組網格 → 驗證組比較一次（最多 3 次）→ 使用者同意 → 設定 `CURRENT_NS_MODEL`，在完整資料集上重跑。
4. **輸出與報告**（R4、R5）：
   - 決策輸出新增選用欄位 `non_seasonal`，契約版本不變。
   - 報告加上「季節特賣以外」的依據與機率，以及「可能提早」的標籤與句子。
   - 決策規則 2.1.0 完全不變。
5. **文件**（R6）：
   - 模型定義新增非季節一節。
   - `seasonal-record` 已知限制 1 改寫，用完整資料集重算兩種校準。
   - 決策規則已知限制 4 改寫。

**plan 階段的原型**（research R0，只用調參組）：

| 項目 | 結果 |
|---|---|
| 候選模型（R0.2） | M3：本身比例 × 時鐘，平滑 2 個月，TW+US。Brier **0.1271**，整體比例 0.1906，差距 −0.0635 [−0.0675, −0.0597]。30 天 0.1088 |
| 更早到價（R0.2） | 門檻 50%：可判斷的決策中有 30.8% 會說這句話，**實際到價 71.8%**；門檻 60%：23.7%、76.4% |
| 改規則的上限（R0.3） | 甜蜜價參考非季節紀錄：改變 6.7% 的決策，多省 NT$8、多等 16 天，淨效益（c = 20）不顯著；事後上限多省 NT$36 |
| 002 的截斷偏差（R0.1） | `seasonal-record` 0–0.1 那一格實際 4.7% → 只算已結束的特賣 3.2%，其中只算季節特賣 2.1% |

## Technical Context

**Language/Version**：Python ≥ 3.12（開發機 3.14.6），uv

**Primary Dependencies**：不新增第三方套件。

**Storage**：

- 資料庫 schema 不變（v3）；只讀既有的價格序列與特賣行事曆。
- 決策輸出與正式紀錄 `data/forecasts/*.json.gz` 新增選用欄位，契約 `steamsage.decision/2` 不升版。
- 新的回測結果檔 `steamsage.ns-backtest/1`，存在 `data/backtests/`（不進版控）。
- 進版控的文件：
  - `docs/model/model-definition.md`（非季節一節、評分框架、已知限制 1 與 4、版本歷史）
  - `docs/model/comparisons.md`（只附加）
  - README、HANDOFF

**Testing**：pytest，測試先行（research R8）。人工價格序列與行事曆（沿用 `tests/forecast_builders.py`），洩漏測試證明抓得到三種偷看。

**Target Platform**：Windows 11 本機

**Project Type**：單一 Python CLI 專案，延伸 `steamsage.forecast`、`steamsage.decision`、`steamsage.report`，新增 `steamsage.forecast.nonseasonal`。

**Performance Goals**（research R7）：

| 執行 | 目標 |
|---|---|
| `report` | 增加 < 5 秒；一鍵更新全部 < 30 秒 |
| `ns-backtest` 完整資料集 | < 2 分鐘（估計 60–100 秒，不含更早到價） |
| `ns-grid` 12 組，調參組 | < 10 分鐘 |
| `backtest`、`backtest-rule` | 不變 |

**Constraints**：

- 決策規則與季節模型不變，逐案相同（spec SC-005）。
- 模型只收到截斷在分析時點的結構，框架負責判定。
- 美國區只用折扣百分比與日期。
- 驗證組只在比較時使用。
- 未採用前不顯示機率。

**Scale/Scope**：

- 願望清單 68 款。
- 回測資料集：台灣區，20 個分析時點。調參組 1,270 款，population 約 2,500 款。

## Constitution Check

依憲章 **1.2.0**。

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原則 | 本計畫的做法 | 結果 |
|---|---|---|
| I 未知不是零 | 期間超過資料已知時間的單位不計分，已發生的也一樣，修正 002 的不對稱。歷史不足時改用整體比例並標為低信心，不當成「沒有促銷」 | ✅ |
| II 證據可追溯 | 輸出寫出依據：歷史來源、次數、間隔、深度、上一次。另外寫出模型、參數、信心與引用的回測數字；原型與網格的結果都有紀錄 | ✅ |
| III 逐項隔離失敗 | 單款的非季節模型出錯只標 `model-error`，決策與季節預測照常 | ✅ |
| IV 預測必須可驗證 | 可在任意過去時點回測，洩漏測試涵蓋三種偷看。基準是整體比例。參數只在調參組選，驗證組判定優於，而且使用者同意才採用。正式紀錄保存完整機率。命中率只引用回測數字 | ✅ |
| V 規則單一正本 | 新模型的規則、參數、結構常數與門檻寫在模型定義，程式常數由測試比對。決策規則不變，版本不升 | ✅ |
| VI 簡單優先 | 不新增使用者偏好。結構常數都有原型依據，模型只有 3 個參數。不改規則（YAGNI，R0.3 的上限證據） | ✅ |
| VII 核心與呈現分離 | 機率、條件、依據都由決策層產生，報告只讀 | ✅ |
| VIII 遵守資料來源條款 | 不新增任何外部請求 | ✅ |
| IX 本機與安全 | 只用本機資料；美國區只用折扣百分比 | ✅ |
| 開發流程 | 測試先行；每個 checkpoint commit；會影響採用的決定（網格、驗證組判定、採用）停下來等使用者 | ✅ |

**Post-design re-check（Phase 1 後）**：data-model 與 contracts 符合上表。research R9 的門檻由使用者確認為 50%，plan 於 2026-09-26 經使用者確認。

## Project Structure

### Documentation (this feature)

```text
specs/007-non-seasonal-discounts/
├── spec.md
├── plan.md              # 本文件
├── research.md          # R0 原型、R1–R9 設計決定
├── data-model.md        # 記憶體結構、輸出欄位、回測結果、常數、狀態轉換
├── quickstart.md        # 驗收步驟
├── contracts/
│   ├── ns-model-api.md          # 非季節模型介面、保證、措辭
│   ├── outputs-non-seasonal.md  # 決策輸出與紀錄的新欄位
│   └── cli-and-report.md        # ns-backtest／ns-grid／ns-compare、報告
├── prototype/           # P0–P2 與 nslib；out/ 不進版控
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks 產生
```

### Source Code (repository root)

```text
src/steamsage/
├── forecast/
│   ├── nonseasonal/                 # 新
│   │   ├── __init__.py              # NS_REGISTRY、build_ns_model、CURRENT_NS_MODEL（None）、NS_BACKTESTS
│   │   ├── events.py                # 非季節到價與非季節促銷、TOL、窗口比例
│   │   ├── evidence.py              # NSEvidence、NSPopulation、時鐘樣本（依分析時點截斷）
│   │   ├── model.py                 # non-seasonal 1.0.0（本身比例、平滑、時鐘係數、單調化）
│   │   ├── engine.py                # 現在時點的預測（報告用）；輸出檢查
│   │   └── backtest.py              # 計分單位、Brier、校準、參照、更早到價命中率、ns_dataset_id、網格、比較
│   └── backtest/
│       └── compare.py               # 重抽樣與紀錄格式：共用函式，非季節的紀錄格式另寫
├── decision/
│   ├── engine.py                    # 每款附加 non_seasonal；earlier 條件；原因句子與標籤
│   ├── contract.py                  # Decision.non_seasonal、DecisionBatch.non_seasonal、序列化與保證檢查
│   ├── records.py                   # 讀舊紀錄（沒有 non_seasonal）
│   └── changes.py                   # 變動比較忽略 non_seasonal；從未採用變成採用的頁首註記
├── report/html.py                   # 「季節特賣以外」一段、「可能提早」標籤、頁首
├── cli.py, commands.py              # ns-backtest、ns-grid、ns-compare
docs/model/model-definition.md, docs/model/comparisons.md

tests/
├── unit/forecast/test_ns_events.py, test_ns_model.py, test_ns_backtest.py
├── unit/decision/test_ns_decision.py
├── unit/report/test_ns_report.py
├── contract/test_ns_no_leak.py, test_ns_outputs.py, test_cli_ns.py
└── integration/test_ns_report_flow.py
```

**Structure Decision**：非季節預測放在 `forecast/nonseasonal/` 子套件，和季節模型的 `forecast/models/` 平行。
季節的 `Model` 協定與 `steamsage.backtest/1` 完全不動，所以 004–006 的結果與比較都還能用。
決策與報告只多讀一個欄位。

## Complexity Tracking

沒有違反憲章的地方。新增的子套件與三個指令是必要的：非季節的輸出單位（天）和季節的單位（場）不同，共用會改變既有契約的意義（research R2）。
