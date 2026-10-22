---

description: "Task list for feature 004: deeper-discount model"
---

# Tasks: 能預測更深折扣的模型

**Input**：`specs/004-deeper-discount-model/` 的 plan.md、spec.md、research.md、data-model.md、contracts/、quickstart.md

**Tests**：憲章要求核心邏輯測試先行。每個實作任務前都有對應的測試任務：先寫測試並確認它會失敗，再實作。

**Organization**：依使用情境分組：

| 情境 | 內容 | 優先 |
|---|---|---|
| US1 | 新模型 `seasonal-record`：預測看得到「比過去更深」 | P1 |
| US2 | 調參組網格、驗證組比較 | P1 |
| US3 | 規則 2.0.0、規則回測並列、照建議買、願望清單差異 | P2 |
| US4 | 換版：`notes`、規則回測對照表、報告用語、現行模型與規則 | P2 |

## Format: `[ID] [P?] [Story] Description`

- **[P]**：可以並行（不同檔案，也不依賴未完成的任務）
- **[Story]**：所屬的使用情境（US1–US4）
- 路徑都相對於 repo 根目錄

## 共用約定（每個任務都適用）

- **驗證組**：在 T021 之前，任何指令、腳本或測試**都不得**對真實資料的驗證組計分或列印驗證組的分數（spec FR-013）。
  真實資料上只能跑 `--split tuning` 或 `--split all` 的預測（`forecast`、`report`）。
- **切分**：鹽固定為 `steamsage-004-split`。
  `part(app) = int(sha256(f"{salt}:{app}").hexdigest()[:8], 16) % 2`，0 = `tuning`，1 = `validation`（research R4）。
- **模型結構常數**（research R1），只寫在 `src/steamsage/forecast/models/seasonal_record.py` 與模型定義：
  - M 組：淺於 -50%、-50% 到 -70%、-75% 到 -85%、-90% 以上
  - s 組：0、1、2–3、4 以上；s 的上限 4
  - 創新低機率的加法平滑強度 a = 20，和原型相同；J 的上限 5 級；J 的分布至少 20 次
- **規則常數**：`P_MIN_MONTHS` 只寫在 `src/steamsage/decision/rule.py` 與模型定義（憲章 V）。
- **分層**：`steamsage.report` 只接受決策契約的 dict（憲章 VII）。
- **CLI**：新指令與新參數都唯讀、不取寫入鎖，只寫 `data/backtests/`；加上 `--record` 時才寫 `docs/model/comparisons.md`，只附加。
- **文字**：使用者看得到的文字用繁體中文。
- **Checkpoint**：每完成一個，就跑 `uv run pytest`、commit（附 attribution trailer），並向使用者報告。要在真實資料上執行，不能只看測試。

---

## Phase 1: Setup

- [X] T001 在 `tests/forecast_builders.py` 新增模型測試用的工具（不碰資料庫）：
  - `outcomes(cuts, region="TW", first_year=2019)`：依序產生 `SaleOutcome`，季節輪替、名稱像「2019 夏特」。
  - `evidence(cuts_by_region, as_of=…, target="TW", app_id=1)`：產生 `GameEvidence`。
  - `population(histories, as_of=…, target="TW")`：`histories` 是 `{app_id: {"TW": [cuts], "US": [cuts]}}`，產生 `PopulationView`。
  - `future_points(n)`：產生 n 個 `SalePoint`。

---

## Phase 2: Foundational（所有使用情境的前提）

**⚠️ 這個階段完成前，不開始任何使用情境。**

- [X] T002 [P] 在 `tests/unit/forecast/test_split.py` 寫切分的測試：
  - 同一 app 每次結果相同。
  - 列出 3 個固定 app 的預期組別：1091500、1245620、413150。預期值用規則直接算出後寫死。
  - 1–5,000 的 app 中，兩組的比例在 45%–55% 之間。
  - 鹽不同時結果不同。
- [X] T003 在 `src/steamsage/forecast/backtest/split.py` 實作 `SALT`、`part(app_id)`、`select(apps, split)`（`all`、`tuning`、`validation`；
  其他值拋出 `ValueError`），讓 T002 通過
- [X] T004 [P] 在 `tests/unit/forecast/test_dataset.py` 新增資料集切分的測試（人工資料庫）：
  - `build_dataset(split="all")` 的識別碼和改動前完全相同：先用現有程式算出人工資料庫的識別碼，寫死在測試中。
  - `tuning` 與 `validation`：
    - `apps` 只含該組，`population_apps` 是全部合格遊戲。
    - 兩組沒有重疊，合起來等於 `all`（SC-004）。
    - 識別碼和 `all` 不同，兩組彼此也不同。
  - 只改動「不在驗證組」的某款遊戲的序列時，驗證組的識別碼也改變，因為整體比例會變。
  - `apps_limit` 在切分之後才套用。
- [X] T005 實作資料集切分，讓 T004 通過：
  - `src/steamsage/forecast/backtest/dataset.py`：`RegionDataset.population_apps`、`BacktestDataset.split`、
    `build_dataset(…, split="all")`。
  - 識別碼：`split` 不是 `all` 時，header 加上 `split` 與 `salt`，雜湊內容改成全部合格遊戲的序列（research R4）。
  - `src/steamsage/forecast/backtest/runner.py`：
    - 整體比例改用 `population_apps` 中當時存在的遊戲，計分仍只用 `apps`。
    - 結果的 `dataset.split` 與 `regions[R].population_games`。
    - `split = all` 的結果和改動前完全相同：既有的 `tests/integration/test_backtest_runner.py` 不變而且通過。
- [X] T006 [P] 在 `tests/unit/forecast/test_metrics.py` 新增 `deeper_than_past` 與 `by_own_sales` 的測試（人工單位，手算）：
  - `deeper_than_past`：只計「本身至少 1 場，而且 d > 最深折扣」的單位，每款遊戲同權重，附校準表。
  - `by_own_sales`：依分析時點的場數分成 0、1、2、3 以上。
  - 沒有任何合格單位時，Brier 為 null、遊戲數為 0。
- [X] T007 實作新分組，讓 T006 通過：
  - `src/steamsage/forecast/backtest/metrics.py`：`RegionMetrics.add(…, own_sales=, past_max=)`。
  - `src/steamsage/forecast/backtest/runner.py`：從 `game_evidence` 算出本身已結束的場數與最深折扣，傳給 `add()`。
  - 結果加上 `regions[R].deeper_than_past` 與 `by_own_sales`（contracts/results-and-decisions.md）。
- [X] T008 [P] 在 `tests/unit/forecast/test_seasonal_freq.py` 新增：`predicts_deeper is False`，
  `deeper_caveat == "長期最低價可能更低：目前的模型無法預測比過去更深的折扣"`
- [X] T009 在 `src/steamsage/forecast/models/base.py`（Protocol 加上 `predicts_deeper`、`deeper_caveat`）與
  `src/steamsage/forecast/models/seasonal_freq.py` 實作，讓 T008 通過
- [X] T010 [P] 在 `tests/contract/test_cli_backtest.py` 新增 `--split`：
  - 摘要與結果檔有 `split`。
  - `tuning` 的遊戲數小於 `all`。
  - 不合法的值：argparse 錯誤。
- [X] T011 在 `src/steamsage/cli.py`、`src/steamsage/commands.py` 加上 `backtest --split`，讓 T010 通過

**Checkpoint**：切分、資料集、新分組、介面屬性完成。

- 真實資料：`uv run steamsage backtest --split all` 的兩區 Brier 與識別碼要和 002 相同（0.1049、0.1791；`d547c29d…`、`75b6da34…`），
  並記下新分組的現行模型分數。
- 跑 `uv run pytest`，commit，向使用者報告。

---

## Phase 3: User Story 1 — 預測看得到「比過去更深」的可能（P1）🎯 MVP

**Goal**：`seasonal-record` 1.0.0 對一般信心的遊戲給出比過去更深的非零機率，原因寫出證據；曲線合法；不洩漏。

**Independent Test**：人工資料上，contracts/model-api.md 的 6 項保證、原因與 evidence 都和手算一致；洩漏測試通過，而且抓得到偷看的變體。

- [X] T012 [P] [US1] 在 `tests/unit/forecast/test_seasonal_record.py` 寫測試，每一項都附手算值：
  1. **參數**：
     - `min_sales` 必須是 ≥ 1 的整數，`half_life` ≥ 0，`hazard_history` ∈ {TW, TW+US}。
     - 未知參數拒絕。
     - CLI 字串可以轉換，例如 `half_life="2"`。
     - `tw_only_params == {"hazard_history"}`。
  2. **低信心路徑**：本身少於 `min_sales` 場時，輸出（機率、信心、原因、evidence）和同一 `min_sales` 的 `seasonal-freq` 逐位相同（保證 1）。
  3. **退化**：`half_life=0` 而且機率表為空（population 沒有任何「之前已有 `min_sales` 場」的樣本）時，
     一般信心的機率和 `seasonal-freq` 逐位相同（保證 2）。
  4. **近期加權**：cuts = [50, 50, 70]、`half_life=2`：
     - 權重是 0.5^1、0.5^0.5、1。
     - p_w(70) = 1 / (0.5 + 0.7071 + 1)。
  5. **狀態**：
     - cuts = [55, 60, 65, 65, 65, 65, 70]：m5 = 70，s = 0，`record_sale` 是最後一場。
     - cuts = [70, 50, 70, 60]：m5 = 70，s = 3，從首次達到算起。
     - s 上限 4。
     - `max_cut = 67` 時 m5 = 65。
  6. **機率表**：
     - 格子的計數與比例和手算一致。
     - 加法平滑（a = 20）：手算一例，例如格子 10 場 5 次、M 組 100 場 20 次、全體 1,000 場 150 次
       → M 組比例 = (20 + 20 × 0.15) / 120 = 0.19167，h = (5 + 20 × 0.19167) / 30 = 0.29444。
     - 全體為 0 時 h = 0，`hazard_basis = "none"`。
     - m5 = 95 時 h = 0。
     - J 的分布：某組少於 20 次時改用全體；J 上限 5 級。
  7. **區域**：
     - `hazard_history=TW` 只用台灣區；`TW+US` 合併兩區的樣本。
     - 美國區目標一律只用美國區。
     - `hazard_regions` 正確。
  8. **狀態鏈**：
     - 固定 h = 0.2、J 必為 1 級、M = 60：
       - P(最深 ≥ 65，1 場) = 0.2；2 場 = 1 − 0.8² = 0.36。
       - P(最深 ≥ 70，2 場) = 0.2 × 0.2 = 0.04。
     - h 隨 s 改變時，再手算一個 3 場的例子。
  9. **交界單調**：P(≥ M，k 場) ≥ P(≥ M+5，k 場)；隨機產生 200 組歷史，全部通過 002 的 `validate_curve`（保證 4）。
  10. **共用倒推表**：
      - 同一 `prepare()` 之後多款遊戲的結果，和每款各自新建模型、各自 `prepare()` 的結果相同。
      - 倒推表只建一次（保證 5）。
  11. **更深的機率 > 0**：一般信心、M < 95、h > 0 時，d = M + 5 的第 1 場機率 > 0（保證 3）。
      - 逐場加深的例子（-55 → … → -70）的下一場 ≥ -75% 機率，大於一直是 -50% 的例子的 ≥ -55%（US1 情境 1、2）。
  12. **原因與 evidence**：
      - 原因依 contracts/model-api.md 的 6 行格式。
      - 樣本不足時寫明改用的範圍；表為空時寫明。
      - evidence 有 `record_sale`、`since_record`、`hazard`、`hazard_basis`、`hazard_regions`、`half_life`、`recent_direction`，
        以及沿用的鍵。
  13. **介面屬性**：`predicts_deeper is True`，`deeper_caveat` 含 `{now_deeper_within_12m}`。
  14. **折扣變淺**（spec FR-003）：cuts = [70, 70, 50, 50]、`half_life=2`：
      - 下一場 ≥ -70% 的機率小於不加權時的 0.5，手算加權比例。
      - `recent_direction = "shallower"`，原因第 3 行寫「變淺」。
  15. **本身只有 1 場**（`min_sales=1`，spec Edge Cases「本身歷史很短」）：
      - cuts = [50]：≥ -50% 的每場機率是 1，所以累積機率為 1。
      - ≥ -55% 的機率等於狀態 (50, 0) 的創新低鏈，來自機率表，不是 0 也不是 1。
      - `recent_direction` 為 null，原因不寫方向。
  16. **從沒打折過**（spec Edge Cases）：cuts = [0, 0, 0]：
      - m5 = 0、s = 2。
      - ≥ -5% 以上的等級都來自創新低鏈，機率 > 0，而且不出錯。
      - 原因寫「過去季節特賣都沒打折」。
- [X] T013 [US1] 在 `src/steamsage/forecast/models/seasonal_record.py` 實作 research R1，讓 T012 通過：
  - `@register`，繼承不必要，但低信心路徑必須呼叫同一份 `seasonal-freq` 的邏輯，確保逐位相同。
  - 倒推表在第一次 `predict()` 時依點數建立，`prepare()` 時清空。
  - 在 `src/steamsage/forecast/models/__init__.py` 匯入註冊，`CURRENT_MODEL` 不變。
- [X] T014 [P] [US1] 洩漏測試：
  - 在 `tests/contract/test_no_future_leak.py` 把 `test_tampering_after_as_of_changes_nothing` 參數化，加上 `seasonal-record` 的
    `{min_sales: 1, half_life: 2, hazard_history: TW+US}` 與 `{min_sales: 2, half_life: 0, hazard_history: TW}`。
  - 新增 `RecordPeeker`：繼承 `seasonal-record`，`prepare()` 另外從資料庫讀取**分析時點之後**才結束的季節特賣加入機率表。
    斷言兩個資料庫的結果不同，證明測試抓得到（FR-007）。
  - 延伸 `test_backtest_truncation_equals_loading_at_as_of`，加上新模型。
- [X] T015 [P] [US1] 新增 `scripts/feature_analysis.py`（唯讀）：在**調參組**上重現 research R0.1 的特徵表。
  - 表格：依 M 組、距上次創新低、距上次達到、趨勢、場數分組的創新低比例與場數；加深級數的分布。
  - 輸出 Markdown 到 stdout，供模型定義引用（FR-004）。
  - 在真實資料上執行，數字應和 R0.1 相同。
- [X] T016 [US1] 真實資料驗收（quickstart B），寫進 `specs/004-deeper-discount-model/validation.md` 的 US1 一節：
  1. **願望清單預測**：`forecast --model seasonal-record --param min_sales=1 --param half_life=2 --param hazard_history=TW+US`：
     - `model-error` 為 0。
     - 抽查 Cyberpunk 2077、柏德之門3、PRAGMATA、一款只有 1 場紀錄的遊戲，檢查原因與機率。
     - 記錄耗時。
  2. **調參組回測**：`backtest --split tuning`，現行模型與上述參數各一次。
     - 兩區 Brier 和 research R0.2 的原型差距在 ±0.001 內；超過時找出原因並記錄。
     - 記錄 `deeper_than_past`、`by_own_sales` 與耗時。

**Checkpoint**：新模型完成，調參組上和原型一致。跑 `uv run pytest`，commit，向使用者報告。

---

## Phase 4: User Story 2 — 在沒調過參數的遊戲上公平比較（P1）

**Goal**：在調參組上依 FR-011 選參數，在驗證組上依 FR-029 判定，最多 3 次，全部記錄。

**Independent Test**：以人工回測結果 dict 驗證選參數規則、美國區重用、次數限制與紀錄格式；CLI 在人工資料庫上端到端執行。

- [X] T017 [P] [US2] 在 `tests/unit/forecast/test_grid.py` 寫網格的測試：
  - `expand(grid)` 產生笛卡兒積，順序固定。
  - 美國區重用：只差 `tw_only_params` 的設定共用同一次美國區結果。
  - 選參數：
    - 排除美國區差距 95% 區間下限 > 0 的設定。
    - 從剩下的設定中選台灣區 Brier 最低的；同分時選網格順序在前的。
    - 全部被排除時回傳 None。
    - 第 3 步（spec FR-011）：
      - 選中的設定 `min_sales=1`，而且它的 `by_own_sales`「1」組台灣區 Brier 比現行模型同一組差時，改選 `min_sales ≥ 2` 中最好的，
        並回傳原因。
      - 不比現行差時維持原選擇。
  - `--split validation` 拒絕。
  - `format_grid_record()`：標題「調參組網格」，每個設定一列，選中的設定標示出來。
- [X] T018 [US2] 實作網格，讓 T017 通過：
  - `src/steamsage/forecast/backtest/grid.py`：`expand`、`run_grid`（呼叫 `run_backtest`，每個結果檔照常寫入）、`select`、`format_grid_record`。
  - `src/steamsage/cli.py`、`src/steamsage/commands.py`：`steamsage grid`（contracts/cli.md）。
- [X] T019 [P] [US2] 比較次數的測試：
  - `tests/unit/forecast/test_compare.py`：
    - 兩份結果的 `split` 不同時拒絕。
    - 驗證組紀錄：
      - 缺少 `--attempt` 時拒絕；N 不在 1–3 時拒絕。
      - 比較文件中已有同一候選模型名稱的第 N 次紀錄時拒絕。
      - 第 2、3 次缺少 `--change` 時拒絕。
      - 標題是「（驗證組 · 第 N 次）」，含 `--change` 的說明。
    - 兩份結果都有 `deeper_than_past` 時，紀錄多一列。
    - 舊結果檔（沒有新欄位）照常比較，紀錄格式和 002 相同。
  - `tests/contract/test_cli_compare.py`：CLI 參數與結束代碼。
  - `tests/contract/test_cli_grid.py`：人工資料庫上 2 個設定的網格，檢查摘要、結果檔數、`--record`、結束代碼。
- [X] T020 [US2] 在 `src/steamsage/forecast/backtest/compare.py`、`src/steamsage/cli.py`、`src/steamsage/commands.py` 實作，讓 T019 通過
- [X] T021 [US2] **真實資料：調參組網格**（quickstart C）：
  `grid --model seasonal-record --grid min_sales=1,2 --grid half_life=0,2,4 --grid hazard_history=TW,TW+US --split tuning --record`。
  - 記錄耗時與選中的設定，寫進 validation.md。
  - `grid` 會自動套用 FR-011 第 3 步（「本身只有 1 場」這一組不得比現行差）。validation.md 列出這一組兩邊的 Brier。
  - **Checkpoint：向使用者報告網格結果，確認後才進行 T022。**
- [X] T022 [US2] **真實資料：驗證組比較第 1 次**（quickstart D）：
  - 現行模型與選中的設定各跑 `backtest --split validation`。
  - `compare … --record --attempt 1`。
  - 判定寫進 validation.md。
  - 「未優於」時：
    - 向使用者報告原因。
    - 經同意後才修改設計並進行第 2 次（`--attempt 2 --change "…"`），最多 3 次。
    - 3 次都沒通過時，跳過 US4 的換版任務（T034–T035）。T032–T033（`notes`）仍然要做（FR-027）。

**Checkpoint**：比較文件中有網格與驗證組比較的紀錄。跑 `uv run pytest`，commit，向使用者報告判定。

---

## Phase 5: User Story 3 — 看到換模型對決策的實際影響（P2）

**Goal**：規則 2.0.0。規則回測可以指定模型、規則與切分，並有照建議買、事後最低價、甜蜜時點分布；`compare-rule` 並列並列出願望清單差異。

**Independent Test**：人工曲線與人工價格序列上，規則 2.0.0、照建議買、並列差距都和手算一致；CLI 在人工資料庫上端到端執行。

- [X] T023 [P] [US3] 在 `tests/unit/decision/test_rule_v2.py` 寫規則版本的測試：
  - `RULES` 有 `1.0.0`（`p_min_months=None`）與 `2.0.0`（`p_min_months=12`）；`CURRENT_RULE == "1.0.0"`（換版前）。
  - `decide(…, rule="2.0.0")`：一般信心也只用結束時間 ≤ 分析時點 + 12 個月的時點。
    - 手算一例：5 年曲線的 P_min 是 -85%，12 個月內是 -75%。
    - `horizon_points` 正確。
    - 甜蜜時點不會超過 12 個月。
  - `decide(…, rule="1.0.0")` 的結果和改動前完全相同：`tests/unit/decision/test_rule.py` 全部不改而且通過。
  - `RuleResult` 與決策契約的 `rule.constants` 帶有 `p_min_months`。
- [X] T024 [US3] 實作規則版本，讓 T023 通過：
  - `src/steamsage/decision/rule.py`：`RULES`、`CURRENT_RULE`、`decide(…, rule=CURRENT_RULE)`、`horizon()` 依規則，`CONSTANTS` 依版本。
  - `src/steamsage/decision/engine.py`：規則 2.0.0 的原因用「12 個月內最低價」、範圍寫「未來 12 個月（到某場特賣）」；1.0.0 的用語不變。
  - `src/steamsage/report/html.py`：依契約的 `rule.constants.p_min_months` 選欄位名稱（「長期最低」或「12 個月內最低」）與偏好說明中的用語。
  - `tests/unit/report/test_html.py`：兩種用語各一個測試。
- [X] T025 [P] [US3] 在 `tests/unit/decision/test_follow_advice.py` 寫照建議買的測試（人工價格序列，逐案手算，research R6）：
  1. **判為現在買**：多省 0、等 0 天。
  2. **30 天後出現 -60%**（甜蜜 -50%）：以 -60% 那個狀態的原價 × 40% 買，無條件捨去到分；等 30 天。
  3. **12 個月內沒到價、12 個月那刻是 -20%**：以 -20% 買，等 365 天。
  4. **資料只到 200 天、還沒到價**：截斷。
  5. **資料只到 200 天、第 100 天已到價**：照常計入。
  6. **原價在期間上漲**：多省為負數。
  7. **事後最低價**：只算有完整 12 個月資料的決策。
  8. **彙總**：依分組與信心；平均、中位數、75 與 90 百分位（最近排名法，沿用 003 的 `_nearest_rank`）；台幣以元四捨五入。
  9. **甜蜜時點分布**：下一場、1 年內、1 年以上。
- [X] T026 [US3] 在 `src/steamsage/decision/backtest.py` 實作，讓 T025 通過：
  - `follow_advice`、`hindsight`、`sweet_timing`。
  - `run_rule_backtest(…, rule=, split=)`。
  - 結果的 `rule.version`、`dataset.split`（contracts/results-and-decisions.md）。
  - `decisions_at` 傳入規則版本。
- [X] T027 [P] [US3] CLI 與洩漏：
  - `tests/contract/test_cli_backtest_rule.py`：`--model`、`--param`、`--rule`、`--split`；摘要的新欄位；未知規則版本時結束代碼 1。
  - `tests/contract/test_rule_no_leak.py`：參數化，加上 `seasonal-record` × 規則 2.0.0。
- [X] T028 [US3] 在 `src/steamsage/cli.py`、`src/steamsage/commands.py` 實作 `backtest-rule` 的新參數，讓 T027 通過
- [X] T029 [P] [US3] 在 `tests/unit/decision/test_compare_rule.py` 寫並列的測試：
  - 資料集識別、截止時間或偏好不同時拒絕，並說明哪裡不同。
  - 各指標的並列值與差距和手算一致：到價率、截斷、超出窗口、時間誤差、甜蜜時點分布、現在買的後續、照建議買、事後最低價。
  - `wishlist_diff(batch_a, batch_b)`：純函式，輸入兩份決策。
    - 輸出各組款數、改變分組的遊戲（名稱、前後分組、甜蜜價與時點）、甜蜜價的平均變化。
    - 只有一邊可預測的遊戲另列。
  - `format_rule_record()`：標題「規則回測並列：A vs B」；`--decision` 附在後面。
- [X] T030 [US3] 實作並列，讓 T029 通過：
  - `src/steamsage/decision/compare_rule.py`：`compare_rule_results`、`wishlist_diff`、`format_rule_record`。
  - `src/steamsage/cli.py`、`src/steamsage/commands.py`：`steamsage compare-rule`。
    - 依結果檔記錄的模型、參數與規則，對現在的願望清單各跑一次 `run_decisions`，非正式執行，不寫紀錄。
    - `--no-wishlist`、`--record`、`--decision`。
  - `tests/contract/test_cli_compare_rule.py`：人工資料庫上端到端執行。
- [X] T031 [US3] **真實資料：規則回測並列**（quickstart E），只有 T022 判定「優於」時才做；否則只在調參組上執行，供記錄：
  1. 在驗證組上跑四個組合的 `backtest-rule --split validation`：現行＋1.0.0、候選＋2.0.0、候選＋1.0.0、現行＋2.0.0。
  2. `compare-rule 現行1.0.0 候選2.0.0 --record`。另外兩個組合的數字列在 validation.md，分開看模型與規則各自的影響。
  3. 記錄耗時。
  4. **Checkpoint：把並列報告、願望清單差異交給使用者決定換不換**，然後 `compare-rule … --decision "…"`。

**Checkpoint**：規則回測並列完成。跑 `uv run pytest`，commit，向使用者報告。

---

## Phase 6: User Story 4 — 換上新模型後，報告自動跟著改變（P2）

**Goal**：
- 模型限制的提示由模型提供，數字依（規則、模型、參數）對照；報告不寫死。
- 使用者同意時換上 `seasonal-record` 與規則 2.0.0，並更新規則回測數字與模型定義。

**Independent Test**：
- 人工決策批次上，`notes` 與 `rule_backtest` 依現行組合正確產生，找不到時不引用。
- 換版後的報告與紀錄帶新版本，和前一份紀錄比較時註明版本改變。

- [X] T032 [P] [US4] `notes` 與對照表的測試：
  - `tests/unit/decision/test_rule_backtest_doc.py`：延伸成檢查 `RULE_BACKTESTS` 的每一筆都能在模型定義中找到日期與各數字。
  - `tests/integration/test_decision_engine.py`：
    - 現行組合有對照時，`rule_backtest` 帶 `model`，`notes` 是填入數字後的 `deeper_caveat`。
    - 沒有對照時，`rule_backtest` 為 null，`notes` 是「規則尚未以現行模型回測」。
    - `predicts_deeper` 為 True 時沒有 `deeper-possible` 標籤與對應原因。
  - `tests/contract/test_decision_contract.py`：`notes` 是字串清單，選用。
  - `tests/unit/report/test_html.py`：
    - 頁首顯示 `notes`。
    - 報告原始碼中不再出現「目前的模型無法預測比過去更深的折扣」這句寫死的文字，只會來自 `notes`。
- [X] T033 [US4] 實作，讓 T032 通過：
  - `src/steamsage/decision/rule.py`：`RULE_BACKTESTS`，把 003 的數字搬成鍵為 `("1.0.0", "seasonal-freq", "1.0.0", {min_sales: 2, history: TW})` 的一筆；
    `lookup_backtest(rule, model)`。
  - `src/steamsage/decision/engine.py`：`notes`、`rule_backtest.model`、`deeper-possible` 依 `predicts_deeper`。
  - `src/steamsage/decision/contract.py`：`DecisionBatch.notes` 與序列化。
  - `src/steamsage/report/html.py`：頁首改讀 `notes`。
  - 這個任務不論是否換版都要做（FR-027）。
- [X] T034 [US4] **換版**，只有 T022 判定「優於」而且 T031 使用者同意時才做：
  - `src/steamsage/forecast/models/__init__.py`：`CURRENT_MODEL = ("seasonal-record", "1.0.0", {選中的參數})`。
  - `src/steamsage/decision/rule.py`：`CURRENT_RULE = "2.0.0"`。
  - 更新 `tests/unit/forecast/test_current_model.py` 與依賴預設值的測試：它們改用明確的 `rule="1.0.0"` 或舊模型，不刪除既有情境。
  - `uv run steamsage backtest-rule`（完整資料集、現行組合）：把數字加進 `RULE_BACKTESTS`，寫進模型定義的「規則回測」一節，舊的一節保留為歷史。
  - `tests/integration/test_report_flow.py`：前一份紀錄是舊模型時，比較說明含「版本或偏好改變」。
  - `uv run steamsage backtest`（完整資料集、兩區、新模型）：
    - 記錄耗時（SC-009，上限 10 分鐘）。
    - 記錄 `by_confidence`、`by_own_sales`、`deeper_than_past`、校準表。
    - 這些是模型定義中新模型「信心等級與回測結果」的數字來源（FR-024，T036）。
- [X] T035 [US4] **真實資料驗收**（quickstart F、G）：
  - `uv run steamsage report --open`：分組款數、抽查 5 款的原因與 `notes`、耗時（SC-006）。
  - 暫時切回舊模型，確認提示恢復、準確率不引用，然後改回來。
  - 用 `SendUserFile` 把 `data/reports/latest.html` 傳給使用者看。

**Checkpoint**：跑 `uv run pytest`，commit，向使用者報告。

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T036 [P] 更新 `docs/model/model-definition.md`：
  - 現行模型與規則。
  - `seasonal-record` v1.0.0 章節：規則、參數與網格（T021）、結構常數與依據（T015 的特徵表）、信心等級與分組分數、已知限制（research R11）。
  - 規則 `sweet-price` 2.0.0：`P_MIN_MONTHS` 與依據（research R0.3）；1.0.0 只供並列比較。
  - 評分框架設定：切分的鹽與規則。
  - 版本歷史。
  - 沒有換版時：只記錄候選與「未優於」的結果，現行不變。
- [X] T037 [P] 更新 `README.md`：`grid`、`compare-rule`、`backtest --split`、`backtest-rule` 的新參數、`compare --attempt`；現行模型與規則。
- [X] T038 [P] 更新 `HANDOFF.md`：
  - 004 的結果。
  - 下一個 feature 的候選：等待成本、非季節折扣、發售前特賣、遊戲年齡、版本追蹤。
  - 專案目標的改變：甜蜜價只看 12 個月。
- [X] T039 完成 `specs/004-deeper-discount-model/validation.md`：
  - SC-001–SC-010 逐項，附證據。
  - quickstart A–I，含 I 的實機洩漏抽查：資料庫副本、2025-06-01 之後的觀測改成 -99%。
  - 實測耗時（SC-009）。
  - 功能測試與準確度分開寫。
- [X] T040 最後檢查：
  - `uv run pytest` 全部通過。
  - 更新專案記憶（feature004-decisions、steamsage2-rewrite-goals）。
  - 詢問使用者是否合併到 master。

---

## Dependencies & Execution Order

- **Phase 1 → Phase 2 → US1 → US2**：US2 的網格需要新模型。
- **US3**：
  - 規則與照建議買（T023–T030）只依賴 Phase 2，可以和 US1、US2 並行開發。
  - 真實資料的並列（T031）依賴 T022 的判定。
- **US4**：
  - T032–T033 只依賴 Phase 2 與 T024，可以提前做。
  - T034–T035 依賴 T022「優於」與 T031 使用者同意。
- **Polish**：在 US4 之後。沒有換版時，在 T031 之後。

**使用者決策點**（實作會停下來等）：T021 之後（網格）、T022 之後（驗證組判定，未優於時是否再試）、T031（換不換）。

## Parallel Opportunities

- **Phase 2**：T002、T004、T006、T008、T010 是不同的測試檔，可以同時寫。實作 T003 → T005 → T007 依序進行（runner 共用）。
- **US1**：T014（洩漏）、T015（特徵分析腳本）可以和 T012–T013 並行。
- **US3**：T023、T025、T027、T029 是不同的測試檔，可以並行；T024 → T026 → T028 → T030 依序。
- **Polish**：T036–T038 可以並行。

```text
# Phase 2 測試並行
T002 tests/unit/forecast/test_split.py
T004 tests/unit/forecast/test_dataset.py
T006 tests/unit/forecast/test_metrics.py
T008 tests/unit/forecast/test_seasonal_freq.py
T010 tests/contract/test_cli_backtest.py
```

## Implementation Strategy

1. **MVP = US1**：新模型在調參組上和原型一致，原因可以讀懂。這時就可以用 `forecast --model seasonal-record` 看願望清單。
2. **US2**：網格 → 使用者確認 → 驗證組第 1 次比較。這是換版的硬門檻。
3. **US3**：並列規則回測 → 使用者決定。
4. **US4**：換版與報告。沒有換版時，只交付 `notes` 的重構與所有紀錄。
5. **每個 checkpoint**：跑測試、在真實資料上執行、commit、報告。
