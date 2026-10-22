# Implementation Plan: 等待成本

**Branch**: `005-waiting-cost` | **Date**: 2026-09-26 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/005-waiting-cost/spec.md`

> **2026-10-22 稽核補記：規則 3.0.0 沒有採用。** 2026-09-26 的驗證組判定中，`sweet-price` 3.0.0 沒有通過換版的硬門檻
> （spec FR-015：c = 20、每月重新評估，平均淨效益差距 +1.7 [−0.7, +4.2]，區間含 0），使用者決定不換版，以「未優於」結束
> （[validation.md](validation.md) 第 2 節；005 T030–T032 跳過、005 T033）。現行規則是 2.1.0（feature 006；
> `src/sweetspot/decision/rule.py` 的 `CURRENT_RULE`）。3.0.0 與 006 加的 3.1.0 只留在程式中，供預覽
> （`sweetspot report --rule`）與回測（`sweetspot backtest-rule --rule/--wait-cost`、`sweetspot compare-rule`）；
> 偏好 `wait_cost_twd` 只在這些情況使用。下文第 5 點的「換版」沒有發生，表中「2.0.0（現行）」是當時的狀態。

## Summary

1. **規則 `sweet-price` v3.0.0**（research R1–R4）：
   - 對每個（目標折扣 d，最晚第 K 場）選項，用現行模型的累積曲線算出期望實付價格與期望等待。
   - 到期沒達到時以原價計算（R2）。
   - 選「期望多省 − c × 期望等待月數」最高的選項，沒有任何選項 > 0 就現在買。
   - 甜蜜時點 = 期限內累積機率第一次 ≥ 50% 的那一場，另外輸出最晚時點（R3）。
   - 決策輸出每場一列的等待對照表（R4）。
2. **偏好**：新增使用者偏好 `wait_cost_twd`，預設 NT$20／月（使用者 plan 階段決定）。偏好依規則分組（R5）。
3. **評估**（R6、R7）：
   - `backtest-rule` 可以一次跑多個 c，新增「每月重新評估」的照建議買、淨效益、逐案結果，以及放寬範圍的計數。
   - `compare-rule` 並列一個基準與多個候選，用成對重抽樣給出淨效益差距與 95% 區間。
   - 驗證組判定最多 3 次。
4. **輸出**：
   - 決策輸出升為 `steamsage.decision/2`，舊紀錄仍可讀（R9）。
   - 報告顯示等待成本、期望多省、淨效益與新的對照表（R10）。
   - 回測數字依 c 對照，c 不同就不引用（R8）。
5. **換版**：只在驗證組通過硬門檻（c = 20、每月重新評估、區間下限 > 0）而且使用者同意之後進行。

**plan 階段的原型**（research R0，只用調參組）：

| 規則 | 平均多省 | 平均多等 | 淨效益（c = 20） |
|---|---|---|---|
| 2.0.0（現行） | NT$211 | 41 天 | 184.4 |
| 下一場以最可能的折扣買 | NT$193 | 23 天 | 177.4 |
| **3.0.0 c = 20** | NT$201 | 19 天 | **188.5**（+4.0 [+2.2, +5.7]） |

- 3.0.0 沒有找到更多可省的錢，它依 c 取捨：少省 NT$10，少等 22 天。
- 願望清單的「繼續等」從 28 款降到 4 款。

## Technical Context

**Language/Version**：Python ≥3.12（開發機 3.14.6），uv

**Primary Dependencies**：不新增第三方套件。成對重抽樣用標準函式庫的 `random`，種子固定。

**Storage**：

- 不改資料庫。
- 結果檔寫到 `data/backtests/`，不進版控。
- 預測紀錄 `data/forecasts/*.json.gz` 從換版起是 `/2`。
- 進版控的文件：
  - `docs/model/model-definition.md`：規則 3.0.0、偏好、原型、規則回測、已知限制、版本歷史
  - `docs/model/comparisons.md`：只附加
  - `steamsage.toml` 範本、README、HANDOFF

**Testing**：pytest，測試先行。

- 規則 3.0.0：人工曲線（2–4 場、少數等級）逐案手算期望值，以分為單位。另測 c 單調、平手規則、各種特殊路徑。
- 每月重新評估：人工 `PriceSeries` 與人工決策序列，包含換決策、截斷、決策出錯時沿用。
- 成對重抽樣：人工 cases，固定種子。
- 契約：`/2` 的保證，以及 `/1` 紀錄的讀取與比較。
- 報告：從人工 `/2` dict 產生報告，逐一比對。
- 洩漏：003 的 `test_rule_no_leak` 參數化；另外證明每月重新評估不改變 t0 的決策。

**Target Platform**：Windows 11 本機

**Project Type**：單一 Python CLI 專案，延伸 `steamsage.decision`、`steamsage.report` 與 `steamsage.config`

**Performance Goals**（research R13）：

| 執行 | 目標 |
|---|---|
| `backtest-rule` 完整資料集，單一 c | 約 20 秒 |
| `backtest-rule` 完整資料集，6 個 c | 約 30 秒 |
| `compare-rule` | 約 30 秒 |
| `report` | 增加 < 0.5 秒；SC-007 上限 30 秒 |

**Constraints**：

- 規則只讀曲線、價格與偏好。
- 金額是整數分，期望值比較前四捨五入。
- 單一遊戲的錯誤不影響其他遊戲。
- 呈現層不計算。

**Scale/Scope**：

- 台灣區完整資料集 2,583 款 × 20 個分析時點；調參組 1,270 款、驗證組 1,313 款。
- 願望清單 68 款。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原則 | 本計畫的做法 | 結果 |
|---|---|---|
| I 未知不是零 | 現價未知時不判現在買，以原價估計並標示。3.0.0 的容許差距欄位為 null，不填 0（升 `/2` 的原因）。截斷的決策不計入 | ✅ |
| II 證據可追溯 | 原因列出選中選項、對照選項、c、機率與「沒到價以原價計」。決策輸出與結果檔帶規則版本、c、模型與切分 | ✅ |
| III 逐項隔離失敗 | 沿用 `decision-error`。每月重新評估時，某個時點出錯就沿用前一個決策，不中斷 | ✅ |
| IV 預測必須可驗證 | 規則常數只在調參組選。c 在驗證組比較前定案。驗證組硬門檻最多 3 次，全部記錄。原型與正式實作對照。洩漏測試涵蓋 3.0.0 | ✅ |
| V 規則單一正本 | 3.0.0 只寫在模型定義與 `rule.py`，升主版本。2.0.0 保留供並列與切回，文件寫明 | ✅ |
| VI 簡單優先 | 只新增 1 個使用者偏好，並拿掉 3.0.0 的 5 個容許差距偏好。新的規則常數只有 `miss_price`（原型比較 3 種後選定）。和最簡單的規則比較過（R0.1） | ✅ |
| VII 核心與呈現分離 | 期望值、對照表、淨效益都由決策核心算好；報告只讀 `/2` | ✅ |
| VIII 遵守資料來源條款 | 不連網 | ✅ |
| IX 本機與安全 | 只有台灣區金額；沒有美國區金額 | ✅ |
| 開發流程 | 規則、每月重新評估、成對比較、契約、報告都先寫會失敗的測試。功能測試與「新規則是否較好」分開報告 | ✅ |

**Post-design re-check（Phase 1 後）**：data-model 與 contracts 都符合上表，沒有違反項目。

設計中有幾個「spec 沒寫明、由設計補上」的決定，請使用者確認：

1. **R9**：決策輸出升為 `steamsage.decision/2`。3.0.0 的容許差距欄位是 null，不能以 0 冒充；舊的 `/1` 紀錄仍可讀取與比較。
2. **R5**：偏好依規則分組。決策輸出、結果檔與報告只記錄該規則用到的偏好，切換規則時不會出現無關的「偏好改變」。
3. **R8**：c 和回測不一致時不引用到價率，只說明原因（spec FR-020 允許的兩種做法之一）。
4. **cli**：`report --rule 3.0.0` 產生預覽報告，不寫紀錄、不比較，用於換版前檢查。
5. **data-model**：3.0.0 判為現在買時，甜蜜價欄位顯示「等下去最好的選項」，和 003 的報告版面一致。
6. **R11**：原因至少列一個對照選項，依序取「現在買／只等到下一場／期望多省最高」中和選中不同的。

## Project Structure

### Documentation (this feature)

```text
specs/005-waiting-cost/
├── plan.md
├── research.md                 # R0 原型（只用調參組）與 R1–R14 決定
├── data-model.md
├── quickstart.md               # 驗收情境 A–H
├── contracts/
│   ├── decision-output-v2.md   # steamsage.decision/2
│   ├── rule-backtest-v005.md   # 淨效益、每月重新評估、cases、longer_horizon
│   ├── report-html-v005.md     # 3.0.0 的報告
│   └── cli.md                  # backtest-rule --wait-cost、compare-rule 多候選與次數、report --rule
├── prototype/                  # 原型程式（只讀調參組）
├── checklists/requirements.md
└── tasks.md                    # /speckit-tasks 產生
```

### Source Code (repository root)

```text
docs/model/model-definition.md   # 規則 3.0.0、偏好、規則回測、已知限制、版本歷史
docs/model/comparisons.md        # 只附加：調參組並列、驗證組比較、使用者的決定
steamsage.toml                   # [preferences] wait_cost_twd = 20，容許差距加註「只供 2.0.0」
scripts/wait_cost_monotonic.py   # quickstart C：c 單調的真實資料檢查（唯讀）
src/steamsage/
├── config.py                    # Preferences.wait_cost_twd、驗證、for_rule()
├── cli.py / commands.py         # backtest-rule --wait-cost、compare-rule 多候選與 --attempt/--change、report --rule
├── decision/
│   ├── rule.py                  # RULES["3.0.0"]、decide_wait_cost()、WaitOption、option_value()、RULE_BACKTESTS 加 c
│   ├── engine.py                # 依規則呼叫、3.0.0 的原因（R11）、notes 依 c（R8）
│   ├── contract.py              # /2：wait_options、expected、deadline_point、nullable 容許差距
│   ├── records.py               # 接受 /1 與 /2
│   ├── changes.py               # 等待成本改變的措辭；只比較兩邊都有的偏好
│   ├── backtest.py              # 多個 c 共用預測、follow_advice_monthly、net、cases、longer_horizon
│   └── compare_rule.py          # 多候選、成對重抽樣、判定、次數、願望清單的期望淨效益
└── report/html.py               # 3.0.0 的頁首、摘要列、等待對照表；2.0.0 照舊
tests/
├── unit/decision/               # test_rule_v3、test_follow_monthly、test_net_summary、test_compare_rule（延伸）、test_changes（延伸）
├── unit/config/                 # test_preferences（wait_cost_twd、for_rule）
├── unit/report/                 # test_html_v3
├── contract/                    # test_decision_contract_v2、test_rule_no_leak（3.0.0）、test_cli_backtest_rule、test_cli_compare_rule
└── integration/                 # test_report_flow（/1 → /2、c 改變的註明、預覽不寫紀錄）
```

**Structure Decision**：

- 沿用既有的套件邊界，依賴方向 `decision → forecast`、`report → 無` 不變。
- 規則 3.0.0 是 `rule.py` 中的一個新分支。`decide()` 依版本分派到 2.x 的容許差距邏輯或 3.0.0 的等待成本邏輯，共用路徑判斷
  （低信心、P_min 為 0、原價不一致）。

## Phasing（給 /speckit-tasks 參考）

1. **基礎**，全部測試先行：
   - 偏好：`wait_cost_twd`、驗證、`for_rule`。
   - 決策輸出 `/2`：contract 與 records 相容，changes 的措辭。
2. **P1 US1 規則 3.0.0**：
   - `rule.py` 的期望值、選擇、甜蜜時點與對照表，以及 engine 的原因。
   - 在調參組上和原型對照：決策與原型逐案相同。
   - `report --rule 3.0.0` 預覽，在真實願望清單上抽查措辭（quickstart B）。
3. **P2 US3 報告**（MVP）：
   - 3.0.0 的頁首、摘要列與對照表。
   - **checkpoint**：把預覽報告交給使用者看版面與措辭，再繼續。
4. **P1 US2 評估**：
   - `backtest-rule`：多個 c、每月重新評估、淨效益、cases、longer_horizon。
   - `compare-rule`：多候選、成對重抽樣、判定、次數。
   - 調參組並列（quickstart D），和原型對照。**checkpoint**：報告給使用者。
   - 之後才跑驗證組第 1 次（quickstart E）。**checkpoint**：交給使用者決定換不換。
5. **P2 US4 換版**：只有通過硬門檻而且使用者同意時才做。
   - 改 `CURRENT_RULE`，在完整資料集上重跑，更新 `RULE_BACKTESTS` 與模型定義。
   - `steamsage.toml` 範本與 README。
   - 把真實報告交給使用者（quickstart F、G）。
   - 不換版時，只記錄結果（quickstart H）。
6. **收尾**：
   - 模型定義：規則 3.0.0、原型、已知限制、版本歷史。
   - HANDOFF：下一個 feature 的候選。放寬 12 個月範圍時，以 R0.4 為依據。
   - validation.md：SC 逐項驗收、實測耗時。
   - 專案記憶。

## Complexity Tracking

沒有違反憲章的項目。

- 決策輸出升版是為了遵守憲章 I：不以 0 冒充不存在的容許差距。舊紀錄仍可讀。
- 2.0.0 與 1.0.0 保留在程式中，只供並列與切回（憲章 V）。這和 004 保留舊模型、舊規則的做法相同。
