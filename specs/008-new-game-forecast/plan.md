# Implementation Plan: 新遊戲與低信心的預測

**Branch**: `008-new-game-forecast` | **Date**: 2026-09-26 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/008-new-game-forecast/spec.md`

## Summary

1. **新版本 `seasonal-record` 1.1.0**：在 1.0.0 上加兩個參數。
   - `low_base`（research R1）：低信心遊戲改用「新遊戲前 k 場的經驗累積比例」；尚未發行的遊戲用預購序列（`new-split`）。
   - `shrink`（R2）：見過的等級的本身比例向全體比例收縮，強度以「場」計，紀錄越多影響越小。
   - 參數取 `population`、`0` 時，和 1.0.0 逐位相同。1.0.0 的類別保留，登錄表改為依（名稱、版本）登錄（R4）。
2. **發行日進入模型的輸入**：框架讀靜態的發行日事實，放進 `GameEvidence` 與 `PopulationView`；資料集識別碼不變（R3）。
3. **回測指標**：只計已結束的校準、依場數的細分組與逐遊戲的分組 Brier（R5）。
4. **判定**：
   - `grid` 加上 FR-004 的排除；`compare --target-groups 0,1` 加上 FR-009 的第 2 個條件（R6）。
   - 規則回測並列與願望清單差異沿用既有指令（R7）。
5. **文件更正**：005 R0.2 與決策規則 v3.0.0 已知限制 1（R9）。

**plan 階段的原型**（research R0，只用調參組，截止 2026-09-25）：

| 指標 | 1.0.0 | 候選（`new-split`、`shrink=0.5`） |
|---|---|---|
| 台灣區 Brier（002 計分） | 0.0630 | **0.0558**（−0.0072 [−0.0087, −0.0056]） |
| 美國區 Brier（1–5 年） | 0.0658 | **0.0612**（−0.0046 [−0.0058, −0.0034]） |
| 低信心組 Brier | 0.2354 | **0.0834** |
| 本身 1 場組 Brier | 0.0696 | **0.0687**（−0.0009 [−0.0012, −0.0005]） |
| 2 場／3–5 場／6 場以上 | 0.0564／0.0489／0.0404 | 沒有顯著變差（6 場以上 −0.0008） |
| 只計已結束：預測 ≥ 0.7 的高估 | +2.0 個百分點 | −0.2 |
| 規則 2.1.0：低信心的到價率 | 7.0% | 56.8% |
| 規則 2.1.0：照建議買淨效益（c = 20） | — | +1.0 [+0.6, +1.4] |
| 願望清單：分組改變 | — | 0 款（甜蜜價改變 2 款，機率微調多款） |

## Technical Context

**Language/Version**：Python ≥3.12（開發機 3.14.6），uv

**Primary Dependencies**：不新增第三方套件。原型用 numpy 只是為了分析，正式程式用純 Python。

**Storage**：

- 不改資料庫。發行日由既有的遊戲事實讀取。
- 結果檔寫到 `data/backtests/`（.gitignore 排除）。
- 進版控的文件：
  - `docs/model/model-definition.md`
  - `docs/model/comparisons.md`（只附加）
  - `specs/005-waiting-cost/research.md`（R0.2 更正）
  - HANDOFF、README

**Testing**：pytest，測試先行。

- 模型：人工的 `PopulationView`（含 `release_dates`）與 `GameEvidence`，逐項檢查 model-api 的 8 項保證與原因。
- 1.0.0 等價：真實形狀的人工資料上逐位比對。
- 指標：人工回測資料手算 `finished_calibration` 與場數分組。
- 網格：人工結果 dict 驗證 FR-004 的排除。
- 比較：`--target-groups` 的判定組合（兩條件各自成立或不成立）。
- 洩漏：002 的測試參數化，加上偷看的變體。

**Target Platform**：Windows 11 本機

**Project Type**：單一 Python CLI 專案，延伸 `steamsage.forecast`

**Performance Goals**（R10）：

- 兩區完整回測約 2 分鐘（上限 10 分鐘）。
- 網格 8 組約 8–10 分鐘。
- `report` 增加不到 0.5 秒。

**Constraints**：

- 模型只看到分析時點以前的價格與紀錄，以及靜態的發行日。
- 美國區只用折扣百分比。
- 單一遊戲的錯誤不影響其他遊戲。
- 決策規則不變。

**Scale/Scope**：

- 台灣區 2,583 款 × 20 個分析時點；調參組 1,270 款、驗證組 1,313 款。
- 美國區調參組 823 款。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原則 | 本計畫的做法 | 結果 |
|---|---|---|
| I 未知不是零 | 發行日未知就不進入序列，目標視為已發行，原因寫明。新遊戲序列不足時退回全體比例並寫明樣本不足。低信心仍標示為低信心 | ✅ |
| II 證據可追溯 | 原因寫出依據、序列數與發行日；`evidence` 保存 `low_base`、`new_games`、`shrink`；結果檔記錄 `release_facts` 的雜湊 | ✅ |
| III 逐項隔離失敗 | 沿用 `predict_one` 的例外隔離 | ✅ |
| IV 預測必須可驗證 | 參數只在調參組選；驗證組判定用 FR-029，再加上重點兩組（比 FR-029 更嚴）；最多 3 次；洩漏測試涵蓋新特徵；基準模型與 1.0.0 保留 | ✅ |
| V 規則單一正本 | 模型定義新增 1.1.0 一節；3.0.0 已知限制 1 直接改寫，不另寫修正說明；決策規則不變 | ✅ |
| VI 簡單優先 | 新增 2 個參數（網格決定）與 2 個結構常數（原型依據）；不做迴歸、不加遊戲年齡的連續特徵；只收縮 1 場的特例被拒絕（R2） | ✅ |
| VII 核心與呈現分離 | 報告不改版面，數字與原因都來自核心 | ✅ |
| VIII 遵守資料來源條款 | 不連網 | ✅ |
| IX 本機與安全 | 美國區只以折扣百分比進入美國區目標的序列；台灣區目標的新遊戲序列只用台灣區 | ✅ |
| 開發流程 | 測試先行；功能測試與準確度分開報告；網格、驗證組判定、換版都停下來等使用者 | ✅ |

**Post-design re-check（Phase 1 後）**：data-model 與 contracts 都符合上表，沒有違反項目。

設計中有幾個「spec 沒寫明、由設計補上」的決定，列在這裡請使用者確認：

1. **R0.5 低信心 → 現在買**：
   - 新依據讓分析時點正在打折的新遊戲，P_min 從 -75%～-80% 變成 -20%～-40%。規則的順序是「現在買」優先，所以調參組 0.5% 的決策（112 個）從低信心改判現在買。
   - 這是規則原本的行為，淨效益也變好（+1.0）；報告上的低信心遊戲以後會出現「現在買」。
2. **R3 發行日進入模型、資料集識別碼不變**：發行日是靜態事實，不納入識別碼（納入會讓舊比較全部失效），改在結果檔記錄雜湊。
3. **R4 版本 1.1.0 與登錄表依版本**：CLI 用 `seasonal-record@1.0.0` 指定舊版本。
4. **R0.7 願望清單的影響比 spec 預估的小**：spec 寫約 10 款受益。原型中分組都沒有改變，有意義的改變是 2 款低信心遊戲的甜蜜價與 1 款的機率，其餘是 100% 變成 95–99% 的微調。
   整體 Brier 的改善主要來自回測中的新遊戲，也就是之後會加入願望清單的遊戲。
5. **網格範圍**：`low_base` ∈ {new, new-split} × `shrink` ∈ {0, 0.25, 0.5, 1}，共 8 組。依權重與向 M 組的收縮不進網格（R2 的理由）。

## Project Structure

### Documentation (this feature)

```text
specs/008-new-game-forecast/
├── plan.md
├── research.md                 # R0 原型（只用調參組）與 R1–R11 決定
├── data-model.md
├── quickstart.md               # 驗收情境 A–I
├── contracts/
│   ├── model-api.md            # 新增的輸入欄位、登錄表、1.1.0 的 8 項保證與原因措辭
│   └── cli.md                  # 名稱@版本、grid 的 FR-004、compare --target-groups、backtest 的新指標
├── prototype/                  # plan 前後的原型（out/ 排除於版控）
├── checklists/requirements.md
└── tasks.md                    # /speckit-tasks 產生
```

### Source Code (repository root)

```text
docs/model/model-definition.md     # 1.1.0 一節、評分框架設定（--target-groups、只計已結束指標）、3.0.0 已知限制 1 更正、版本歷史
docs/model/comparisons.md          # 只附加：網格、驗證組比較、規則回測並列、使用者的決定、005 R0.2 更正
specs/005-waiting-cost/research.md # R0.2 更正段落
src/steamsage/
├── cli.py / commands.py           # 名稱@版本；compare --target-groups；backtest 摘要的新指標
├── forecast/
│   ├── evidence.py                # GameEvidence.release_date、PopulationView.release_dates
│   ├── engine.py                  # 讀發行日（一次），傳入 evidence 與 population
│   ├── models/__init__.py         # REGISTRY 依（名稱、版本）；build_model(version=)；CURRENT_MODEL（換版時才改）
│   ├── models/seasonal_record.py  # 1.1.0 子類別：low_base、shrink、原因；1.0.0 不動
│   └── backtest/
│       ├── runner.py              # 發行日、finished_calibration、場數細分組、release_facts
│       ├── metrics.py             # 新指標與分組
│       ├── grid.py                # FR-004 排除
│       └── compare.py             # --target-groups 條件與紀錄
└── decision/
    ├── backtest.py                # 發行日傳入（規則回測也用模型）
    └── rule.py                    # 換版時：RULE_BACKTESTS 新的一筆
tests/
├── unit/forecast/                 # test_seasonal_record_v110、test_registry_versions、test_metrics_finished、test_grid（FR-004）
├── contract/                      # test_no_future_leak（1.1.0 與偷看變體）、test_cli_compare（--target-groups）、test_cli_backtest（新欄位）
└── integration/                   # test_backtest_runner（release_facts、識別碼不變）、test_report_flow（換版後）
```

**Structure Decision**：
- 沿用既有的套件邊界，依賴方向 `decision → forecast`、`report → 無` 不變。
- 1.1.0 是 `seasonal-record` 的子類別。1.0.0 保留，用於切回與重現舊結果。

## Phasing（給 /speckit-tasks 參考）

1. **基礎**（測試先行）：
   - 登錄表依版本與 `名稱@版本`
   - 發行日進入 `GameEvidence`／`PopulationView`
   - 回測的新指標與場數細分組
   - SC-004：1.0.0 的 002 Brier、單位數與識別碼不變
2. **P1 US1 新版本**：
   - `seasonal_record.py` 1.1.0，含 8 項保證、原因與洩漏測試。
   - 和原型對照：`candidate.py` 在同參數下逐單位相同（先確認錯誤數為 0，007 的教訓）。
   - 在真實願望清單上抽查原因（quickstart G）。
3. **P1 US2 公平判定**：
   - `grid` 的 FR-004、`compare --target-groups`。
   - 跑調參組網格（quickstart C）。**checkpoint**：向使用者報告網格。
   - 之後才跑驗證組比較第 1 次（quickstart D）。**checkpoint**：判定交給使用者。
4. **P2 US3 決策面**：驗證組的規則回測並列與願望清單差異（quickstart E）。**checkpoint**：使用者決定換不換。
5. **P2 US4 換版**：只有判定優於而且使用者同意時才做。
   - 改 `CURRENT_MODEL`，重跑完整資料集的規則回測，更新 `RULE_BACKTESTS` 與模型定義。
   - 把真實報告交給使用者（quickstart F）。
6. **P3 US5 文件更正**（和換版無關，可以提早做）：005 R0.2、3.0.0 已知限制 1、comparisons.md 附加（quickstart H）。
7. **收尾**：
   - 模型定義：1.1.0、網格、已知限制、版本歷史
   - README：`名稱@版本`、`--target-groups`
   - HANDOFF：009「使用者指定版本、列出其他購買選項」
   - validation.md：SC 逐項驗收與實測耗時
   - 專案記憶

## Complexity Tracking

沒有違反憲章的項目。

最接近邊界的是登錄表改為依版本登錄（新增的抽象）。理由是 spec FR-016（切回 1.0.0），以及舊結果、紀錄的標示要保持正確。
替代做法「直接改 1.0.0」會讓舊結果無法重現，所以不採用。
