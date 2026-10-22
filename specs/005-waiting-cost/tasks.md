---

description: "Task list for feature 005: waiting cost"
---

# Tasks: 等待成本

**Input**：`specs/005-waiting-cost/` 的 plan.md、spec.md、research.md、data-model.md、contracts/、quickstart.md

**Tests**：憲章要求核心邏輯測試先行。每個實作任務前都有對應的測試任務：先寫測試並確認它會失敗，再實作。

**Organization**：依使用情境分組。執行順序依 plan 的 Phasing：US1 → US3（MVP，先給使用者看報告）→ US2 → US4。

| 情境 | 內容 | 優先 |
|---|---|---|
| US1 | 規則 3.0.0：依等待成本決定現在買還是等 | P1 |
| US2 | 規則回測：每月重新評估、淨效益、並列與驗證組判定 | P1 |
| US3 | 報告顯示等待划不划算 | P2 |
| US4 | 換上新規則後，文件與數字一致 | P2 |

## Format: `[ID] [P?] [Story] Description`

- **[P]**：可以並行（不同檔案，也不依賴未完成的任務）
- **[Story]**：所屬的使用情境（US1–US4）
- 路徑都相對於 repo 根目錄

## 共用約定（每個任務都適用）

- **驗證組**：在 T029 之前，任何指令、腳本或測試**都不得**對真實資料的驗證組計分或列印驗證組的結果（spec FR-014）。
  真實資料上只能跑 `--split tuning`、`--split all` 的預測，以及願望清單。
- **c**：預設 `wait_cost_twd = 20`（使用者偏好），在 T029 之前不得再改。
- **規則常數**（research R1–R3），只寫在 `src/steamsage/decision/rule.py` 與模型定義（憲章 V）：
  - `p_min_months = 12`
  - `timing_threshold = 0.5`、`p_min_threshold = 0.5`
  - `low_confidence_months = 12`、`stale_hours = 24`
  - `miss_price = "regular"`
  - `month_days = 365 / 12`
- **3.0.0 的公式**（research R1）：設 F_i(d) 為曲線第 i 場（1 起算）的累積機率，F_0 = 0；B 為基準價（現價，未知時原價）；m(t) = (t − as_of) 天數 ÷ `month_days`。
  - 期望實付 = Σ_{i≤K}(F_i − F_{i−1}) × price(d) ＋ (1 − F_K) × 原價
  - 期望等待 = Σ_{i≤K}(F_i − F_{i−1}) × m(第 i 場 start) ＋ (1 − F_K) × m(第 K 場 end)
  - 期望多省、等待成本、淨效益都四捨五入成整數分之後再比較。
- **金額**：價格是整數分；`twd()` 對負數也是 0.5 進位（例如 −150 分 → −1 元），測試要涵蓋。
- **分層**：`steamsage.report` 只接受決策契約的 dict（憲章 VII）。
- **CLI**：新參數都唯讀、不取寫入鎖，只寫 `data/backtests/`；`--record` 時才附加 `docs/model/comparisons.md`。
- **文字**：使用者看得到的文字用繁體中文；中文與數字之間的空格照 004 的慣例。
- **Checkpoint**：每完成一個，就跑 `uv run pytest`、commit（附 attribution trailer），並向使用者報告。要在真實資料上執行，不能只看測試。

---

## Phase 1: Setup

- [X] T001 在 `tests/decision_builders.py` 新增 3.0.0 測試用的工具（不碰資料庫）：
  - `timed_points(as_of, spans)`：`spans` 是 `[(start_月, end_月), …]`，依 `month_days` 換成日期，產生 `SalePoint`（標籤像「2026 秋特」依序輪替）。
  - `step_curve(rows)`：`rows` 是每場一個 `{level: 累積機率}`，未列出的等級補成「隨折扣加深不遞增」的曲線，檢查隨時間不遞減。
  - `prefs(**kw)`：`Preferences` 加上 `wait_cost_twd`（預設 20）。

---

## Phase 2: Foundational（所有使用情境的前提）

**⚠️ 這個階段完成前，不開始任何使用情境。**

- [X] T002 [P] 在 `tests/unit/test_config.py` 寫偏好的測試：
  - `wait_cost_twd` 預設 20；設定檔 `wait_cost_twd = 35` 讀成 35。
  - 「整數，0–10,000」：−1、10001、1.5、"20" 都拋出 `ConfigError`，訊息為「preferences.wait_cost_twd 必須是 0 到 10000 的整數」。
  - `for_rule("2.0.0")` 只有 003 的六個鍵；`for_rule("3.0.0")` 只有 `wait_cost_twd`、`soon_sales`；`for_rule("1.0.0")` 同 2.0.0。
- [X] T003 實作 `src/steamsage/config.py` 的 `Preferences.wait_cost_twd`、驗證與 `for_rule()`；
  在 `steamsage.toml` 的 `[preferences]` 加上 `wait_cost_twd = 20` 與註解「每多等一個月要多省的台幣（使用者偏好，規則 3.0.0）」，
  容許差距各項加註「只用於規則 2.0.0（並列回測）」。
- [X] T004 [P] 在 `tests/contract/test_decision_contract.py` 加上 `/2` 的測試（contracts/decision-output-v2.md 保證 1–10）：
  - `schema` 是 `steamsage.decision/2`；`preferences` 依規則分組。
  - 3.0.0 的決策：容許差距欄位為 null；有 `wait_options`、`expected`；非現在買時有 `deadline_point`。
  - `wait_options` 與 `expected` 的每個 `*_cents` 都有對應的 `*_twd`；負數金額 0.5 進位。
  - 2.0.0 的決策：欄位值和 `/1` 相同，沒有 `wait_options`。
- [X] T005 [P] 在 `tests/unit/decision/test_records.py` 加上：`/1` 與 `/2` 的紀錄都能讀取；其他 schema 拋出 `RecordError`。
- [X] T006 [P] 在 `tests/unit/decision/test_changes.py` 加上：
  - c 改變時，`version_changes` 有「等待成本從 NT$20 改成 NT$30」。
  - 偏好只比較兩邊都有的鍵：`/1`（2.0.0 偏好）的基準對 `/2`（3.0.0 偏好）時，只有「規則 sweet-price 2.0.0 → 3.0.0」，沒有任何偏好改變。
  - 分組、甜蜜時點、甜蜜價的變動照舊比較。
- [X] T007 實作 `src/steamsage/decision/contract.py`：`SCHEMA = "steamsage.decision/2"`；`Decision` 新增 `wait_options`、`deadline_point`、`expected`；
  `batch_to_dict` 的 `preferences` 改用 `for_rule(rule.version)`；`twd()` 支援負數（0.5 進位）。
  同時改 `src/steamsage/decision/records.py`（接受 `/1`、`/2`）與 `src/steamsage/decision/changes.py`（等待成本措辭、只比共有的鍵）。
  跑全部測試：004 的測試中寫死 `/1` 的地方，改成 `/2` 並確認語意不變。

**Checkpoint**：`uv run pytest` 全部通過；`uv run steamsage report` 仍用 2.0.0，產生 `/2` 紀錄，並和 2026-09-26 的 `/1` 紀錄正常比較。

---

## Phase 3: User Story 1 — 依等待成本決定現在買還是等（P1）🎯

**Goal**：規則 3.0.0 在任何曲線上都給出期望值正確、可解釋的決策。

**Independent Test**：人工曲線上的期望值與手算完全相同（SC-001）；c 提高，等待不增加（SC-002）。

- [X] T008 [P] [US1] 在 `tests/unit/decision/test_rule_v3.py` 寫規則 3.0.0 的測試（用 T001 的工具）：
  - **期望值手算**：2 場、目標 -50%，F = 0.6、0.9，原價 100,000 分，現價 = 原價，c = 20。逐項核對：
    - 期望實付、期望等待、期望多省、等待成本、淨效益，全部以整數分核對。
    - 到期沒達到的部分以原價、最晚那一場的 end 計算。
  - **選擇**：
    - 每一場選淨效益最高的等級，相同時選較淺的等級。
    - 所有場中選最高且 > 0 的選項，相同時選較早的一場。
    - 全部 ≤ 0 時現在買。
  - **甜蜜時點**：T = 第一個 F_i(d) ≥ 0.5 的那一場，沒有就 = K；`sweet_probability = F_T`；`deadline_index = K`。
  - **`wait_options`**：
    - 第 0 列是現在買，淨效益 0；之後每場一列，列到 12 個月內的最後一場。
    - 恰好一列 `chosen`，等於 `expected`。
    - `net = saving − cost`。
    - 某一場沒有任何價格 < B 的等級時，那一列只有時點。
  - **路徑**（同 2.0.0）：
    - 低信心：分組 low，範圍 12 個月。
    - 一般信心但 12 個月內沒有等級 ≥ 50%：改用 no-history 曲線、low、basis = no-history；沒有 no-history 曲線時拋出 `DecisionError`。
    - 原價不一致：low。
    - 12 個月內沒有季節特賣：`DecisionError`。
  - **現價未知**：基準價 = 原價；沒有第 0 列；分組 ≠ now，改選淨效益最高的選項（即使 ≤ 0）；有 `price-unknown` 標籤。
  - **現在買時的甜蜜價**：取淨效益最高的等待選項。沒有任何候選等級時，甜蜜價 = 現價、甜蜜時點 = 下一場、`sweet_probability = None`。
  - **3.0.0 不用容許差距**：`gap_pp`、`tolerance_*`、`target_cents` 為 None；改變容許差距偏好不影響結果。
  - **P_min 只當參考**：值和 2.0.0 相同，改變它不影響選擇。
  - **c 單調**：固定種子隨機產生 200 條合法曲線，c 取 0、10、20、30、50、80、120 時，選中選項的期望等待不增加。
  - **c = 0**：選中的是期望多省最高的選項。
  - **可重現**：同一輸入兩次結果相同。
  - **版本**：2.0.0 與 1.0.0 的現有測試照舊通過。
- [X] T009 [US1] 實作 `src/steamsage/decision/rule.py`：
  - `RULES["3.0.0"]`，包含上方共用約定的常數與 `"kind": "wait-cost"`。
  - frozen dataclass `WaitOption`，欄位照 data-model.md。
  - `RuleResult` 新增 `wait_options`、`deadline_index`、`expected`、`wait_cost_twd`。
  - `decide()` 依版本分派：2.x 維持原邏輯；3.0.0 走 `_decide_wait_cost()`，共用路徑判斷。
  - `option_value(curve, points, as_of, regular_cents, base_cents, pct, deadline_index, wait_cost_twd) -> WaitOption`：
    以 R1 的公式評估任意一個選項，給 `compare-rule` 評估 2.0.0 的建議（T026）。
  - 每款遊戲每個分析時點只算一次各等級的累積項（research R13）。
  - `CURRENT_RULE` 維持 `"2.0.0"`。
- [X] T010 [P] [US1] 在 `tests/integration/test_decision_engine.py` 加上 3.0.0 的決策與原因測試（research R11）：
  - 原因的順序依序為：範圍、等待成本（含「使用者偏好」）、建議（最可能到價、最晚、到期前機率）、期望值（含「到期沒達到時以原價計算（規則常數）」）、至少一個對照選項。
  - 各種情況的措辭：
    - 現在買：「等下去最好的選項是……淨效益 NT$…，不划算；現在買」
    - 現價未知：「現價未知，以原價估計，無法判斷是否現在買」
    - 沒有候選等級：「沒有比現價更低的折扣等級可以等」
    - 低信心、no-history、原價不一致、現價過舊、非季節折扣：沿用 003 的原因
  - 從沒打折過的遊戲，不得出現「-0%」或「創新低」（004 的教訓）。
  - **限制提示（spec FR-022）**：3.0.0 的 `notes` 中，模型的 `deeper_caveat` 數字取自 3.0.0 那一筆的 `now_deeper_within_12m`。
    措辭要符合 3.0.0 的語意：12 個月內最低價只是參考，提示說的是「判為現在買之後 12 個月內仍有 X% 出現更深折扣」。
    需要時調整 `src/steamsage/forecast/models/seasonal_record.py` 的 `deeper_caveat`，並確認 2.0.0 下的措辭不變。
  - `rule_backtest`：`lookup_backtest("3.0.0", model, c)` 在 c 相同時回傳該筆；c 不同時為 None，
    `notes` 有「規則回測是以等待成本 NT$20 算的，目前設定為 NT$X，沒有對應的回測，所以不引用到價率」。
  - 決策輸出的 `preferences` 只有 `wait_cost_twd`、`soon_sales`。
- [X] T011 [US1] 實作 `src/steamsage/decision/engine.py`：
  - `run_decisions(…, rule=)` 依規則呼叫，3.0.0 用 R11 的原因。
  - `lookup_backtest` 加上 `wait_cost_twd` 參數。`RULE_BACKTESTS` 的每一筆加 `"wait_cost_twd"`，2.0.0 與 1.0.0 為 None。
  - `notes` 依 research R8；`preferences` 用 `for_rule`。
- [X] T012 [P] [US1] 在 `tests/contract/test_rule_no_leak.py` 把規則參數化，加上 3.0.0：
  竄改分析時點之後的資料，決策（包含 `wait_options` 的每個整數分）不變。
- [X] T013 [P] [US1] 在 `tests/contract/test_cli_report.py` 加上 `report --rule` 的測試（contracts/cli.md）：
  - `--rule 3.0.0`（非現行）：
    - `official = false`，不寫 `data/forecasts/`，不和前一天比較。
    - 輸出 `data/reports/preview-3.0.0.html`，不動 `latest.html`；頁首有「預覽：非現行規則」。
  - `--rule` 等於現行規則時，等於一般的 `report`。
  - 設定檔的 `wait_cost_twd` 無效時，結束代碼 1。
- [X] T014 [US1] 實作 `src/steamsage/cli.py` 與 `src/steamsage/commands.py` 的 `report --rule`（choices 加上 `3.0.0`），
  以及 `backtest-rule --rule` 的 choices 加上 `3.0.0`（參數在 T024 完成）。
- [X] T015 [US1] 和原型逐案對照（research R0）：
  1. 依 `specs/005-waiting-cost/prototype/` 的說明重建 `cache_tuning.pkl`（`proto_cache.py`，約 11 秒）。
  2. 新增 `specs/005-waiting-cost/prototype/parity.py`：對同一批曲線，以 c = 20 比較 `rule.decide(rule="3.0.0")`
     和原型 `decide3` 的分組、目標折扣、最晚時點與甜蜜時點。
  3. **預期 100% 相同**。不同的案例要逐一說明原因（例如整數分的平手）；如果是正式實作的錯誤，要先修正。
  4. 結果寫進 research.md 的 R0 末尾。
- [X] T016 [US1] 新增 `scripts/wait_cost_monotonic.py`（唯讀，quickstart C）：對現在的願望清單，c 取 0、10、20、30、50、80、120 各做一次 3.0.0 決策。
  檢查兩件事：每款遊戲的期望等待不增加；c = 0 時期望多省最高。最後印出違反的款數，應為 0。在真實資料上執行並記錄。

**Checkpoint**：
- 執行 `uv run steamsage report --rule 3.0.0`（quickstart B）：
  - 各組款數和 research R0.6 相近。
  - 逐一抽查特殊情況的原因措辭。
  - 耗時 < 30 秒。
- commit，並向使用者報告。

---

## Phase 4: User Story 3 — 報告顯示等待划不划算（P2，MVP 的最後一步）

**Goal**：使用者在報告中看得到建議的期望多省、等待成本、淨效益與機率，以及每場的對照。

**Independent Test**：由人工 `/2` dict 產生報告，每個數值都和契約相同（SC-005）。

- [X] T017 [P] [US3] 在 `tests/unit/report/test_html.py` 加上 3.0.0 的測試（contracts/report-html-v005.md 保證 1–4）：
  - **頁首**：有「等待成本 NT$20／月（使用者偏好）」與規則 3.0.0，不出現「容許差距」；預覽時有「預覽：非現行規則」。
  - **摘要列**：
    - 甜蜜價、甜蜜時點與機率、最晚等到、期望多省、淨效益逐一等於契約值。
    - 現在買的遊戲，期望多省與淨效益顯示「—」。
  - **等待對照表**：
    - 列數 = `wait_options` 的列數，恰好一列「建議」；第一列是「現在買」。
    - 期望等待顯示一位小數。
  - **回測數字**：`rule_backtest` 為 null 時不顯示到價率，只顯示 `notes`；否則各組標題註明「以等待成本 NT$20 回測」。
  - **比較基準**：`version_changes` 中的「等待成本從 NT$20 改成 NT$30」照樣顯示。
  - **2.0.0 不變**：用 004 的 `/1` dict 產生的報告和現在完全相同。
  - **不變的保證**：跳脫、沒有外部資源。
- [X] T018 [US3] 實作 `src/steamsage/report/html.py`：
  - 依 `rule.version` 與欄位決定顯示方式，不做任何計算。
  - 12 個月內最低價在 3.0.0 移到展開後的詳細資料。
- [X] T019 [P] [US3] 在 `tests/integration/test_report_flow.py` 加上：
  - 前一天是 `/1`（2.0.0）的紀錄、今天是 `/2`（3.0.0）時，頁首有「規則 sweet-price 2.0.0 → 3.0.0」，變動照常標示。
  - 前一天 c = 20、今天 c = 30 時，頁首有「等待成本從 NT$20 改成 NT$30」。
  - 預覽不寫紀錄，也不成為之後的比較基準。
- [X] T020 [US3] **MVP checkpoint**：
  1. 在真實資料上執行 `uv run steamsage report --rule 3.0.0`。
  2. 用 Playwright 截圖，檢查版面在窄視窗也不會水平捲動（`uv run --with playwright python 腳本`）。
  3. 把 `data/reports/preview-3.0.0.html` 用 `SendUserFile` 交給使用者。
  4. **停下來等使用者對版面與措辭的意見**，修改後才進入 Phase 5。

---

## Phase 5: User Story 2 — 用回測判斷新規則是不是真的比較好（P1）

**Goal**：在同一份資料上並列 2.0.0 與 3.0.0 的淨效益，並在驗證組上依硬門檻判定。

**Independent Test**：人工價格路徑上，每個決策的實際多省、天數與淨效益和手算一致（SC-003）；成對差距與區間可重現。

- [X] T021 [P] [US2] 在 `tests/unit/decision/test_follow_monthly.py` 寫每月重新評估的測試（research R6 第 2 點；人工 `PriceSeries`
  與人工的決策序列 `{(app, as_of): 決策}`）：
  - t0 的決策是現在買：以 t0 的現價買，0 天。
  - 在兩個分析時點之間到價：以那個價格狀態的價格買，天數從 t0 算起。
  - 下一個分析時點改成新的甜蜜價，之後才到新甜蜜價：以新甜蜜價的到價時點計算。
  - 下一個分析時點的決策是現在買：以那時的現價買。
  - 某個分析時點沒有決策（出錯或不在清單）：沿用前一個。
  - 12 個月內都沒買：以 t0 + 12 個月的價格買。
  - 資料已知時間早於下一個檢查點而且還沒買：截斷。
  - **淨效益**：多省（元）− cost × 天數 ÷ (365/12)。
    - `evaluation_costs_twd` = `[0, 10, 20, 30, 50, 80]` 加上規則本身的 c（不重複、排序）。
    - 平均、中位數、p25、p75 用 nearest-rank，和既有的百分位相同。
  - `cases` 的列格式 `[app_id, "YYYY-MM-DD", mode, saving_cents, wait_days]`，依 (app_id, as_of, mode) 排序，截斷的不列。
    列數 = 兩種模式的 evaluated 相加。
- [X] T022 [US2] 實作 `src/steamsage/decision/backtest.py`：
  - `MonthlyScore`、`follow_advice_monthly()`、淨效益彙總（`follow_advice` 與 `follow_advice_monthly` 都有 `net_twd`）、`cases`。
  - `run_rule_backtest(…, wait_costs=[…])`：每個分析時點只預測一次，依每個 c 各自決策與計分，回傳多份結果。
  - `longer_horizon`：只在 3.0.0；範圍改為 24 與 60 個月時的 `decisions`、`beyond_12m`、`mean_expected_wait_months`。
  - `preferences` 用 `for_rule`。
  - 結果檔名加上 `-c<值>`（contracts/rule-backtest-v005.md）。
  - 既有的 `follow_advice`、到價率與 `now_followup` 不變。
- [X] T023 [P] [US2] 在 `tests/contract/test_cli_backtest_rule.py` 加上：
  - `--rule 3.0.0 --wait-cost 10,20`：兩份結果檔，除了決策相關欄位以外，預測部分相同。
  - `--wait-cost` 搭配 `--rule 2.0.0`：結束代碼 1，訊息「規則 2.0.0 不使用等待成本」。
  - `--wait-cost -1` 與 `--wait-cost abc`：結束代碼 1。
  - 摘要有 `follow_advice_monthly`、淨效益平均、`longer_horizon`；多個 c 時摘要是清單。
- [X] T024 [US2] 實作 `src/steamsage/cli.py` 與 `src/steamsage/commands.py` 的 `backtest-rule --wait-cost`。
- [X] T025 [P] [US2] 在 `tests/unit/decision/test_compare_rule.py` 加上：
  - **一致性**：
    - 多個候選時，資料集識別、截止時間、切分、模型與參數必須相同。
    - 偏好只比較共有的鍵，`soon_sales` 不同就拒絕。
    - 規則版本可以不同。
  - **淨效益表**：
    - 差距只算兩邊都有 case 的決策。
    - 以候選的 c 計算；兩種模式都有。
    - 95% 區間依遊戲成對重抽樣 2,000 次，種子由資料集識別碼決定，重跑相同。
  - **判定**：只有在「兩份都是驗證組、候選 c 等於 `Preferences` 在程式中的預設值（20，不是設定檔當下的值）、每月重新評估」時
    才有 `verdict`；區間下限 > 0 為 pass，否則 fail。使用者把設定檔改成其他 c，不改變判定用的 c。
  - **次數**：
    - 驗證組加 `--record` 時必須有 `--attempt`，範圍 1–3；第 2、3 次必須有 `--change`。
    - 同一候選規則版本的第 N 次已存在時拒絕。
    - 標題為「規則驗證組比較（sweet-price 3.0.0）第 N 次」。
  - **願望清單差異**：
    - 2.0.0 的建議用 `option_value` 評估期望淨效益。
    - 列出兩邊的期望淨效益，以及放寬範圍時的款數。
- [X] T026 [US2] 實作 `src/steamsage/decision/compare_rule.py` 與 CLI 的 `compare-rule 基準 候選 [候選…] [--attempt N] [--change 說明]`
  （contracts/cli.md）。沿用 004 的紀錄格式，並附上淨效益表與判定。
- [X] T027 [P] [US2] 在 `tests/contract/test_rule_no_leak.py` 加上：
  - 每月重新評估時，竄改 t0 之後的價格，t0 當時的決策不變，只有計分改變。
  - 偷看 t0 之後價格的決策函式，測試要能抓到。
- [X] T028 [US2] **調參組並列**（quickstart D）：
  1. `backtest-rule --rule 2.0.0 --split tuning`
  2. `backtest-rule --rule 3.0.0 --wait-cost 0,10,20,30,50,80 --split tuning`
  3. `compare-rule … --record`

  - 和 research R0.1 的原型對照，平均淨效益差距應在 ±1 以內；超出時先找出原因。
  - 記錄實際耗時。
  - **checkpoint**：向使用者報告調參組的並列結果。
- [X] T029 [US2] **驗證組判定第 1 次**（quickstart E）：只在 T028 報告完成、c 仍為 20 時執行。
  1. `backtest-rule --rule 2.0.0 --split validation`
  2. `backtest-rule --rule 3.0.0 --wait-cost 0,10,20,30,50,80 --split validation`
  3. `compare-rule … --record --attempt 1`

  **停下來**把判定、並列表與願望清單差異交給使用者，由使用者決定換不換（FR-015）。
  - 使用者決定之後，用 `compare-rule … --decision "…"` 把決定附加到比較文件（FR-018）；換版與不換版都要記錄。
  - 未通過時，由使用者決定是否修改設計再試。第 2、3 次要 `--change`，最多 3 次。

**Checkpoint**：commit，並向使用者報告。

---

## Phase 6: User Story 4 — 換上新規則後，文件與數字一致（P2）

**只有 T029 通過硬門檻、而且使用者同意時才做 T030–T032；否則做 T033。**

- [X] T030 （跳過：驗證組未通過硬門檻，使用者 2026-09-26 決定不換版）[P] [US4] 在 `tests/unit/decision/test_rule_backtest_doc.py` 加上：
  - `RULE_BACKTESTS` 的每一筆都有 `wait_cost_twd`。
  - 3.0.0 那一筆的 c、到價率與 `now_deeper_within_12m`，必須能在模型定義「規則回測（sweet-price 3.0.0 …）」一節找到。
- [X] T031 （跳過：驗證組未通過硬門檻，使用者 2026-09-26 決定不換版）[US4] 換版：
  1. `CURRENT_RULE = "3.0.0"`。
  2. 在完整資料集上執行 `backtest-rule --rule 3.0.0`（c = 20），把 `report_figures` 加進 `RULE_BACKTESTS`。
  3. 在 `docs/model/model-definition.md` 更新：
     - 現行規則表
     - 規則 3.0.0 一節，含完整資料集的規則回測、兩種照建議買與淨效益
     - 版本歷史
  4. 確認 T030 通過。
  5. 確認報告的限制提示數字來自 3.0.0 那一筆（spec FR-022），比較文件已有 T029 附加的使用者決定。
- [X] T032 （跳過：驗證組未通過硬門檻，使用者 2026-09-26 決定不換版）[US4] 真實報告（quickstart F、G）：
  1. `uv run steamsage report --open`：頁首是 3.0.0，比較基準有「規則 sweet-price 2.0.0 → 3.0.0」。
  2. 用 `SendUserFile` 把 `data/reports/latest.html` 交給使用者。
  3. 暫時把 c 改成 30 檢查註明與「不引用到價率」，完成後改回 20。
- [X] T033 [US4] 不換版時（quickstart H）：
  - 現行規則維持 2.0.0。
  - 比較文件附上使用者的決定。
  - 模型定義記錄 3.0.0 的設計、原型與判定，標明「未採用」。

**Checkpoint**：commit，並向使用者報告。

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T034 [P] `docs/model/model-definition.md`：規則 3.0.0 一節（不論是否換版都要寫）。
  - 規則：R1 的步驟與公式。
  - 參數與依據：
    - `wait_cost_twd` = 20，**使用者偏好**，依據是 R0.1 與 R0.6。
    - `miss_price`，規則常數，依據是 R2。
    - 甜蜜時點的定義，依據是 R3。
  - 原型結果：R0 的主要表格。
  - 已知限制：R12 的 5 點。
  - 評分框架加上「每月重新評估」與「淨效益」的定義。
- [X] T035 [P] `README.md`：
  - 偏好 `wait_cost_twd` 的意義與修改方式。
  - `report --rule`、`backtest-rule --wait-cost`，以及 `compare-rule` 的多候選與次數。
- [X] T036 [P] `specs/005-waiting-cost/validation.md`：逐項驗收 SC-001–SC-008，附實測耗時與真實資料的輸出摘要。
  功能測試與「新規則是否較好」分開寫。
- [X] T037 `HANDOFF.md` 改寫給下一個 feature：
  - 現況數字。
  - 候選方向：放寬 12 個月範圍（依據 R0.4）、非季節折扣、遊戲年齡、到期前機率偏樂觀的校準（R0.2）、版本追蹤、Chrome 擴充功能、以實際購買結果校準。
  - 本 feature 的教訓。
- [X] T038 收尾：
  1. 跑 `uv run pytest`，應全部通過。
  2. 更新專案記憶（`feature005-decisions`、`steamsage2-rewrite-goals` 的現況）。
  3. commit，並詢問使用者是否合併到 master。

---

## Dependencies & Execution Order

- **Phase 1 → Phase 2 → US1 → US3 → US2 → US4 → Polish**。
- **US3 依賴 US1**：報告需要 3.0.0 的決策輸出。
- **US2**：
  - T021–T027 只依賴 Phase 2 與 T009，可以和 US3 並行開發。
  - 真實資料的 T028 依賴 T020 使用者看過報告；T029 依賴 T028。
- **US4**：
  - T030 可以提前寫。
  - T031–T032 依賴 T029 通過而且使用者同意。
- **Polish**：T034 在 T029 之後（要寫判定結果）；其他在 US4 之後。

**使用者決策點**（實作會停下來等）：

| 任務 | 等什麼 |
|---|---|
| T020 | 版面與措辭 |
| T028 | 調參組結果 |
| T029 | 換不換；未通過時是否再試 |

## Parallel Opportunities

- **Phase 2**：T002、T004、T005、T006 是不同的測試檔，可以同時寫；實作 T003 → T007 依序。
- **US1**：T008、T010、T012、T013 可以同時寫；實作 T009 → T011 → T014 依序。
- **US2 與 US3**：T017、T019、T021、T023、T025、T027 是不同的測試檔，可以並行。
- **Polish**：T034–T036 可以並行。

```text
# US1 測試並行
T008 tests/unit/decision/test_rule_v3.py
T010 tests/integration/test_decision_engine.py
T012 tests/contract/test_rule_no_leak.py
T013 tests/contract/test_cli_report.py
```

## Implementation Strategy

1. **MVP = US1 + US3**：
   - 規則 3.0.0 和原型逐案一致，原因可以讀懂。
   - 預覽報告交給使用者（T020）。這時已經可以用 `report --rule 3.0.0` 看願望清單。
2. **US2**：調參組並列 → 使用者 → 驗證組第 1 次 → 使用者決定。這是換版的硬門檻。
3. **US4**：換版與報告。沒有換版時，只記錄結果。
4. **每個 checkpoint**：跑測試、在真實資料上執行、commit、報告。
