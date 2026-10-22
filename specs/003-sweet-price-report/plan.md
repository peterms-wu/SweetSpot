# Implementation Plan: 甜蜜價決策與 HTML 報告

**Branch**: `003-sweet-price-report` | **Date**: 2026-09-25 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/003-sweet-price-report/spec.md`

## Summary

新增決策核心 `steamsage.decision` 與呈現層 `steamsage.report`：

- **決策核心**：讀 002 的預測曲線與台灣區現價，套用甜蜜價規則 `sweet-price` v1.0.0，產生 5 種分組、甜蜜價、甜蜜時點、
  等待對照表與原因，輸出版本化的決策契約 `steamsage.decision/1`（research R1–R5）。
- **紀錄與變動**：每次正式執行把決策契約以 gzip 原子寫入 `data/forecasts/`。和「前一天或更早的最後一份紀錄」比較，
  標出分組、甜蜜時點、甜蜜價的變動（R6、R7）。
- **HTML 報告**：單一檔案、可離線開啟，只讀決策契約（R8）。
- **一鍵執行**：`steamsage report` 加上 `更新資料.cmd` 的串接（R9）。
- **規則回測**：`steamsage backtest-rule` 在 002 的台灣區資料集上評分甜蜜時點的到價率與現在買的後續（R10）。
- **偏好設定**：`steamsage.toml` 的 `[preferences]`（R11）。

plan 階段已在真實資料上跑原型（R0）：一般信心的甜蜜時點前到價 93.0%，低信心 20.2%。探索中發現的 3 個問題已經由使用者決定並寫回 spec。

## Technical Context

**Language/Version**: Python ≥3.12（開發機 3.14.6），uv

**Primary Dependencies**: 不新增第三方套件。

- 標準庫 `gzip`、`html`、`json`、`os`（`os.replace`、`os.startfile`）、`statistics`。
- 沿用 002 的 `steamsage.forecast`（引擎、模型、回測資料集與評分）。

**Storage**:

- 只讀 `data/steamsage.db`，透過 `PriceStore`。
- 新增的本機輸出，都要加進 `.gitignore`：
  - `data/forecasts/*.json.gz`：預測紀錄，只新增
  - `data/reports/*.html`
  - `data/backtests/*.json`：規則回測
- 進版控：`docs/model/model-definition.md` 新增決策規則章節。

**Testing**: pytest，測試先行。

- 決策規則用人工曲線測試，逐項對照 SC-001 的情境。
- 紀錄與比較基準用暫存目錄測試，包括中斷與損壞的檔案。
- 報告做契約比對（SC-003）與跳脫測試。
- CLI 做 contract tests。
- 規則回測在人工資料庫上做端到端測試，並做洩漏測試。

**Target Platform**: Windows 11 本機；報告在任何瀏覽器離線開啟。

**Project Type**: 單一 Python CLI 專案，新增子套件 `steamsage.decision` 與 `steamsage.report`。

**Performance Goals**:

- `report` 實測預測 3.0–3.2 秒，估計合計 5–8 秒；SC-006 上限 30 秒。
- 規則回測實測約 11 秒（R12）。

**Constraints**:

- 報告只讀決策契約（憲章 VII）。
- 不寫價格資料庫；不連網；美國區永不換算台幣（憲章 IX）。
- 單一遊戲的決策錯誤不影響其他遊戲（憲章 III）。

**Scale/Scope**:

- 願望清單約 70 款，上限 500 款（設定檔 `max_items`）。
- 規則回測約 2,500 款 × 20 個分析時點。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原則 | 本計畫的做法 | 結果 |
|---|---|---|
| I 未知不是零 | 現價未知時不判斷「現在買」，並加 `price-unknown` 標籤。低信心照樣給估計並醒目標示，包括回測到價率。P_min 為 0 不當成「不會打折」，改走低信心路徑。原價不一致時不硬套歷史 | ✅ |
| II 證據可追溯 | 每筆決策附原因、現價來源與確認時間、曲線範圍、容許差距的依據。契約帶模型、規則、偏好的版本與值。紀錄保存完整的預測曲線 | ✅ |
| III 逐項隔離失敗 | 決策錯誤只影響該遊戲（`decision-error`）。紀錄先寫 `.tmp` 再改名，比較基準只讀完整檔案，損壞的略過並註明。紀錄失敗仍出報告 | ✅ |
| IV 預測必須可驗證 | 每次正式執行都保存紀錄。甜蜜價規則用 002 的資料集回測（US5），也做洩漏測試。報告只引用回測數字，並寫明範圍。低信心組直接寫出 20% | ✅ |
| V 規則單一正本 | 規則與常數只寫在 `model-definition.md` 的決策規則章節與 `steamsage.decision.rule`。規則名稱與版本出現在每份契約、紀錄與報告。回測數字的常數以測試確保和文件一致 | ✅ |
| VI 簡單優先 | 每個門檻都有依據（spec Clarifications、research R0）。偏好值標明「使用者偏好」並可設定。不新增套件、不用樣板引擎。版本追蹤等需求不預先建構 | ✅ |
| VII 核心與呈現分離 | 決策核心輸出 `steamsage.decision/1`，台幣顯示值由核心算好。`steamsage.report` 只接受 dict，contract test 檢查它不匯入 `forecast` 或 `decision` | ✅ |
| VIII 遵守資料來源條款 | 本 feature 不連網；`更新資料.cmd` 沿用 001 的 update | ✅ |
| IX 本機與安全 | 所有輸出都在 `data/`。報告中的外部文字一律跳脫、不引用外部資源。沒有美國區金額。不需要金鑰 | ✅ |
| 開發流程 | 決策規則、比較基準、變動、紀錄原子寫入、規則回測評分都先寫會失敗的測試。功能測試與回測準確度分開報告 | ✅ |

**Post-design re-check（Phase 1 後）**：data-model 與 contracts 都符合上表，沒有違反項目。

設計中有幾個「spec 沒寫明、由設計補上」的決定，列在這裡請使用者確認：

1. **R4**：季節特賣以外的折扣，只有比季節特賣紀錄更深時才寫進原因。願望清單目前有 16 款，spec FR-007 已照此修正。
2. **R3**：現價取所有來源中最新的一筆，Steam 的現價快照優先於 ITAD；「確認時間」取兩者中較晚的。
3. **R9**：`report` 不取寫入鎖；update 失敗或已在執行時仍出報告，由 `--update-exit` 在報告中說明。
4. **R8**：報告路徑是 `data/reports/latest.html`，每次覆蓋；過去時點的報告另存。

## Project Structure

### Documentation (this feature)

```text
specs/003-sweet-price-report/
├── plan.md
├── research.md                 # R0 探索結果與 R1–R12 決定
├── data-model.md
├── quickstart.md               # 驗收情境 A–I
├── contracts/
│   ├── decision-output.md      # steamsage.decision/1，以及 forecast/1 的選用欄位 no_history
│   ├── rule-backtest-result.md # steamsage.rule-backtest/1
│   ├── report-html.md          # 報告結構與保證
│   └── cli.md                  # report、backtest-rule、[preferences]、更新資料.cmd
├── checklists/requirements.md
└── tasks.md                    # /speckit-tasks 產生
```

### Source Code (repository root)

```text
更新資料.cmd                       # update → report --open --update-exit
.gitignore                        # data/forecasts/、data/reports/
docs/model/model-definition.md    # 新增「決策規則 sweet-price v1.0.0」章節、規則回測結果；已知限制加上 004 候選
specs/002-backtest-baseline/contracts/forecast-output.md   # 註明選用欄位 no_history
src/steamsage/
├── config.py                     # [preferences] 區段、Preferences dataclass、驗證
├── cli.py / commands.py          # report、backtest-rule（唯讀，不取鎖）
├── forecast/
│   ├── contract.py               # ForecastBatch.no_history（選用）與序列化
│   └── engine.py                 # run_forecast 產生 no_history 曲線（R2）
├── decision/
│   ├── __init__.py
│   ├── rule.py                   # 規則常數、RULE_BACKTEST、decide()：純函式，輸入曲線、原價、現價、偏好（R1）
│   ├── prices.py                 # 現價、確認時間、原價不一致；非季節折扣（R3、R4）
│   ├── contract.py               # Decision、DecisionBatch、驗證、to_dict、台幣四捨五入（R5）
│   ├── engine.py                 # run_decisions()：forecast → prices → decide → batch
│   ├── records.py                # gzip 原子寫入、列出、讀取、比較基準（R6）
│   ├── changes.py                # 變動與版本、偏好差異（R7）
│   └── backtest.py               # 規則回測與結果寫入（R10）
└── report/
    ├── __init__.py
    └── html.py                   # render(contract_dict) -> str；只用標準庫（R8）
tests/
├── unit/decision/                # test_rule、test_prices、test_records、test_changes、test_backtest_scoring
├── unit/test_config.py           # [preferences]（延伸既有檔案）
├── unit/report/                  # test_html：契約比對、跳脫、無外部資源、模組匯入邊界
├── contract/                     # test_decision_contract、test_cli_report、test_cli_backtest_rule、test_rule_no_leak
└── integration/                  # test_report_flow：人工資料庫 → report 兩次（跨日）→ 變動；中斷
```

**Structure Decision**：

- 依賴方向是 `decision → forecast`（只用 engine、contract 與 backtest 的資料集和評分），`report → 無`。
  報告只吃 dict，未來的 Chrome 擴充功能也能讀同一份契約。
- `decision/rule.py` 是純函式，不碰資料庫，所以規則的單元測試與規則回測共用同一份實作。

## Phasing（給 /speckit-tasks 參考）

1. **基礎**：
   - `[preferences]` 設定。
   - `forecast` 加上 `no_history`，並補 002 契約的註記。
   - `decision/rule.py` 的 `decide()`，涵蓋 SC-001 的所有情境：兩段折扣差距、上限、下限、低信心 12 個月、P_min=0、現價已到價、現價未知、原價不一致、「原價就在容許範圍」不算現在買。全部測試先行。
2. **P1 US1**：`prices.py`、`contract.py`、`engine.py`。在真實願望清單上執行，和 R0 的原型對照。
3. **P1 US3**：`records.py`、`changes.py`，包括中斷與損壞紀錄的測試。
4. **P1 US2**：`report/html.py`、`steamsage report`。在真實資料上檢查報告。
5. **P2 US4**：`更新資料.cmd`、`--update-exit`、`--open`。實際雙擊驗收。
6. **P3 US5**：`decision/backtest.py`、`steamsage backtest-rule`、洩漏測試。
   跑真實回測，把數字寫進模型定義與 `RULE_BACKTEST`，報告改為引用正式數字。
7. **收尾**：
   - README：`report`、`backtest-rule`、`[preferences]`。
   - 模型定義：決策規則章節、004 候選。004 候選包括發售前的特賣、非季節折扣、更深的折扣，也寫進 HANDOFF。
   - `validation.md`：SC 逐項驗收、實測耗時。

## Complexity Tracking

沒有違反憲章的項目。
