---

description: "Task list for feature 002: backtest harness and baseline model"
---

# Tasks: 回測框架與基準模型

**Input**: `specs/002-backtest-baseline/` 的 plan.md、spec.md、research.md、data-model.md、contracts/、quickstart.md

**Tests**: 憲章要求核心邏輯測試先行。每個實作任務前面都有對應的測試任務：先寫測試、確認它會失敗，再實作。

**Organization**: 依使用情境分組。US1 = 預測曲線，US2 = 回測，US3 = 模型比較，US4 = 信心等級的含義與模型定義。

## Format: `[ID] [P?] [Story] Description`

- **[P]**：可以並行（不同檔案，也不依賴未完成的任務）
- **[Story]**：所屬的使用情境（US1–US4）
- 路徑都相對於 repo 根目錄

## 共用約定（每個任務都適用）

- 時間一律是帶時區的 UTC `datetime`。折扣是 0–100 的整數。等級 `LEVELS = [5, 10, …, 95]`。
- 分析核心只透過 `steamsage.store.query.PriceStore` 讀資料（憲章 VII）；模型不得讀資料庫、檔案或目前時間（contracts/model-api.md）。
- 新的 CLI 指令都是唯讀：不取寫入鎖、不開啟 `StoreWriter`（FR-035）。
- 使用者看得到的文字（原因、摘要、錯誤訊息）用繁體中文。
- 每完成一個 Checkpoint：跑 `uv run pytest`，commit（附 attribution trailer），並向使用者報告。

---

## Phase 1: Setup

- [X] T001 更新 `.gitignore`，加入 `data/backtests/` 與 `data/forecast*.json`。建立空的套件骨架：
  `src/steamsage/forecast/__init__.py`、`src/steamsage/forecast/models/__init__.py`、`src/steamsage/forecast/backtest/__init__.py`，
  以及 `tests/unit/forecast/__init__.py`（若 tests 需要的話）
- [X] T002 [P] 在 `tests/forecast_builders.py` 建立測試用的人工資料建構工具，給後面所有 forecast 測試共用：
  - `write_calendar(path, sales)`：寫出符合 `steam_sales.toml` 格式的 TOML。每筆需要 name、name_zh、kind、season、year、start、end、
    status、https source、confidence。
  - `build_db(db_path, games)`：用 `StoreWriter` 寫入觀測。`games` 描述每款遊戲、每個區域的狀態序列 `[(時間, cut, is_tracking_start)]`、
    來源（`itad-history`／`legacy-itad`／`steam-current`）、台灣區原價、facts（`release_date`、`product_type`）、ITAD 對應狀態。
    另外直接以 SQL 寫入 `history_fetches`（`app_id, source, region, fetched_at, entries`），模擬每款遊戲的最後抓取時間。
  - 美國區觀測的 currency、regular_cents、price_cents 一律是 None。

---

## Phase 2: Foundational（所有使用情境的前提）

**⚠️ 這個階段完成前，不開始任何使用情境。**

- [X] T003 [P] 在 `tests/contract/test_store_series.py` 寫 contracts/store-api-additions.md 的保證事項：
  - `history_known_until(app, region)` = max（該區域最新的 `history_fetches.fetched_at`，該區域 `legacy-itad` 觀測的最新 `retrieved_at`）；
    沒有取得過時回傳 None；台灣區與美國區分開。
  - `series_rows(apps, region, as_of)` 只回傳 `itad-history` 與 `legacy-itad`，不含 `steam-current`，也不含 anomaly 不為 NULL 的觀測；
    每一筆 `observed_at <= as_of`；依 app_id、observed_at、source 排序；結果與逐款呼叫 `observations(app, as_of, region)` 再過濾來源完全相同。
  - 兩個方法都不改變資料庫（比對呼叫前後的 `total_changes`，或以唯讀連線執行）。
- [X] T004 在 `src/steamsage/store/query.py` 實作 `PriceStore.history_known_until()` 與 `PriceStore.series_rows()`，讓 T003 通過
- [X] T005 [P] 在 `tests/unit/forecast/test_series.py` 寫 research R1 的測試：
  - 兩個來源的觀測合併，同一 `observed_at` 只留一筆，以 `itad-history` 為準。
  - `cut_pct` 為 NULL 的觀測不產生狀態。
  - `is_tracking_start` 的狀態不出現在 `events_after()`。
  - `truncate(as_of)` 只留 `start <= as_of` 的狀態，`known_until` 變成 `min(known_until, as_of)`。
  - `events_after(as_of)` 只回傳 `start > as_of` 的非追蹤起點狀態。
  - **特賣最大折扣**：
    - 取特賣開始時生效的狀態，加上特賣期間內的所有新狀態，取最大值。例如特賣前 20%，特賣中變 50%、再變 30% → 50。
    - 序列在特賣期間才開始 → 這場不產生 `SaleOutcome`。
    - 特賣結束時間 > `known_until` → 不產生。
    - 特賣期間沒有打折 → `max_cut = 0`（有資料的 0，不是缺資料）。
    - 限免（cut 100）→ 100。
    - 特賣的 `end` 是開區間：剛好在 `end` 生效的狀態不算。
- [X] T006 實作 `src/steamsage/forecast/series.py` 的 `PriceState`、`PriceSeries`（`truncate`、`events_after`）、
  `build_series(rows, known_until)`、`sale_outcomes(series, seasonal_sales, region)`，讓 T005 通過
- [X] T007 [P] 在 `tests/unit/forecast/test_salepoints.py` 寫 research R2 的測試（用 T002 的行事曆工具）：
  - 只列 `start > as_of` 的季節特賣；as_of 落在進行中的特賣時，這場不列入，第一個時點是下一場。
  - 列到 as_of + 60 個月為止，`index` 從 1 開始、依時間排序。
  - 只列 as_of 前 18 個月內舉辦過的季節：as_of = 2021-06-01 時沒有春特；as_of = 2024-06-01 時有 2025 春特。
  - **回測模式**（as_of 在過去）：用 `PriceStore.sales(as_of)` 加上 `calendar.estimate_sale()` 推估，不使用事後才公告的日期。
    構造一個「as_of 之後才出現在行事曆」的特賣，確認它的實際日期沒有被使用。
  - **現在模式**：已公告的特賣 `status = "announced"`、`basis = None`；其餘 `status = "estimated"`，並附 `basis`。
  - `label` 為「2027 春特」這種格式；冬特用開始年份。
- [X] T008 實作 `src/steamsage/forecast/salepoints.py` 的 `SalePoint` 與 `future_sale_points(store, as_of, horizon_months=60)`，
  讓 T007 通過
- [X] T009 [P] 在 `tests/contract/test_forecast_contract.py` 寫 contracts/forecast-output.md 的保證事項 1–8，針對 `contract.py`：
  - `validate_curve()` 拒絕以下情況：維度不符、數值不在 0–1、同一等級隨時間遞減、同一時點隨折扣加深遞增（FR-004）。
  - `status = "ok"` 時一定有 `confidence`、`reasons`、`curve`；其他狀態時 `curve` 為 null，而且一定有 `status_reason`。
  - JSON 有 `schema = "steamsage.forecast/1"`、`model`（name、version、params）、`as_of`、`data_cutoff`、`generated_at`、`levels`、
    `confidence_levels`、`games`、`summary`，鍵依字母排序。
  - `regular_price_cents` 未知時為 null（不是 0）；輸出中沒有任何美國區金額。
  - `write_json_atomic(path, obj)` 先寫 `path.tmp` 再改名；寫到一半丟出例外時，不留下 `path`。
- [X] T010 實作 `src/steamsage/forecast/contract.py`：`Forecast`、`ForecastBatch`、`validate_curve()`、`to_json()`、
  `write_json_atomic()`，狀態值限定為 `ok`、`unreleased`、`free`、`unsupported-bundle`、`no-history`、`unverified`、`model-error`。
  讓 T009 通過
- [X] T011 [P] 在 `tests/unit/forecast/test_evidence.py` 寫 research R3 的測試：
  - `GameEvidence.sale_history` 只含 `end <= as_of` 的特賣。
  - 目標區域是 TW 時，`series` 含 TW 與 US；目標區域是 US 時只有 US，`PopulationView` 也只有 US。
  - `PopulationView` 中所有遊戲的資料都已截斷到 as_of。
  - `GameEvidence` 與 `PopulationView` 都**沒有** `known_until` 以外的未來資訊：`series[*].known_until <= as_of`。
- [X] T012 實作 `src/steamsage/forecast/evidence.py`（`GameEvidence`、`PopulationView`，以及從完整序列建立截斷證據的函式）
  與 `src/steamsage/forecast/models/base.py`（`Model` Protocol、`ModelOutput`，依 contracts/model-api.md），
  以及 `src/steamsage/forecast/models/__init__.py` 的 `build_model(name, params)` 註冊表骨架。讓 T011 通過

**Checkpoint**：序列、特賣時點、證據截斷、輸出契約都有測試，而且通過。

---

## Phase 3: User Story 1 - 取得願望清單遊戲的折扣機率曲線 (P1) 🎯 MVP

**Goal**：`steamsage forecast` 為願望清單的每款遊戲輸出 `steamsage.forecast/1` JSON。

**Independent Test**：在人工資料庫上執行，確認每款遊戲都有曲線或明確狀態，曲線符合 FR-004，時點標示到具體特賣；
再在真實願望清單上執行（quickstart B、C）。

- [X] T013 [P] [US1] 在 `tests/unit/forecast/test_seasonal_freq.py` 寫基準模型（research R5）的測試，全部用手算驗證：
  - 本身 8 場已結束的季節特賣中 6 場 ≥ 50 → p(50) = 0.75；第 k 個時點的累積機率 = 1 − 0.25^k。
  - 本身的特賣少於 `min_sales` → 改用 `PopulationView` 的整體比例（每場特賣同權重），`confidence = "low"`。
    `min_sales` 剛好等於門檻時是 `normal`。
  - `history = "TW"`：只用台灣區的 `SaleOutcome`。
  - `history = "TW+US"`：同一場特賣以台灣區為準，沒有台灣區才用美國區；原因中出現「美國區」。
  - 目標區域是 US 時，不論 `history` 參數，只用美國區（證據本來就只有 US）。
  - 整體比例只由 `prepare()` 計算，同一個 as_of 只算一次；`PopulationView` 沒有任何特賣時，`predict()` 丟出 `ValueError`，
    訊息為「資料庫中沒有任何已結束的季節特賣，無法估計」（框架會記為 `model-error`，並把這段訊息放進 `status_reason`）。
  - 輸出符合 FR-004；`reasons` 為繁體中文，含特賣場數與區域；`evidence` 含 `regions`、`sales_used`、`first_sale`、`last_sale`、
    `population_sales`。
  - `params` 驗證：`min_sales` 是 ≥ 1 的整數，`history` 是 `TW` 或 `TW+US`，其他值丟出 `ValueError`。
- [X] T014 [US1] 實作 `src/steamsage/forecast/models/seasonal_freq.py`（`name = "seasonal-freq"`，`version = "1.0.0"`，
  預設參數 `{"min_sales": 1, "history": "TW"}` 暫定，由 T039 以正式回測決定；`tw_only_params = frozenset({"history"})`），
  並在 `models/__init__.py` 註冊。`CURRENT_MODEL` 暫時指向這組預設值，**T041 完成前不得合併**（T037 的測試會把關）。
  讓 T013 通過
- [X] T015 [P] [US1] 在 `tests/integration/test_forecast_engine.py` 寫測試（用 T002 建立人工資料庫）：
  - 狀態判定依 data-model.md 的順序：`product_type` 為 `package`／`bundle` → `unsupported-bundle`；
    分析時點尚未發行 → `unreleased`（附預定發售日）；台灣區原價為 0 → `free`；ITAD 對應被拒絕 → `unverified`；
    沒有台灣區 ITAD 歷史 → `no-history`。
  - 模型對某一款丟出例外、或輸出不符合 FR-004 → 該款是 `model-error`，其他遊戲照常產生（憲章 III）。
  - `regular_price_cents` 是分析時點台灣區最新狀態的原價。
  - 遊戲依 app_id 排序；`summary` 的各狀態數量正確；同一輸入跑兩次，除了 `generated_at` 以外完全相同。
- [X] T016 [US1] 實作 `src/steamsage/forecast/engine.py` 的 `run_forecast(store, app_ids, as_of, model, *, target_region="TW")`：
  - 讀取序列（`series_rows`、`history_known_until`），建立證據。
  - 判定狀態，呼叫 `model.prepare()` 與 `predict()`，驗證輸出。
  - 組成 `ForecastBatch`。`data_cutoff` = 使用資料中最新的已知時間（不超過 as_of）。

  讓 T015 通過
- [X] T017 [P] [US1] 在 `tests/contract/test_cli_forecast.py` 寫 contracts/cli.md 中 `forecast` 的測試：
  - 不取寫入鎖（持有鎖時仍可執行）、不開啟 `StoreWriter`。
  - `--json` 在 stdout 輸出完整的 `steamsage.forecast/1`。
  - `--out` 寫入檔案（原子寫入）。
  - `--as-of 2025-06-01` 的時點全部來自 as_of 以前的特賣推估。
  - `--app` 可以重複指定；`--scope all` 會預測資料庫中所有商品（沒有歷史的也列出狀態），預設 `--scope wishlist`。
  - 沒有 `--json` 時，每款一行：名稱、狀態、信心、下一場特賣 ≥ -50% 的機率。
  - 有 `model-error` 時 exit 2，否則 exit 0；參數錯誤時 exit 1。
- [X] T018 [US1] 修改 `src/steamsage/cli.py`：
  - 新增 `READ_ONLY_COMMANDS = {"forecast", "backtest", "compare"}`，這些指令不開啟 `StoreWriter`、不取鎖，`Context.writer` 為 None。
  - 加入 `forecast` 的 argparse 設定。

  在 `src/steamsage/commands.py` 實作 `forecast` handler（以 `PriceStore.open()` 唯讀開啟，範圍 wishlist 或 all）。讓 T017 通過
- [X] T019 [US1] 對真實資料執行 `uv run steamsage forecast` 與 `uv run steamsage forecast --as-of 2025-06-01 --json --out data/forecast-2025-06-01.json`：
  - 檢查 SC-002：每款都有曲線或狀態；有歷史的已發行付費遊戲都是 `ok`。
  - 檢查 SC-003：曲線都合法。
  - 檢查 SC-007：預測 1 分鐘內完成。
  - 抽查 3 款遊戲的原因與機率是否和資料一致。

  結果記在 `specs/002-backtest-baseline/validation.md` 的草稿中

**Checkpoint**：US1 完成，commit 並向使用者報告實際的預測結果（例如幾款低信心、下一場特賣的預測分布）。

---

## Phase 4: User Story 2 - 在任意過去時點回測模型 (P1)

**Goal**：`steamsage backtest` 以固定的回測資料集，產生兩區的回測結果 JSON。

**Independent Test**：在人工資料上，分數與手算一致；洩漏測試通過；重跑結果相同。再以真實資料跑台灣區與美國區（quickstart D）。

- [X] T020 [P] [US2] 在 `tests/unit/forecast/test_scoring.py` 寫 research R3 與 data-model 的 ScoringUnit 測試：
  - `occurred`：第一次新折扣事件 t\* < 實際結束時間。
  - `not-occurred`：實際結束時間 ≤ 該款的資料已知時間，而且沒有事件。
  - `censored`：實際結束時間 > 資料已知時間，而且目前沒有事件。
  - `not-held`：預估的（季節, 年份）在行事曆中不存在。
  - as_of 當下已生效的折扣不算事件；進行中特賣剩下期間出現的新事件，算在下一個時點（k = 1）。
  - 預測時點以（季節, 年份）對應到實際特賣，用**實際**結束時間判定；預測距離以**預估**結束時間計算。
  - 評估窗口：台灣區為預估結束時間在 (as_of, as_of + 12 個月]；美國區為 (as_of + 12 個月, as_of + 60 個月]。
  - 資料已知時間不同的兩款遊戲，截斷的判定各自獨立。
- [X] T021 [US2] 實作 `src/steamsage/forecast/backtest/scoring.py`，讓 T020 通過
- [X] T022 [P] [US2] 在 `tests/unit/forecast/test_metrics.py` 以手算的小例子寫 research R4 的測試：
  - Brier 為先算每款遊戲的平均再平均：遊戲 A 有 3 個單位、遊戲 B 有 1 個單位時，結果是兩者平均的平均，不是 4 個單位的平均。
  - 分組（預測距離：台灣區 `0-3m`、`3-6m`、`6-12m`，美國區 `12-24m`、`24-36m`、`36-60m`；折扣等級；信心；樣本來源）在組內用同樣的方式計算。
  - 校準表：每 0.1 一組；`mean_forecast` 與 `observed_rate` 的權重為 1/該遊戲的單位數；`units` 為原始數量。
  - 命中率：點預測 = 累積機率第一次 ≥ 0.5 的時點；點預測為截斷的不計；整條曲線都沒到 0.5 的計入 `never_predicted`，
    並分別計算其中實際發生的數量。
  - 時間誤差 = 點預測的時點序號 − 實際第一次發生的時點序號；實際在窗口內沒有發生、也沒有截斷的，計入 `not_occurred_in_window`。
  - 參照分數（FR-021）= 所有遊戲都用整體比例時的 Brier。
  - `per_game[region][app] = [單位數, 平方誤差總和]`。
- [X] T023 [US2] 實作 `src/steamsage/forecast/backtest/metrics.py`（以累加器方式計算，不保存所有評分單位），讓 T022 通過
- [X] T024 [P] [US2] 在 `tests/unit/forecast/test_dataset.py` 寫 research R6 的測試：
  - 遊戲清單：有台灣區 ITAD 歷史、資料截止時台灣區原價 > 0、不是套裝。
  - 樣本來源：`wishlist`（目前或曾經在願望清單）、`related`（reference_candidates 的 related-publisher／related-developer）、
    `broad`、`legacy`（只有舊專案匯入），每款遊戲只取一個，優先順序依此排列。
  - 台灣區排程：從第一場已結束季節特賣之後的第一個月 1 日開始，到截止前最後一個月 1 日為止。
  - 美國區排程：從行事曆第一場季節特賣結束後的第一個月 1 日開始，到截止前 12 個月為止。
  - 某個分析時點，只納入序列已開始的遊戲。
  - 截止時間的預設值 = 最新的資料已知時間，取到當天 00:00 UTC。
  - `dataset_ids` 逐區域計算（research R6）。某區的識別碼在以下任何一項改變時都會改變：該區遊戲清單、截止時間、該區排程、
    等級、該區評估窗口、行事曆、任一款在該區的資料已知時間、該區目標可以看到的任一筆觀測（台灣區包含兩區觀測，美國區只含美國區）。
    內容沒變時識別碼相同。只改美國區觀測時，台灣區與美國區的識別碼都會變；只改台灣區觀測時，美國區的識別碼不變。
  - 只跑台灣區（`regions=["TW"]`）時，台灣區的識別碼和兩區一起跑時相同。
- [X] T025 [US2] 實作 `src/steamsage/forecast/backtest/dataset.py` 的 `BacktestDataset` 與 `build_dataset(store, cutoff, regions, apps_limit=None)`，
  讓 T024 通過
- [X] T026 [P] [US2] 在 `tests/contract/test_no_future_leak.py` 寫 SC-001 的洩漏測試：
  - 建立人工資料庫 A，複製成 B；在 B 中把某個 as_of 之後的所有觀測折扣改成 99、另外新增幾筆 as_of 之後的觀測、
    把 as_of 之後才開始的特賣從行事曆移除。
  - 對同一個 as_of，用 `run_forecast` 分別對 A、B 產生預測：除了 `generated_at` 以外，逐位元相同。
  - 回測 runner 在記憶體中截斷所產生的預測，與直接用 `run_forecast(store, …, as_of)` 產生的預測完全相同（research R7）。
  - 測試裡的模型包含基準模型，以及一個故意「偷看」`series` 最後一筆的測試模型，後者要被這個測試抓出來（證明測試有效）。
- [X] T027 [P] [US2] 在 `tests/integration/test_backtest_runner.py` 寫測試：
  - 人工資料庫上端到端執行，結果 JSON 符合 contracts/backtest-result.md（`schema = "steamsage.backtest/1"`、`model`、`dataset`、
    `regions`、`per_game`、`errors`、`run`）。
  - 同一資料集、同一模型跑兩次，除了 `run` 以外逐位元相同（SC-005）。
  - 模型對某款在某個分析時點丟出例外 → 記在 `errors`，其他照常計分。
  - runner 執行中途丟出例外 → `data/backtests/` 只留下 `.json.tmp`，沒有 `.json`（FR-017）。
  - 進度訊息的格式為 `回測 TW 分析時點 n/N（YYYY-MM-DD）`。
- [X] T028 [US2] 實作 `src/steamsage/forecast/backtest/runner.py` 的 `run_backtest(store, dataset, model, progress, out_dir)`：
  - 一次讀入序列，依分析時點截斷證據。
  - 每個時點呼叫 `prepare()` 一次。
  - 呼叫 `engine` 的共用邏輯產生曲線，評分並累加指標，同時計算參照分數。
  - 依檔名規則原子寫入結果。

  讓 T026、T027 通過
- [X] T029 [P] [US2] 在 `tests/contract/test_cli_backtest.py` 寫 contracts/cli.md 中 `backtest` 的測試：
  - `--model`、`--param k=v`（可重複，值會轉成正確型別）、`--region TW|US|all`、`--cutoff`、`--apps-limit`。
  - 參數不合法時 exit 1。
  - 摘要列出結果檔路徑，以及各區的遊戲數（`games`）、分析時點數（`as_of_count`）、Brier、參照分數、評分與截斷與未舉辦的數量，
    和總耗時（FR-034）。
  - 不取寫入鎖。
- [X] T030 [US2] 在 `src/steamsage/cli.py` 與 `src/steamsage/commands.py` 加入 `backtest` 指令，讓 T029 通過
- [X] T031 [US2] 把 `specs/002-backtest-baseline/research-calendar-2012-2018.toml` 的 21 個 `[[sale]]` 條目（不含檔尾註記）
  依日期加入 `data/steam_sales.toml`，放在 2019 農曆新年特賣之前（FR-033）。在 `tests/unit/test_calendar.py` 新增測試：
  - 以真實的 `data/steam_sales.toml` 載入：2012–2018 每年都有夏特、秋特、冬特。
  - 2023 年以前沒有春特。
  - 每場季節特賣都有 https 來源，而且不含 steamdb。

  執行 `uv run steamsage calendar --check`，確認沒有新的提醒。
- [X] T032 [US2] 對真實資料執行：
  1. `uv run steamsage backtest --region TW --apps-limit 100`：快速試跑，檢查數字合理。
  2. `uv run steamsage backtest --region TW`
  3. `uv run steamsage backtest --region US`

  要做的事：
  - 記錄各自的耗時（SC-007），並和 research R5 的探索性數字對照；差距大時找出原因再繼續。
  - 用 Ctrl+C 中斷一次，確認只留下 `.json.tmp`。
  - 結果記進 validation.md 草稿。

**Checkpoint**：US2 完成，commit，並向使用者報告兩區的基準分數與耗時。

---

## Phase 5: User Story 3 - 比較兩個模型並留下版本化紀錄 (P2)

**Goal**：`steamsage compare` 依 FR-029 判定，並附加寫入 `docs/model/comparisons.md`。

**Independent Test**：以已知優劣的人工結果比較，判定正確；資料集不同時拒絕比較。

- [X] T033 [P] [US3] 在 `tests/unit/forecast/test_compare.py` 寫測試：
  - 可以比較的條件（contracts/backtest-result.md，逐區域）：
    - 任一份沒有台灣區 → 拒絕。
    - 兩份都有的區域，`dataset_ids[區域]` 不同 → 拒絕，並說明是哪一區。
    - 同一區域中，任一款遊戲的評分單位數不同 → 拒絕，並指出第一個不同的 app_id。
    - 只有一份有美國區：兩個模型名稱與版本相同、參數差異全部在 `tw_only_params` → 可以比較，美國區差距視為 0，
      紀錄註明「依構造相同，未重跑」；參數差異包含 `min_sales` → 拒絕。
  - 成對重抽樣：2,000 次、依遊戲抽樣、每區種子 = `int(該區 dataset_id[:8], 16)`；同樣的輸入得到同樣的區間。
  - 判定：台灣區區間上限 < 0，**而且**美國區區間下限 ≤ 0 → `優於`；否則 `未優於`，並附理由。
    用 4 組人工結果驗證（SC-008）：兩區都明顯較好；台灣區較好但美國區顯著變差；台灣區差距不顯著；
    候選只有台灣區、差異只在 `history`（美國區視為沒有變差）。
  - `--record` 以 contracts/backtest-result.md 的格式附加紀錄到指定的 markdown 檔；檔案原有內容逐位元保留。
  - 第一筆紀錄可以用判定 `建立下限` 寫入（`format_record(..., verdict="建立下限")`），不需要比較對象的結果。
- [X] T034 [US3] 實作 `src/steamsage/forecast/backtest/compare.py`（`compare_results(a, b)`、`format_record()`、`append_record(path, record)`），
  讓 T033 通過
- [X] T035 [P] [US3] 在 `tests/contract/test_cli_compare.py` 寫 `compare` 指令的測試：
  - 資料集不同時 exit 1。
  - 判定為 `未優於` 時 exit 2，`優於` 時 exit 0。
  - `--record` 預設寫入 `docs/model/comparisons.md`；`--record-to PATH` 寫入指定檔案（隱含 `--record`），測試用暫存路徑。
  - 不改變 `CURRENT_MODEL`。
- [X] T036 [US3] 在 `src/steamsage/cli.py` 與 `src/steamsage/commands.py` 加入 `compare` 指令，讓 T035 通過

**Checkpoint**：US3 完成，commit。

---

## Phase 6: User Story 4 - 知道信心等級代表什麼，並決定基準模型 v1 的參數 (P2)

**Goal**：以正式回測決定 `min_sales` 與 `history`，寫出模型定義文件與比較紀錄，讓每個信心等級都有回測分數可查。

**Independent Test**：`model-definition.md` 寫明每個信心等級的判定條件與回測分數；CURRENT_MODEL 有一筆「建立下限」或「優於」的比較紀錄。

- [X] T037 [P] [US4] 在 `tests/unit/forecast/test_current_model.py` 寫測試：
  - `CURRENT_MODEL` 的名稱與版本可以用 `build_model()` 建立。
  - `docs/model/comparisons.md` 中有一筆紀錄，候選模型的名稱、版本、參數與 `CURRENT_MODEL` 相同，且判定為 `優於` 或 `建立下限`。
  - `docs/model/model-definition.md` 包含 `CURRENT_MODEL` 的名稱與版本。
- [X] T038 [P] [US4] 在 `tests/unit/forecast/test_seasonal_freq.py` 補測試：`forecast` 輸出的 `confidence_levels` 說明文字包含實際的 N 值；
  `low` 的原因寫出「本身只有 x 場，少於門檻 N 場」。實作補在 `src/steamsage/forecast/models/seasonal_freq.py` 與 `engine.py`
- [X] T039 [US4] 以真實資料跑網格：`min_sales` ∈ {1, 2, 3, 4, 6} × `history` ∈ {TW, TW+US}，台灣區共 10 組。
  `history = TW` 的 5 組跑兩區（`--region all`）；`history = TW+US` 的 5 組只跑台灣區（`--region TW`），
  因為美國區目標一律只用美國區，結果必然和同一 `min_sales` 的 TW 組相同，compare 依 `tw_only_params` 規則處理。要做的事：
  - 所有結果使用同一個 `--cutoff`。
  - 依台灣區 Brier 選出最佳設定。
  - 用 `compare --record` 把最佳設定分別與 (a) TW 的次佳 N、(b) TW+US 的最佳設定比較，結果附加到 `docs/model/comparisons.md`。
  - 若正式結果與 research R5 的預期（TW、N=1）不同，在比較紀錄中說明。
- [X] T040 [US4] 撰寫 `docs/model/model-definition.md`（research R9 的格式），內容包括：
  - 基準模型 `seasonal-freq` v1.0.0 的規則
  - 參數與依據（T039 的網格表）
  - 兩個信心等級的判定條件，以及回測中各自的 Brier、校準表摘要與樣本數
  - 已知限制：更深的折扣給 0、不分季節、各場獨立、長期預測弱於參照分數（附數字）、美國區 2015 夏特以前的特賣有限時搶購、
    資料庫中沒有任何已結束的季節特賣時無法估計（`model-error`）
  - 「評分框架設定」一節（research R9）：18 個月季節窗口、60 個月輸出範圍、評估窗口、0.5 點預測門檻、0.1 校準分組、
    2,000 次重抽樣；標明是框架設定、不是模型參數，並附推理依據
  - 版本歷史
- [X] T041 [US4] 在 `docs/model/comparisons.md` 開頭寫說明（只附加、判定規則見 FR-029、第一個現行模型的例外見 FR-031），
  並附加基準模型的第一筆紀錄（判定：`建立下限`，理由：網格中台灣區 Brier 最低；不要求顯著優於其他設定）。
  把 `src/steamsage/forecast/models/__init__.py` 的 `CURRENT_MODEL` 設為 T039 選定的參數，讓 T037 通過

**Checkpoint**：US4 完成，commit，並向使用者報告選定的參數、各信心等級的分數，以及已知限制。

---

## Phase 7: Polish & Cross-Cutting

- [X] T042 [P] 更新 `README.md`：
  - 把「目前完成的是 feature 001」「預測尚未開始」等過時描述改成目前的狀態。
  - 新增 `forecast`、`backtest`、`compare` 指令。
  - 說明預測是什麼（累積機率曲線）、信心等級的含義。
  - 引用模型定義文件，並聲明：回測分數之外，不宣稱任何準確率（FR-022）。
- [X] T043 [P] 更新 `pyproject.toml` 的 `description`（加入預測與回測）與 `version`（0.2.0），並同步 `src/steamsage/__init__.py`
  的 `__version__`；回測結果的 `run.steamsage_version` 會使用這個值
- [X] T044 依 quickstart.md 的情境 A–G 實際執行，完成 `specs/002-backtest-baseline/validation.md`：
  - SC-001–SC-008 逐項列出結果與證據；實測耗時。
  - 兩區的基準分數；已知限制。
  - 沒有通過或無法驗證的項目。
  - spec Edge Case「行事曆沒有涵蓋的期間」：補齊行事曆後，美國區最早的資料（2012-09）已在行事曆範圍內，註明「不適用」並附查詢依據。
  - 功能測試通過與預測準確度分開報告。
- [X] T045 更新 `HANDOFF.md`，改寫成開始 feature 003 的交接：
  - 002 的結論：分數、參數、限制、預測 JSON 的位置。
  - 003 需要注意的事：長期預測的限制、台幣換算由 003 的決策核心負責。
  - 待決問題：折扣差距預設值等。
- [X] T046 最後一次執行 `uv run pytest`（`tests/` 全部），確認通過；詢問使用者是否把 `002-backtest-baseline` 合併到 master

---

## Dependencies & Execution Order

- **Setup** → **Foundational** → 各使用情境
- **US1** 依賴 Foundational。
- **US2** 依賴 US1 的 `engine.py` 與基準模型：回測要用同一份預測邏輯（T028 使用 T016）。
  T031（行事曆補齊）不依賴程式，可以提早做，但必須在 T032 的美國區回測之前完成。
- **US3** 依賴 US2 的結果格式（T028）；T033 的單元測試可以用人工結果，所以在 T023 完成後就能開始。
- **US4** 依賴 US2 與 US3：T039 需要 backtest 與 compare。
- **Polish** 最後進行。

## Parallel Opportunities

- Phase 2：T003、T005、T007、T009、T011 的測試可以同時寫；T004、T006、T010 可以同時實作。
- US1：T013、T015、T017 的測試可以同時寫。
- US2：T020、T022、T024、T026、T027、T029 的測試可以同時寫；T031 可以在任何時候進行。
- US3：T033、T035 可以同時寫。
- Polish：T042、T043 可以同時進行。

```text
# Phase 2 測試並行示例
Task: "tests/contract/test_store_series.py"
Task: "tests/unit/forecast/test_series.py"
Task: "tests/unit/forecast/test_salepoints.py"
Task: "tests/contract/test_forecast_contract.py"
Task: "tests/unit/forecast/test_evidence.py"
```

## Implementation Strategy

1. **MVP**：Setup、Foundational、US1。先讓真實願望清單產生預測曲線，確認輸出格式與原因合理。
2. 接著做 US2：回測與洩漏測試。完成後就能量化基準模型好不好，這是本 feature 的核心。
3. 然後做 US3（比較）與 US4（正式決定參數、模型定義文件）。
4. 每個 Checkpoint：跑測試、commit、向使用者報告實際數字。**功能測試通過不代表預測準確**，兩者分開報告。
