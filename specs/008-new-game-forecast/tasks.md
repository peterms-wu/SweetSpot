---

description: "Task list for feature 008: new-game and low-confidence forecasts"
---

# Tasks: 新遊戲與低信心的預測

**Input**：`specs/008-new-game-forecast/` 的 plan.md、spec.md、research.md、data-model.md、contracts/、quickstart.md

**Tests**：憲章要求核心邏輯測試先行。每個實作任務前都有對應的測試任務：先寫測試並確認它會失敗，再實作。

**Organization**：依使用情境分組。執行順序：Setup → Foundational → US1（新版本）→ US2（網格、驗證組）→ US3（規則並列）→ US4（換版，條件式）→ US5（文件更正，可以提早做）→ Polish。

| 情境 | 內容 | 優先 |
|---|---|---|
| US1 | 新遊戲與紀錄很少的遊戲，到價機率不再過度樂觀 | P1 |
| US2 | 公平判定新版本是否比較好 | P1 |
| US3 | 看到新版本對決策與願望清單的影響 | P2 |
| US4 | 換上後，報告與引用的數字跟著改變 | P2 |
| US5 | 更正 005 的計分錯誤 | P3 |

## Format: `[ID] [P?] [Story] Description`

- **[P]**：可以並行（不同檔案，也不依賴未完成的任務）
- **[Story]**：所屬的使用情境（US1–US5）
- 路徑都相對於 repo 根目錄

## 共用約定（每個任務都適用）

- **截止時間**：每個回測、網格、規則回測指令都明確加 `--cutoff 2026-09-25`（HANDOFF §7）。
- **本身場數**：分析時點以前、目標區域已結束的季節特賣紀錄數（`len(evidence.sale_history[region])`，和 runner 的 `own_sales` 相同）。
  分組名：`0`、`1`、`2`、`3-5`、`6+`，保留舊的 `3+`。
- **只計已結束的單位**（FR-011）：評分單位對應的實際特賣存在，而且 `series.known_until >= actual.end`。結果 = 第一次達到 d 的時間 < `actual.end`。
- **和過去最深的距離**：M = 本身紀錄的最大折扣（`past_max`）；分組 `M`、`M-5`、`M-10`、`<=M-15`、`M+5`、`>=M+10`。沒有本身紀錄的單位不分這一組。
- **模型 `seasonal-record` 1.1.0**（research R1、R2；contracts/model-api.md）：
  - **參數**：`{min_sales, half_life, hazard_history, low_base, shrink}`。`low_base` ∈ {`population`, `new`, `new-split`}，`shrink` 為 ≥ 0 的數字。
  - **新遊戲序列**：`PopulationView.sale_history` 中每款遊戲在目標區域的紀錄依時間排列。第一場的 `start.date() - release_date <= 365 天` 才保留。發行日未知的不保留。
    - 預購序列：第一場的 `start.date() < release_date`。
    - 已發行序列：其餘的新遊戲序列。
  - **經驗累積** F[k][d]：至少 k 場的序列中，前 k 場最大值 ≥ d 的比例。
    - 序列少於 `MIN_SEQUENCES = 30` 時沿用 k − 1。k = 1 就不足時退回全體每場比例 b(d)，原因寫明樣本不足。
    - 每一列對 k 取累積最大；每一列依 d 取累積最小。
  - **低信心路徑**：
    - `new`：全部新遊戲序列。
    - `new-split`：目標 `release_date > as_of.date()` 用預購序列，否則用已發行序列。發行日未知視為已發行。
  - **收縮**：d ≤ M 時，每場比例 = (n·p_w(d) + a·b(d)) / (n + a)。n 為本身紀錄數，a = `shrink`，b 為 `seasonal-freq` 的整體比例（`_freq._pool`）。
    代入 1.0.0 的累積公式後，每一列依 d 取累積最小。
  - **退化**：`low_base = population`、`shrink = 0` 時，機率、信心、原因與 `evidence` 的既有鍵和 1.0.0 逐位相同。
- **判定**：
  - FR-008：`grid` 排除美國區顯著變差、以及 2／3-5／6+ 任一組台灣區顯著變差的設定，再取台灣區最低。
  - FR-009：002 FR-029，加上 `--target-groups 0,1`，兩組的台灣區 Brier 點估計都較低。
  - 重抽樣：依遊戲成對 2,000 次，種子由資料集識別碼決定。
- **不變**：決策規則 2.1.0、資料庫、`steamsage.forecast/1` 與 `steamsage.decision/2`、002 的 Brier、評分單位與資料集識別碼（SC-004）。
- **對照原型**：正式程式和 `prototype/candidate.py` 對照時，先確認錯誤數為 0，再逐單位比對（HANDOFF §7）。
- **改檔案**：多行修改用 Edit 工具，或 scratchpad 中的 Python 腳本，不用 Bash heredoc 改程式（HANDOFF §6）。
- **Checkpoint**：每完成一個，就跑 `uv run pytest`、commit（附 attribution trailer）並向使用者報告。要在真實資料上執行，不能只看測試。
  網格結果、驗證組判定、換不換版都要停下來等使用者確認。
- **原型輸出**：`prototype/out/` 不進版控。

---

## Phase 1: Setup

- [X] T001 記錄基準：
  - `uv run pytest -q` 的通過數，預期 939。
  - `uv run steamsage backtest --split tuning --cutoff 2026-09-25 --json` 的台灣區與美國區 Brier（0.0630／0.0658）與資料集識別碼（台灣區 `858b3147…`、美國區 `0e03f03e…`）。
  - 寫進 `specs/008-new-game-forecast/validation.md` 的「基準」一節（新檔），供 SC-004 對照。
- [X] T002 [P] 在 `tests/forecast_builders.py` 加上建立 `GameData`／`PopulationView` 時指定發行日的輔助參數（`release_date=`、`release_dates=`），預設 None，不影響既有測試。

---

## Phase 2: Foundational（阻擋後續所有情境）

### 模型登錄表依版本（research R4）

- [X] T003 [P] 測試 `tests/unit/forecast/test_registry_versions.py`：
  - `REGISTRY` 依（名稱、版本）登錄。
  - `build_model(name, params, version=None)` 沒給版本時取最新版本，給了就取那一版。
  - 版本不存在時 `ValueError`，訊息列出可用的版本。
  - `current_model()` 依 `CURRENT_MODEL` 的版本建立。
  - `commands.model_from_args` 接受 `--model seasonal-record@1.0.0`。
  - `grid` 的 `--model` 也接受 `名稱@版本`。
  - `compare.py` 查 `tw_only_params` 時依結果的版本。
- [X] T004 實作登錄表：
  - `src/steamsage/forecast/models/__init__.py`：`register` 以 `(cls.name, cls.version)` 為鍵；`build_model(name, params, version=None)`；`current_model()` 用 `CURRENT_MODEL[1]`。
  - `src/steamsage/commands.py`：`model_from_args` 解析 `@`；第 556 行附近依結果的 `model.version` 重建。
  - `src/steamsage/forecast/backtest/grid.py`：`--model` 可帶版本。
  - `src/steamsage/forecast/backtest/compare.py` 第 46–48 行：依版本查類別。

  T003 通過，既有測試不變。

### 發行日進入模型的輸入（research R3）

- [X] T005 [P] 測試 `tests/contract/test_store_facts_as_of.py`（延伸）：`PriceStore.release_dates(app_ids)`：
  - 一次查詢，取每款最新的 `release_date`（靜態欄位，不看分析時點）。
  - 沒有紀錄或值為 null 時為 None；無法解析的日期也是 None。
  - 結果和逐款 `facts(app, as_of).release_date.value` 一致。
- [X] T006 實作 `PriceStore.release_dates` 於 `src/steamsage/store/query.py`：單一 SQL，依 `retrieved_at DESC, fact_id DESC` 取每款最新一筆。
- [X] T007 [P] 測試 `tests/unit/forecast/test_evidence_release.py`：
  - `GameData.release_date` 由 `load_games` 填入。
  - `game_evidence(...)` 產生的 `GameEvidence.release_date` 等於它。
  - `population_view(...)` 的 `release_dates` 涵蓋傳入 `population_view` 的所有遊戲（包括沒有紀錄的），未知為 None。
  - 既有欄位與行為不變。
- [X] T008 實作：
  - `src/steamsage/forecast/evidence.py`：`GameData.release_date: date | None = None`、`GameEvidence.release_date: date | None = None`、`PopulationView.release_dates: Mapping[int, date | None]`（預設空）；`game_evidence` 與 `population_view` 帶入。
  - `src/steamsage/forecast/engine.py` 的 `load_games`：呼叫一次 `store.release_dates(apps)`。

  四個 `population_view` 的呼叫端（runner、engine、decision/backtest、nonseasonal/backtest）不需要改。

### 回測指標（research R5，FR-011）

- [X] T009 [P] 測試 `tests/unit/forecast/test_metrics_finished.py`，在人工評分單位上手算：
  - `by_own_sales` 多了 `3-5` 與 `6+`，`3+` 仍在而且值不變。
  - `per_game_by_own_sales[app]` = {組名: [單位數, 誤差平方和]}（頂層，和 `per_game` 並列）。
  - `finished_calibration`：`units`、`brier`、`bins`（每 0.1 一組：lo、n、predicted、actual），以及 `groups`：
    - `confidence`
    - `own_sales`（`0`、`1`、`2`、`3-5`、`6+`）
    - `seen`（`seen`／`deeper`）
    - `distance`（`M`、`M-5`、`M-10`、`<=M-15`、`M+5`、`>=M+10`）

    每組有 n、predicted、actual、brier。
  - 加權：`brier` 是每款遊戲同權重（002 慣例）；`n`、`predicted`、`actual` 是逐單位平均（data-model「加權」）。手算測試兩種都驗。
  - **SC-004**：加入新指標前後，同一份輸入的 `brier`、`units` 與既有欄位逐位相同。
- [X] T010 實作：
  - `src/steamsage/forecast/backtest/metrics.py`：新分組與 `finished_calibration`。
  - `src/steamsage/forecast/backtest/runner.py`：
    - 每個窗口時點傳入「是否已結束」：實際特賣存在而且 `known_until >= actual.end`，並附上已結束的結果。
    - 傳入 `past_max`，供距離分組使用。
    - 頂層加 `release_facts = {"count", "known", "sha256"}`：以 (app_id, 發行日) 排序後雜湊，只含資料集與參考資料集的遊戲。
  - 資料集識別碼的計算不動。
- [X] T011 [P] 整合測試 `tests/integration/test_backtest_runner.py`（延伸）：
  - 結果有 `release_facts` 與 `finished_calibration`。
  - 同一份人工資料在加入發行日前後的 `dataset_id` 相同。
  - 1.0.0 的 Brier 不變。
- [X] T012 真實資料：
  - `uv run steamsage backtest --split tuning --cutoff 2026-09-25 --json`。
  - 台灣區、美國區 Brier 與資料集識別碼和 T001 逐位相同；台灣區 `finished_calibration.brier` = 0.0725（每款同權重；逐單位平均為 0.0594，可從 `bins` 驗算；data-model「加權」）。
  - 記錄耗時。
  - **Checkpoint**：pytest、commit、報告。

---

## Phase 3: User Story 1 — 新遊戲與紀錄很少的遊戲，到價機率不再過度樂觀（P1）

**Goal**：`seasonal-record` 1.1.0（low_base、shrink）。

**Independent Test**：contracts/model-api.md 的 8 項保證在人工資料上成立；洩漏測試抓得到偷看的變體；和原型逐單位相同。

- [X] T013 [P] [US1] 測試 `tests/unit/forecast/test_seasonal_record_v110.py`，contracts/model-api.md 的保證 1–7：
  1. 退化：`low_base=population, shrink=0` 和 1.0.0 逐位相同，包括原因與 evidence 的既有鍵。用一般信心、低信心、從沒打折三種人工遊戲。
  2. 只有 1 場 -50%、`shrink=0.5`：第 1 場 ≥ -50% 的機率 = (1·1 + 0.5·b(50)) / 1.5 < 1，手算。
  3. n 越大越接近 p_w。
  4. 人工序列的經驗累積手算。`new-split` 對預購與已發行的目標用不同序列。
  5. 發行日未知的目標視為已發行，參考資料集中發行日未知的遊戲不進序列；序列不足時退回 b(d)，原因寫明。
  6. `validate_curve` 通過，也就是隨時間不遞減、隨折扣加深不遞增，包括收縮後低於倒推機率的那一格。
  7. 美國區目標只用美國區紀錄。

  另外：參數驗證，`low_base` 不在三個值中、`shrink < 0` 或不是數字時拒絕並說明原因。
- [X] T014 [P] [US1] 測試原因措辭 `tests/unit/forecast/test_seasonal_record_v110.py`（同檔，另一組）：
  - 低信心已發行、低信心預購、發行日未知、收縮有作用（本身 ≤ 3 場）、收縮不寫（本身 ≥ 4 場）。
  - 措辭照 contracts/model-api.md；數字來自當時的表格，不是寫死的例子。
  - `confidence_levels()` 的低信心說明寫出新依據。
- [X] T015 [US1] 實作 `src/steamsage/forecast/models/seasonal_record.py`：
  - 新類別 `SeasonalRecordV110(SeasonalRecord)`，`version = "1.1.0"`，登錄。1.0.0 的類別不改。
  - `from_params` 與 `params` 加上 `low_base`、`shrink`；常數 `NEW_GAME_DAYS = 365`、`MIN_SEQUENCES = 30`。
  - `prepare`：
    - 建三組序列。
    - 經驗累積表依（序列組、K）快取。
    - 記下 `as_of` 與目標區域。
  - `predict`：
    - 低信心走新依據，信心仍為 `low`。
    - 一般信心套收縮與累積最小。
    - `evidence` 新增 `low_sequences`（`all-new`／`pre-release`／`released`）、`new_games`、`release_date`、`shrink`、`own_share_raw`。
    - 原因依 T014。
- [X] T016 [US1] 洩漏測試 `tests/contract/test_no_future_leak.py`：
  - 把 1.1.0（`new-split`、`shrink=0.5`）加入參數化。
  - 新增一個偷看的變體：新遊戲序列包含分析時點之後才結束的紀錄。
  - 證明測試抓得到它，而且正式版本通過。
  - 發行日：發行日固定時，竄改分析時點之後的紀錄與價格，預測不變；另一個偷看變體用「分析時點之後才出現的第一場紀錄」判斷新遊戲，MUST 被抓到。
- [X] T017 [US1] 原型對照 `specs/008-new-game-forecast/prototype/t017_parity.py`（新檔）：
  - 調參組、截止 2026-09-25，正式 1.1.0 與 `candidate.py` 用同一組參數：`new-split, 0.5, n, pop` 與 `new, 0, n, pop`。
  - 先確認兩邊錯誤數為 0，再逐評分單位比對機率，差距 < 1e-12。
  - 不同時用逐單位比對找出原因（`p11b_low_change.py` 的寫法）。
  - 結果寫進 validation.md。
- [X] T018 [US1] 真實願望清單抽查（quickstart G）：
  - 指令：`uv run steamsage forecast --model seasonal-record@1.1.0 --param low_base=new-split --param shrink=0.5`（唯讀）。
  - 抽查對象：
    - 2 款低信心遊戲的原因：依據與樣本數
    - Breath of Fire IV 的收縮行
    - 回測時點上 1 款預購遊戲的措辭（用 `forecast --as-of`，或原型挑出的時點）
  - 措辭與數字截圖或摘錄寫進 validation.md。
  - SC-002：清點願望清單每款的狀態（有曲線，或有明確狀態與原因），沒有例外；結果寫進 validation.md。
  - **Checkpoint**：pytest、commit、報告。

---

## Phase 4: User Story 2 — 公平判定新版本是否比較好（P1）

**Goal**：`grid` 加上 FR-004 的排除、`compare --target-groups`；跑網格與驗證組比較第 1 次。

**Independent Test**：人工結果上的排除與判定組合都正確；真實網格和原型一致。

- [X] T019 [P] [US2] 測試 `tests/unit/forecast/test_grid.py`（延伸），用人工結果 dict：
  - 某設定的 `2`／`3-5`／`6+` 任一組在成對重抽樣中顯著變差（下限 > 0）時排除，`excluded_reason = "own-sales-worse:<組名>"`。
  - 用 `per_game_by_own_sales` 成對抽樣，種子由資料集識別碼決定。
  - 違反 spec FR-003 的設定（`shrink = 0`，見過的等級沒有收縮）排除，`excluded_reason = "fr-003"`，仍列在網格中作為對照。
  - 004 的第 3 步只在 `min_sales` 改變時觸發，行為不變。
- [X] T020 [US2] 實作 `src/steamsage/forecast/backtest/grid.py` 的 FR-004 與 FR-003 排除（FR-003 由模型類別提供：`grid_exclusion(params) -> str | None`，1.1.0 在 `shrink == 0` 時回傳 `"fr-003"`；其他模型沒有這個方法時不排除），以及網格紀錄中被排除的原因（沿用 004 的紀錄格式）。
- [X] T021 [P] [US2] 測試：
  - `tests/unit/forecast/test_compare.py`（延伸）：`--target-groups 0,1` 的判定組合。
    - FR-029 通過而且兩組都較低 → 優於。
    - FR-029 通過但任一組不較低 → 未優於，原因寫出是哪一組。
    - FR-029 未通過 → 未優於。
  - 紀錄文字包含：條件說明、各組 Brier、差距、區間，以及只計已結束的「預測平均 − 實際比例」。
  - `tests/contract/test_cli_compare.py`：
    - 不合法的組名是使用錯誤。
    - 驗證組比較次數依候選的（名稱、版本）計算，1.1.0 從第 1 次開始，不和 1.0.0 或 `seasonal-freq` 的紀錄混算。
- [X] T022 [US2] 實作：
  - `src/steamsage/forecast/backtest/compare.py`：`target_groups` 參數、判定與紀錄；次數依版本計算。
  - `src/steamsage/cli.py`／`src/steamsage/commands.py`：`compare --target-groups`。
- [X] T023 [P] [US2] 測試與實作 `backtest` 摘要的新行，只計已結束的 Brier 與預測 ≥ 0.7 的「預測 − 實際」：`tests/contract/test_cli_backtest.py`、`src/steamsage/commands.py`。
- [X] T024 [US2] 在模型定義的「評分框架設定」新增三列，寫明理由與日期（2026-09-26）：`docs/model/model-definition.md`。
  - 只計已結束的校準指標（只報告）。
  - `--target-groups` 的判定條件（本 feature 用 `0,1`）。
  - 發行日作為靜態事實、不在識別碼中，以及 `release_facts`。
- [X] T025 [US2] 真實資料：調參組網格（quickstart C，約 8–10 分鐘）。
  - 指令：`uv run steamsage grid --model seasonal-record@1.1.0 --split tuning --cutoff 2026-09-25 --grid low_base=new,new-split --grid shrink=0,0.25,0.5,1 --record`
  - 和 research R0.3、R0.4 對照，差距 ±0.001 內；不一致時先找原因再報告。`shrink=0` 的兩列只作為對照（FR-003 排除）。
  - **Checkpoint（停下來等使用者）**：網格表、被排除的設定與原因、選中的參數。
- [X] T026 [US2] 使用者確認後：驗證組比較第 1 次（quickstart D）。
  - 兩份 `backtest --split validation --cutoff 2026-09-25`，然後 `compare ... --attempt 1 --target-groups 0,1 --record`。
  - **Checkpoint（停下來等使用者）**：判定、重點兩組、只計已結束的偏差。

---

## Phase 5: User Story 3 — 看到新版本對決策與願望清單的影響（P2）

**Goal**：驗證組的規則回測並列與願望清單差異，交給使用者決定。

**Independent Test**：兩份規則回測的資料集、規則、偏好相同；願望清單差異逐款列出。

- [X] T027 [US3] 真實資料（quickstart E）：
  - `backtest-rule --split validation --cutoff 2026-09-25`，1.0.0 與 1.1.0（選定參數）各一份。
  - `compare-rule <1.0.0> <1.1.0> --record`，包含願望清單差異。
- [X] T028 [P] [US3] 腳本 `specs/008-new-game-forecast/prototype/t028_low_to_now.py`（新檔）：
  - 從兩份結果的 `cases` 與決策，算出「低信心 → 現在買」等分組改變的決策數。
  - 抽 5 個案例逐一解釋（research R0.5 的寫法）。
  - 附加到比較紀錄。
- [X] T029 [US3] **Checkpoint（停下來等使用者）**：
  - 並列表：到價率、現在買的後續、淨效益（評估成本 0–80 與 20）、甜蜜時點分布。
  - 願望清單差異、分組改變的解釋。
  - 使用者決定換不換；決定附加到 `docs/model/comparisons.md`。

---

## Phase 6: User Story 4 — 換上後，報告與引用的數字跟著改變（P2，條件式）

**Goal**：只有 T026 判定「優於」而且使用者在 T029 同意時才做；否則跳到 T034，並在模型定義記錄結果。

**Independent Test**：換版後報告與紀錄使用 1.1.0；程式中的回測常數與模型定義一致。

- [X] T030 [US4] 測試 `tests/unit/forecast/test_registry_versions.py`（延伸）：`CURRENT_MODEL` 是 1.1.0 與選定參數；`current_model()` 回傳 1.1.0；`--model seasonal-record@1.0.0` 仍可切回（FR-016）。
- [X] T031 [US4] 改 `CURRENT_MODEL` 於 `src/steamsage/forecast/models/__init__.py`，註解寫明比較紀錄與使用者同意的日期。
- [X] T032 [US4] 完整資料集規則回測：
  - `uv run steamsage backtest-rule --cutoff 2026-09-25`。
  - 把新的一筆加進 `src/steamsage/decision/rule.py` 的 `RULE_BACKTESTS`。
  - 改寫 `docs/model/model-definition.md` 的規則回測一節，以及決策規則已知限制 3（低信心到價率）。
  - `tests/unit/decision/test_rule_backtest_doc.py` 等一致性測試通過。
- [X] T033 [US4] 真實報告（quickstart F）：
  - `uv run steamsage report --open`，確認頁首與紀錄的模型版本、低信心組的到價率、變動註明模型版本改變。
  - 用 `specs/006-version-tracking/prototype/check_390.py` 檢查，並以 `SendUserFile` 交給使用者。
  - **Checkpoint**：pytest、commit、報告。

---

## Phase 7: User Story 5 — 更正 005 的計分錯誤（P3，和換版無關，可以提早做）

**Goal**：把「到期前達到 96.6% → 84.9%」更正為以實際特賣結束日計分的數字（research R9）。

**Independent Test**：`prototype/p5_compare.py` 重現 96.6% → 89.8%（8,688 個決策），和更正後的文件一致。

- [X] T034 [P] [US5] `specs/005-waiting-cost/research.md` 的 R0.2 表格下方加上「更正（feature 008，2026-09-26）」段落：
  - 原本以分析時點估計的特賣結束日計分；2026 春特估計 3/19 結束、實際 3/26。
  - 以實際結束日計分：96.6% → 89.8%；一般信心本身曲線 97.0% → 91.8%；低信心或沒有本身歷史 81.9% → 9.3%。
  - 期望多省與等待不受影響；規則驗證組的判定也不受影響，因為「照建議買」不看特賣日期。
  - 附原型路徑。
  - 舊表保留不刪。
- [X] T035 [P] [US5] 改寫 `docs/model/model-definition.md`：
  - 「決策規則 v3.0.0」的「原型與正式實作」第 4 點，以及已知限制 1，改成正確的數字與原因（不另寫修正說明，憲章 V）。
  - 版本歷史加一列「2026-09-26 文件更正：3.0.0 已知限制 1 的計分方式」。
- [X] T036 [US5] `docs/model/comparisons.md` 附加一筆「更正：005 R0.2 的選項層級校準（feature 008）」，日期用 UTC，不改舊紀錄。
  然後跑 quickstart H 確認數字一致。
  - **Checkpoint**：commit、報告。

---

## Phase 8: Polish & Cross-Cutting

- [X] T037 `docs/model/model-definition.md`：
  - `seasonal-record` 1.1.0 一節：預測什麼、規則（R1、R2）、參數與網格表、低信心依據的分析（research R0.1、R0.2）、信心等級的分數、校準表（含只計已結束）。
  - 已知限制：
    - 6 場以上在過去最深等級的低估（spec clarify）
    - 發行日事後被改晚（資料庫中 1 款有不同值）
    - 發售前紀錄（沿用限制 8）
    - 美國區預購序列樣本少
    - 1.0.0 已知限制 5 的處理結果
  - 現行模型表與版本歷史（換版時）；沒換版時記錄「候選，未採用」與原因。
- [X] T038 [P] `README.md`：`--model 名稱@版本`、`compare --target-groups`、backtest 摘要的新行。
- [X] T039 [P] `HANDOFF.md`：改寫成 008 結束時的狀態。
  - 現行組合、008 的結果。
  - 下一個方向是 009「使用者指定版本、列出其他購買選項」（使用者已排定）。
  - §3 候選加上「6 場以上在過去最深等級的低估」。
  - 教訓：選項層級計分要用實際特賣日期；等待條件不要用會誤中的字串（例如 "error"）。
- [X] T040 `specs/008-new-game-forecast/validation.md`：SC-001～SC-010 逐項驗收與實測耗時（完整資料集兩區回測、網格、report）。
- [X] T041 最後檢查：
  - `uv run pytest` 全部通過。
  - 更新專案記憶（`feature008-proposal.md` 改寫為完成狀態）。
  - 詢問使用者是否合併（建議 squash，原因寫在報告中）。

---

## Dependencies & Execution Order

- **Setup（T001–T002）** → **Foundational（T003–T012）**：阻擋全部情境。
  - T003/T004（登錄表）、T005–T008（發行日）、T009–T011（指標）三組可以並行。
  - T012 在三組之後。
- **US1（T013–T018）**：需要 T004 與 T008。
- **US2（T019–T026）**：
  - T019–T024 需要 T010 的指標，可以和 US1 並行。
  - T025 需要 US1 完成；T026 需要 T025 與使用者確認。
- **US3（T027–T029）**：需要 T026。
- **US4（T030–T033）**：需要 T026 判定「優於」與 T029 的使用者同意。
- **US5（T034–T036）**：不依賴其他任務，任何時候都可以做。
- **Polish（T037–T041）**：最後。T037 依換不換版決定內容。

## Parallel Example

```text
# Foundational：三組同時開始
T003 test_registry_versions.py   |  T005 test_store_facts_as_of.py  |  T009 test_metrics_finished.py
# US1 與 US2 的測試
T013/T014 test_seasonal_record_v110.py  |  T019 test_grid.py  |  T021 test_compare.py
# 任何時候
T034 005 research 更正  |  T035 模型定義 3.0.0 已知限制 1
```

## Implementation Strategy

1. **MVP = US1 + US2 的網格**（T001–T025）：
   - 新版本完成，並在真實調參組上證明它比 1.0.0 好。
   - 在 T025 把網格交給使用者。
2. **驗證組判定**（T026）與**規則並列**（T027–T029）：每一步都停下來等使用者。
3. **換版**（T030–T033）：只有判定優於而且使用者同意時才做。把真實報告交給使用者看。
4. **文件更正**（T034–T036）：可以在 Foundational 期間就先完成，降低收尾時的工作量。
5. **收尾**（T037–T041）：文件、驗收、記憶，然後詢問是否合併。
