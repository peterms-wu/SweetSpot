# Implementation Plan: 能預測更深折扣的模型

**Branch**: `004-deeper-discount-model` | **Date**: 2026-09-26 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/004-deeper-discount-model/spec.md`

## Summary

1. **新模型 `seasonal-record` v1.0.0**（research R1）：
   - 過去見過的折扣等級用近期加權的本身頻率。
   - 比過去更深的等級用「創新低」狀態鏈：每場創新低的機率依「目前最深折扣 × 距上次創新低幾場」查表，
     表從分析時點以前的所有遊戲估計，可以加入美國區的折扣百分比（R3）。
2. **公平比較**：
   - 依遊戲雜湊切出調參組與驗證組（R4）。
   - `grid` 在調參組上依 spec FR-011 選參數（R7）。
   - `compare` 在驗證組上判定，最多 3 次（FR-013）。
   - 回測新增「比過去更深」與「依場數」分組（R2）。
3. **決策面**：
   - `backtest-rule` 可以指定模型、規則與切分，並新增「照建議買」與甜蜜時點分布（R6）。
   - `compare-rule` 並列兩份結果，並列出願望清單差異（R8）。
4. **規則 `sweet-price` v2.0.0**：P_min 只看 12 個月（R5，使用者在 plan 階段決定）。
   - 模型限制的提示改由模型提供，報告不再寫死（R9）。
   - 換版只在驗證組判定「優於」而且使用者同意之後進行。

**plan 階段的原型**（R0，只用調參組）：

| 指標 | 現行 | 候選 |
|---|---|---|
| 台灣區 Brier | 0.1026 | **0.0630** |
| 美國區（1–5 年）Brier | 0.1775 | **0.0658** |
| 照建議買（規則 2.0.0）：多省 | NT$194 | NT$208 |
| 照建議買（規則 2.0.0）：多等 | 55 天 | 52 天 |

同一個候選配上舊規則（P_min 看 5 年），願望清單 57/65 款會變成「繼續等」。這個發現促成了規則 2.0.0。

## Technical Context

**Language/Version**：Python ≥3.12（開發機 3.14.6），uv

**Primary Dependencies**：不新增第三方套件。倒推表用純 Python，每個分析時點只算一次（R10）。

**Storage**：

- 不改資料庫。
- 結果檔寫到 `data/backtests/`，已被 .gitignore 排除。
- 進版控的文件：
  - `docs/model/comparisons.md`：只附加
  - `docs/model/model-definition.md`：新模型、規則 2.0.0、評分框架的切分設定
  - HANDOFF、README

**Testing**：pytest，測試先行。

- 模型：人工的 `PopulationView` 與 `GameEvidence`，檢查 model-api 契約的 6 項保證與原因。
- 切分與資料集識別：人工資料庫。
- 網格選參數：人工回測結果 dict。
- 比較次數：暫存的比較文件。
- 照建議買：人工價格序列逐案手算。
- `notes` 與 RuleBacktestFigures：一致性測試讀模型定義。
- 洩漏：002、003 的洩漏測試參數化，並加上偷看的變體。

**Target Platform**：Windows 11 本機

**Project Type**：單一 Python CLI 專案，延伸既有的 `steamsage.forecast` 與 `steamsage.decision`

**Performance Goals**（R10）：

- 兩區完整回測約 2 分鐘；SC-009 上限 10 分鐘。
- 調參組網格約 4–5 分鐘。
- `report` 增加不到 1 秒。

**Constraints**：

- 模型只看到分析時點以前的資料。
- 美國區只用折扣百分比。
- 單一遊戲的錯誤不影響其他遊戲。
- 呈現層不寫死結論。

**Scale/Scope**：

- 台灣區 2,583 款 × 20 個分析時點；美國區 1,703 款 × 154 個分析時點。
- 各半切分後，台灣區調參組 1,270 款、驗證組 1,313 款。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原則 | 本計畫的做法 | 結果 |
|---|---|---|
| I 未知不是零 | 創新低機率表以加法平滑向 M 組與全體靠攏；全體為 0 時明寫「沒有足夠的樣本」，不假裝有證據。截斷的決策不計入照建議買 | ✅ |
| II 證據可追溯 | 原因寫出上一次創新低的特賣、查表的格子、機率、樣本數與區域；`evidence` 保存這些值。結果檔與紀錄帶模型、規則、切分與版本 | ✅ |
| III 逐項隔離失敗 | 新模型沿用 `predict_one` 的例外隔離（`model-error`） | ✅ |
| IV 預測必須可驗證 | 參數只在調參組選。換版只看驗證組的 FR-029 判定，最多 3 次並全部記錄。規則回測並列。洩漏測試涵蓋新模型。基準模型 `seasonal-freq` 保留 | ✅ |
| V 規則單一正本 | 模型與規則 2.0.0 只寫在模型定義與對應程式。規則升主版本。舊規則 1.0.0 只為並列比較保留，文件寫明。提示文字由模型提供，不另寫說明文件 | ✅ |
| VI 簡單優先 | 3 個模型參數都由網格決定。結構常數依 R0.1 的特徵表。平滑強度因為沒有影響而固定為 20。不做迴歸、不新增套件。「等待成本」記為之後的候選 | ✅ |
| VII 核心與呈現分離 | `notes` 由決策核心產生，報告只顯示；報告仍只讀 `steamsage.decision/1` | ✅ |
| VIII 遵守資料來源條款 | 不連網 | ✅ |
| IX 本機與安全 | 美國區只以折扣百分比進入創新低機率表，已有 001 的一致性驗證與 R0.2 的網格證據，原因中標示區域（R3）；沒有任何美國區金額 | ✅ |
| 開發流程 | 模型、切分、選參數、比較次數、照建議買都先寫會失敗的測試。功能測試與準確度分開報告 | ✅ |

**Post-design re-check（Phase 1 後）**：data-model 與 contracts 都符合上表，沒有違反項目。

設計中有幾個「spec 沒寫明、由設計補上」的決定，列在這裡請使用者確認：

1. **R5**：規則 2.0.0 只在模型換版時一起換上。如果新模型沒換上，規則維持 1.0.0，因為改規則的動機是新模型。
   原型中「現行模型＋規則 2.0.0」和現行幾乎相同（NT$195 / 55 天）。
2. **R9**：`RULE_BACKTEST` 改成依（規則、模型、參數）對照。切回舊模型時，自動用那一組的數字；沒有數字就不引用準確率。
3. **R4**：`split = all` 的資料集識別碼和 002 相同，舊結果仍可比較；調參組與驗證組的識別碼另外包含全部遊戲的資料。
4. **R11 第 5 點與 spec FR-011 第 3 步**：`min_sales=1` 讓只有 1 場紀錄的遊戲變成一般信心。`grid` 會依場數分組比較，
   如果 1 場的遊戲比低信心差，就退回 `min_sales=2`。
5. **R7**：新增 `grid` 指令，把 FR-011 的選參數規則寫成程式與測試，不再手動比對。

## Project Structure

### Documentation (this feature)

```text
specs/004-deeper-discount-model/
├── plan.md
├── research.md                     # R0 原型結果（只用調參組）與 R1–R12 決定
├── data-model.md
├── quickstart.md                   # 驗收情境 A–I
├── contracts/
│   ├── model-api.md                # predicts_deeper、deeper_caveat；seasonal-record 的保證與原因
│   ├── results-and-decisions.md    # backtest/1、rule-backtest/1、decision/1 的新增欄位
│   └── cli.md                      # backtest --split、grid、compare --attempt、backtest-rule 新參數、compare-rule
├── checklists/requirements.md
└── tasks.md                        # /speckit-tasks 產生
```

### Source Code (repository root)

```text
docs/model/model-definition.md     # seasonal-record 章節、網格、特徵分析、規則 2.0.0、評分框架（切分）、版本歷史
docs/model/comparisons.md          # 只附加：網格、驗證組比較、規則回測並列、使用者的決定
src/steamsage/
├── cli.py / commands.py           # grid、compare-rule；backtest/backtest-rule/compare 的新參數
├── forecast/
│   ├── models/__init__.py         # 登錄 seasonal-record；CURRENT_MODEL（換版時才改）
│   ├── models/base.py             # predicts_deeper、deeper_caveat
│   ├── models/seasonal_freq.py    # 兩個新屬性（值照舊）
│   ├── models/seasonal_record.py  # 新模型：近期加權頻率、創新低機率表、倒推表、原因（R1）
│   └── backtest/
│       ├── split.py               # 雜湊切分（R4）
│       ├── dataset.py             # split、population_apps、識別碼
│       ├── runner.py              # 整體比例用 population_apps；deeper_than_past、by_own_sales
│       ├── metrics.py             # 新分組
│       ├── compare.py             # split 檢查、--attempt/--change、更深分組列
│       └── grid.py                # 網格與選參數（R7）
├── decision/
│   ├── rule.py                    # RULES {1.0.0, 2.0.0}、CURRENT_RULE、decide(rule=…)、RULE_BACKTESTS 對照表
│   ├── engine.py                  # notes、依規則版本的用語、deeper-possible 依 predicts_deeper
│   ├── contract.py                # notes、rule_backtest.model
│   ├── backtest.py                # --model/--rule/--split、sweet_timing、follow_advice、hindsight（R6）
│   └── compare_rule.py            # 並列、願望清單差異、紀錄（R8）
└── report/html.py                 # 顯示 notes；「長期最低價」依規則用語；拿掉寫死的提示
tests/
├── unit/forecast/                 # test_seasonal_record、test_split、test_grid、test_metrics_deeper
├── unit/decision/                 # test_rule_v2、test_follow_advice、test_rule_backtest_doc（延伸）、test_compare_rule
├── unit/report/                   # test_html：notes、用語
├── contract/                      # test_no_future_leak / test_rule_no_leak 參數化；test_cli_grid、test_cli_compare_rule、test_cli_compare（次數）
└── integration/                   # test_backtest_runner（split）、test_report_flow（換版後的版本改變）
```

**Structure Decision**：

- 沿用既有的套件邊界，依賴方向 `decision → forecast`、`report → 無` 不變。
- 新模型是模型登錄表中的一個新類別。
- 舊模型與舊規則保留：舊模型是基準模型，也用來切回（FR-026）；舊規則只供並列比較。

## Phasing（給 /speckit-tasks 參考）

1. **基礎**，全部測試先行：
   - 切分與資料集（`split`、`population_apps`、識別碼）
   - 回測的新分組
   - 模型介面的兩個新屬性
2. **P1 US1 新模型**：`seasonal_record.py`，含契約的 6 項保證與原因，以及洩漏測試。
   - 在真實願望清單上檢查 Cyberpunk 2077 等遊戲的原因。
   - 和 R0 原型的調參組分數對照，應在 ±0.001 內。
3. **P1 US2 公平比較**：
   - `grid`（選參數規則）、`compare` 的次數限制，在真實資料上跑調參組網格（quickstart C）。
   - **checkpoint**：向使用者報告網格結果。
   - 之後才跑驗證組比較第 1 次（quickstart D）。
4. **P2 US3 決策面**：
   - 規則 2.0.0，以及 `backtest-rule` 的新參數與指標。
   - `compare-rule`，在驗證組上跑並列（quickstart E）。
   - **checkpoint**：把並列報告與願望清單差異交給使用者決定。
5. **P2 US4 換版**：只有 FR-029「優於」而且使用者同意時才做。
   - `notes`、RuleBacktestFigures 對照表、報告用語。
   - 改 `CURRENT_MODEL` 與 `CURRENT_RULE`，在完整資料集上重跑規則回測，更新模型定義。
   - 把真實報告交給使用者（quickstart F、G）。
   - 不換版時，只做 `notes` 與對照表的重構，讓報告不再寫死提示（FR-027 不論換不換都適用），並記錄結果。
6. **收尾**：
   - 模型定義：新模型、網格、特徵表、已知限制、版本歷史。
   - README：新指令。
   - HANDOFF：下一個 feature 的候選，包括等待成本、非季節折扣、發售前特賣、遊戲年齡。
   - validation.md：SC 逐項驗收、實測耗時。
   - 專案記憶：原始目標「甜蜜價不設時間上限」已改成 12 個月。

## Complexity Tracking

沒有違反憲章的項目。

唯一接近邊界的是舊規則 1.0.0 保留在程式中（憲章 V）。它只能用 `backtest-rule --rule 1.0.0` 執行，不能成為現行規則以外的輸出，
而且模型定義會寫明它只供並列比較。這和舊模型保留在登錄表中是同一種做法。
