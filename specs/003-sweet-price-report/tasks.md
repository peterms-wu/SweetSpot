---

description: "Task list for feature 003: sweet-price decision and HTML report"
---

# Tasks: 甜蜜價決策與 HTML 報告

**Input**: `specs/003-sweet-price-report/` 的 plan.md、spec.md、research.md、data-model.md、contracts/、quickstart.md

**Tests**: 憲章要求核心邏輯（甜蜜價決策、變動比較）測試先行。每個實作任務前都有對應的測試任務：先寫測試並確認它會失敗，再實作。

**Organization**: 依使用情境分組：

| 情境 | 內容 |
|---|---|
| US1 | 決策 |
| US2 | HTML 報告 |
| US3 | 紀錄與變動標示 |
| US4 | 一鍵執行 |
| US5 | 規則回測 |

## Format: `[ID] [P?] [Story] Description`

- **[P]**：可以並行（不同檔案，也不依賴未完成的任務）
- **[Story]**：所屬的使用情境（US1–US5）
- 路徑都相對於 repo 根目錄

## 共用約定（每個任務都適用）

- **金額**：一律以「分」為整數計算；顯示用的「元」由決策核心以 0.5 進位算好，放進契約（research R1）。
- **時間**：帶時區的 UTC `datetime`。只有比較基準的日期用台北時間（UTC+8）判斷。
- **折扣與規則門檻**：
  - 折扣等級是 `LEVELS = (5, 10, …, 95)`。
  - 規則常數（`p_min_threshold = 0.5`、`timing_threshold = 0.5`、`low_confidence_months = 12`、`stale_hours = 24`）只寫在
    `src/steamsage/decision/rule.py` 與 `docs/model/model-definition.md`（憲章 V）。
- **分層**：
  - 決策核心只透過 `PriceStore` 與 `steamsage.forecast` 取得資料。
  - `steamsage.report` 只接受決策契約的 dict，不匯入 `steamsage.forecast` 或 `steamsage.decision`（憲章 VII）。
- **CLI**：新指令以唯讀方式開啟資料庫、不取寫入鎖，只寫 `data/forecasts/`、`data/reports/`、`data/backtests/`。
- **文字**：使用者看得到的文字用繁體中文。外部文字（遊戲名稱）在 HTML 中一律跳脫。
- **Checkpoint**：每完成一個，就跑 `uv run pytest`、commit（附 attribution trailer），並向使用者報告。
  要在真實資料上執行，不能只看測試。

---

## Phase 1: Setup

- [X] T001 更新 `.gitignore`，加入 `data/forecasts/` 與 `data/reports/`。建立空的套件骨架：
  `src/steamsage/decision/__init__.py`、`src/steamsage/report/__init__.py`、`tests/unit/decision/__init__.py`、
  `tests/unit/report/__init__.py`
- [X] T002 [P] 在 `tests/decision_builders.py` 建立決策測試共用的工具：
  - `curve_from_shares(shares_by_level, n_points)`：依 `1 − (1 − p)^k` 產生累積曲線。
  - `points(n, start="2026-09-29", as_of=...)`：產生 `SalePoint`，每 3 個月一場，名稱像「2026 秋特」。
  - `make_forecast(...)`：產生 `Forecast`，可指定信心、原價、`evidence.max_cut`。
  - `steam_current(app_id, when, price, regular)`：產生 `NewObservation`，給 `GameSpec.extra_tw` 使用。
  - 沿用 `tests/forecast_builders.py` 的 `build_db`、`GameSpec`、`Sale`、`BASIC_CALENDAR`。

---

## Phase 2: Foundational（所有使用情境的前提）

**⚠️ 這個階段完成前，不開始任何使用情境。**

- [X] T003 [P] 在 `tests/unit/test_config.py` 新增 `[preferences]` 的測試：
  - 沒有這個區段時，使用預設值：`gap_pp_shallow=10`、`gap_pp_deep=5`、`gap_boundary_pct=75`、`tolerance_min_twd=30`、
    `tolerance_max_twd=100`、`soon_sales=1`。
  - 只寫部分鍵時，其餘用預設值。
  - 驗證錯誤時拋出 `ConfigError`：
    - `gap_pp_*` 不在 1–50
    - `gap_boundary_pct` 不在 5–95 或不是 5 的倍數
    - `tolerance_min_twd` < 0 或 > `tolerance_max_twd`
    - `tolerance_max_twd` < 1
    - `soon_sales` 不在 1–4
    - 型別錯誤、布林值
  - 未知鍵只產生警告。
- [X] T004 在 `src/steamsage/config.py` 實作：`DEFAULT_TOML` 加入 `[preferences]` 與註解、`_SCHEMA`、frozen dataclass `Preferences`、
  `Config.preferences`、驗證。讓 T003 通過，而且既有的設定測試不變
- [X] T005 [P] 寫 `no_history` 的測試：
  - `tests/integration/test_forecast_engine.py`：`run_forecast` 的結果有 `no_history`，等於現行模型對「沒有本身歷史」的證據所給的曲線；
    信心 low、時點與整批相同。沒有未來時點時為 None。
  - `tests/contract/test_forecast_contract.py`：`batch_to_dict` 輸出最上層的 `no_history`，格式為 `{confidence, reasons, probabilities}` 或 null；
    002 既有的保證事項測試全部不變。
- [X] T006 實作 `no_history`（research R2），讓 T005 通過：
  - `src/steamsage/forecast/contract.py`：`ForecastBatch.no_history`（選用，預設 None）與序列化。
  - `src/steamsage/forecast/engine.py`：在 `model.prepare` 之後，以 `GameEvidence(0, as_of, "TW", {}, {"TW": (), "US": ()})` 呼叫 `predict_one`；
    出錯時記為 None。
  - 在 `specs/002-backtest-baseline/contracts/forecast-output.md` 註明這個選用欄位。
- [X] T007 [P] 在 `tests/unit/decision/test_rule.py` 寫 `decide()` 的測試，每個情境都附手算值（SC-001）：
  1. **一般信心、P_min -60%、原價 NT$990**：g=10，tol=NT$99，目標價 NT$495 → 目標 -50%（NT$495）。
  2. **下限**：原價 NT$300、P_min -80%。5pp 只有 NT$15，下限把 tol 提到 NT$30 → 目標 -70%（NT$90），`tolerance_bound = "min"`。
  3. **上限**：原價 NT$1,599、P_min -70%。10pp 是 NT$160，上限把 tol 壓到 NT$100 → 目標價 NT$580 → 目標 -65%（NT$560），`tolerance_bound = "max"`。
  4. **分界**：P_min -70% 用 10pp，-75% 用 5pp。
  5. **甜蜜時點**：目標折扣的累積機率第一次 ≥ 0.5 的時點；機率恰好 0.5 也算。
  6. **低信心**：只用結束時間 ≤ 分析時點 + 12 個月的時點算 P_min 與時點；`horizon_points` 正確。
  7. **P_min = 0 的一般信心遊戲**：改用 `no_history` 曲線與 12 個月，`basis = "no-history"`，信心變成 low，分組是 low。
  8. **現在買**：現價 ≤ 甜蜜價。原價剛好等於目標價時（原價 NT$369、P_min -10%，tol=NT$36.9 → 目標價 NT$369）**不算**現在買，
     分組是 soon，目標 -5%。
  9. **分組順序**：
     - 低信心但現價已到價 → now，加 `low-confidence` tag。
     - 原價不一致 → 信心 low。
     - 甜蜜時點在前 `soon_sales` 場 → soon；其餘 → wait。
     - 現價未知 → 不會是 now，加 `price-unknown` tag。
  10. **等待對照表**：時點 1 到甜蜜時點，每列是「機率 ≥ 0.5 的最深等級」、價格與機率，最後一列就是甜蜜時點。
      現在買的遊戲至少列時點 1。
  11. **tags**：`deeper-possible`（P_min 等於 `floor5(evidence.max_cut)`）、`below-history`（現價 < P_min 價）。
  12. **偏好改變**：例如 `tolerance_min_twd=0`，結果隨之改變。
  13. **整數運算**：沒有浮點誤差，例如原價 NT$369 的邊界。
  14. **甜蜜時點不存在**（人工構造的不合理曲線）：拋出 `DecisionError`。
  15. **低信心而且 12 個月內沒有任何時點**：拋出 `DecisionError`，原因為「未來 12 個月內沒有季節特賣，無法估計」
      （spec Edge Cases）。
- [X] T008 在 `src/steamsage/decision/rule.py` 實作 research R1，讓 T007 通過：
  - 常數 `RULE_NAME = "sweet-price"`、`RULE_VERSION = "1.0.0"`、`CONSTANTS`。
  - `RULE_BACKTEST = None`，由 US5 填入。
  - frozen dataclass `RuleResult`。
  - 純函式 `decide(probabilities, points, as_of, confidence, evidence_max_cut, regular_cents, current_price_cents,
    regular_mismatch, no_history, preferences) -> RuleResult`。不碰資料庫，也不讀目前時間。

**Checkpoint**：設定、`no_history` 與規則核心完成。跑 `uv run pytest`，commit，向使用者報告。

---

## Phase 3: User Story 1 — 知道每款遊戲現在該不該買（P1）🎯 MVP

**Goal**：每款願望清單遊戲都有分組、甜蜜價、甜蜜時點、等待對照表與原因，輸出 `steamsage.decision/1`。

**Independent Test**：在人工資料庫上跑 `run_decisions`，分組、數值、原因都與手算一致；單一遊戲出錯不影響其他遊戲。

- [X] T009 [P] [US1] 在 `tests/unit/decision/test_prices.py` 寫 research R3、R4 的測試：
  - **現價**：取分析時點以前、台灣區任一來源最新的一筆；`steam-current` 比 ITAD 新時用 `steam-current`；排除 anomaly 不為 NULL 的觀測。
  - **原價**：沒有 `regular_cents` 時，用預測的原價。
  - **`confirmed_at`**：取最新 `steam-current` 的 `observed_at` 與 `history_known_until` 中較晚的，而且不超過分析時點。
  - **`stale`**：差距 > 24 小時才算；恰好 24 小時不算。
  - **原價不一致**：兩者都已知且不同才算；有一方未知時不算。
  - **非季節折扣**：找出和已結束季節特賣都不重疊的折扣狀態，取最深的一個，只有比本身季節特賣紀錄的最深折扣更深時才回傳；
    沒有季節特賣紀錄時視為 0。
- [X] T010 [US1] 在 `src/steamsage/decision/prices.py` 實作 `current_prices(store, app_ids, as_of, forecasts)`（一次查詢所有遊戲）與
  `non_seasonal_deeper(series, sales, own_max_cut)`，讓 T009 通過
- [X] T011 [P] [US1] 在 `tests/contract/test_decision_contract.py` 以人工的 `DecisionBatch` 驗證 contracts/decision-output.md 的保證事項 1–10：
  - 每款恰好一次。
  - `group ≠ na` 時必要欄位齊全；`na` 時有 `status_reason`。
  - `sweet_pct ≤ p_min_pct`、`sweet_cents ≥ p_min_cents`、`ladder` 最後一列等於甜蜜時點。
  - `now` 時現價不為 null 且 ≤ `sweet_cents`。
  - `*_twd` 以 0.5 進位（例如 16750 分 → 168 元，33,450 分 → 335 元）。
  - 沒有美國區金額；`rule`、`preferences`、`as_of`、`forecast.model` 存在。
  - `official = false` 時沒有比較基準與變動。
  - `forecast` 符合 002 的契約。
  - 違反時拋出 `ValueError`，由引擎轉成 `decision-error`。
- [X] T012 [US1] 在 `src/steamsage/decision/contract.py` 實作，讓 T011 通過：
  - `SCHEMA = "steamsage.decision/1"`。
  - frozen dataclass `Decision`（欄位照 data-model.md），`__post_init__` 驗證。
  - `DecisionBatch`、`twd()`（0.5 進位）、`decision_to_dict`、`batch_to_dict`、`summarize`（`now`、`soon`、`wait`、`low`、`na`、`decision_error`、`changed`）。
- [X] T013 [P] [US1] 在 `tests/integration/test_decision_engine.py` 以 `build_db` 建立人工願望清單，至少包含：
  - 一般信心的現在買、即將到價、繼續等各一款
  - 低信心一款
  - P_min=0 且有非季節折扣的一款（像 PRAGMATA）
  - 原價不一致的一款（`steam-current` 原價 ≠ ITAD 原價，像 Dying Light）
  - 尚未發行、沒有歷史各一款

  驗證：
  - 分組、甜蜜價、時點都與手算一致。
  - 原因包含 FR-007（非季節折扣與日期）、FR-008（「長期最低價可能更低：目前的模型無法預測比過去更深的折扣」）、低信心原因與「只看 12 個月」、
    容許差距上下限、原價不一致（「歷史 NT$X，目前 NT$Y：可能漲價，或 Steam 改賣其他版本」）。
  - 讓 `decide` 對某一款拋錯時，只有那款是 `decision-error`（`group = na`）。
  - 同一輸入重跑，`decisions` 完全相同（FR-011）。
- [X] T014 [US1] 在 `src/steamsage/decision/engine.py` 實作 `run_decisions(store, app_ids, as_of, model, preferences, *, now, official,
  update_exit=None) -> DecisionBatch`，讓 T013 通過：
  - 流程：`run_forecast` → `current_prices` → 對每款 `decide` → 組出原因與 tags。
  - 個別例外包成 `decision-error`，不中斷整批。
  - `data_refresh` 的說明文字：
    - update 結束代碼 1：「本次資料更新失敗，使用既有資料」
    - 2：「本次資料更新有部分項目未完成」
    - 3：「另一個更新正在執行，使用既有資料」
  - `rule_backtest` 取自 `RULE_BACKTEST`，還沒有時為 null。
- [X] T015 [US1] 在 `docs/model/model-definition.md` 新增「決策規則 `sweet-price` v1.0.0」章節：
  - 規則步驟：研究 R1 的 1–9。
  - 參數表：每項標明性質（規則常數或使用者偏好）與依據，依據引用 spec Clarifications 與 research R0。
  - 規則常數。
  - 已知限制：只看標準版本、低信心回測約 20%（原型）。
  - feature 004 的候選：發售前的季節特賣被計入、非季節折扣不計入、比過去更深的折扣。
  - 版本歷史加一列。
- [X] T016 [US1] 真實資料驗收：
  - 用一行 Python 呼叫 `run_decisions` 跑真實願望清單，和 research R0 的原型比對分組與抽查的遊戲：
    Dying Light、PRAGMATA、活俠傳、Devil May Cry 5。
  - 記錄耗時與差異原因，寫到 `specs/003-sweet-price-report/validation.md` 的 US1 一節（新建檔案）。

**Checkpoint**：US1 完成。commit 並報告真實資料的分組結果。

---

## Phase 4: User Story 2 — 打開一份報告就看懂整份願望清單（P1）

**Goal**：`steamsage report` 產生單一 HTML 檔、可離線開啟，依分組呈現，只讀決策契約。

**Independent Test**：用固定的決策契約產生報告，逐一比對數值、跳脫、沒有外部資源、每款恰好一次。

- [X] T017 [P] [US2] 在 `tests/unit/report/test_html.py` 以人工契約 dict 驗證 contracts/report-html.md：
  - 每款恰好一列，位在對應的分組區塊。
  - 顯示的每個 `*_twd`、折扣、機率（`0.537` 顯示為 `54%`）、時點名稱與「官方／預估」、現價的來源與確認時間
    （`current.source`、`current.confirmed_at`，以台北時間顯示）都和契約一致（SC-003、FR-024）。
  - 頁首：版本、偏好（標示「使用者偏好」）、資料更新狀態、比較基準、各組款數、固定提示
    （「長期最低價可能更低…」「價格指標準版本（通常是一般版），不含豪華版等套件」）。
  - 規則回測：`rule_backtest` 為 null 時顯示「規則尚未回測」，不引用其他數字；有值時：
    - 即將到價、繼續等、低信心的標題顯示到價率。低信心組寫「回測中只有約 N% 在這個時點前到價，僅供參考」。
    - 現在買的標題顯示「回測中判為現在買之後 12 個月內，N% 出現更深折扣」。
    - 無法預測不顯示（FR-026）。
  - 名稱 `<script>alert(1)</script>` 只顯示為文字。
  - 沒有外部的 `src` 或 `href`（Steam 商店連結除外）。
  - 同一份契約產生的輸出完全相同。
  - 在子程序匯入 `steamsage.report.html` 後，`sys.modules` 沒有 `steamsage.forecast` 或 `steamsage.decision`。
  - 規模（SC-007）：用 500 筆人工決策產生報告，每款都在、篩選框存在，產生時間 < 2 秒，檔案 < 3 MB。
- [X] T018 [US2] 在 `src/steamsage/report/html.py` 實作 `render(contract: dict) -> str`，讓 T017 通過：
  - 只用標準庫，全部以 `html.escape` 跳脫。
  - CSS 與名稱篩選的 JavaScript 內嵌；每組用 `<details open>`，每款遊戲用 `<details>`。
  - 支援深色模式。
  - 排序照 research R8。
- [X] T019 [P] [US2] 在 `tests/contract/test_cli_report.py` 寫 contracts/cli.md 的 `report` 測試（人工資料庫）：
  - 預設寫出 `data/reports/latest.html`；`--as-of 2025-06-01` 寫出 `data/reports/asof-2025-06-01.html`；`--out` 寫到指定路徑。
  - 摘要欄位齊全；`--json` 輸出 JSON 摘要。
  - 資料庫檔案在執行前後的 hash 相同，也不建立 `data/.lock`。
  - 結束代碼：`model-error` 或 `decision-error` 時為 2；`--update-exit 1`、`2`、`3` 時為 2，契約的 `data_refresh` 對應正確；資料庫不存在時為 1。
  - `--open` 呼叫可替換的 `OPEN_FILE`（測試接縫，預設是 `os.startfile`）。
- [X] T020 [US2] 在 `src/steamsage/cli.py` 與 `src/steamsage/commands.py` 新增 `report` 指令，讓 T019 通過：
  - 加進 `READ_ONLY_COMMANDS`，參數照 contracts/cli.md。
  - 流程：`run_decisions` → `render` → 原子寫入 HTML。
  - 沒有 `--json` 時，stdout 印出各組款數。
- [X] T021 [US2] 真實資料驗收：
  - 跑 `uv run steamsage report --open`，用瀏覽器檢查報告：分組、抽查的遊戲、篩選、收合、深色模式。
  - 記錄報告大小與耗時（SC-006：≤ 30 秒）。
  - 把 T017 的 500 款報告存成檔案，在瀏覽器開啟，確認可以用篩選框找到任一款，並記錄檔案大小（SC-007）。
  - 寫進 validation.md 的 US2 一節。

**Checkpoint**：US2 完成。commit，並把報告截圖或摘要給使用者看。

---

## Phase 5: User Story 3 — 每次正式執行都留下紀錄，並標出與上次的不同（P1）

**Goal**：正式執行保存 `data/forecasts/*.json.gz`；和前一天或更早的最後一份紀錄比較，標出分組、甜蜜時點、甜蜜價的變動。

**Independent Test**：以固定的「現在」跑兩次（跨日），變動正確；中斷時沒有不完整的紀錄，比較基準不前進。

- [X] T022 [P] [US3] 在 `tests/unit/decision/test_records.py` 寫 research R6 的測試：
  - **檔名**：`<分析時點 %Y%m%dT%H%M%SZ>.json.gz`。
  - **決定性**：gzip 的 `mtime=0`，同樣的內容得到同樣的位元組。
  - **原子寫入**：讓 `os.replace` 之前失敗時，不存在 `.json.gz`；殘留的 `.tmp` 不會被列出。
  - **只新增**：檔名已存在時拋錯，不覆蓋。
  - **比較基準**：取「台北日期早於本次」的紀錄中最晚的一份。
    - 邊界：`2026-09-25T15:59Z` 是台北 9/25 23:59，`2026-09-25T16:00Z` 是台北 9/26。
    - 同一天的紀錄不當作基準。
  - **損壞的紀錄**：不是 gzip、JSON 無效、schema 不符的檔案會被略過並回報檔名，改用下一份。
- [X] T023 [US3] 在 `src/steamsage/decision/records.py` 實作 `write_record(dir, batch_dict)`、`list_records(dir)`、
  `load_record(path)`、`find_baseline(dir, as_of) -> (path | None, skipped)`，讓 T022 通過
- [X] T024 [P] [US3] 在 `tests/unit/decision/test_changes.py` 寫 research R7 的測試：
  - 分組、甜蜜時點（現在買視為「現在」）、甜蜜價（比較元，分不同但元相同不算變動）各自標示，並附 `from` / `to`。
  - 三項都沒變時 `change` 為 null；基準中沒有這款遊戲時也是 null。
  - `version_changes` 列出模型版本、規則版本與每個偏好鍵的改變，例如「偏好 gap_pp_deep 5 → 10」。
  - `changed_games` 計數正確。
- [X] T025 [US3] 在 `src/steamsage/decision/changes.py` 實作 `compare(batch_dict, baseline_dict) -> (per_app_changes, comparison)`，讓 T024 通過
- [X] T026 [P] [US3] 在 `tests/integration/test_report_flow.py` 寫端到端測試，用可替換的 `NOW` 接縫：
  - **第一次執行**：沒有比較基準，報告顯示「沒有前一天或更早的紀錄，無法比較」，寫出 1 份紀錄。
  - **同一天第二次**：比較基準仍然是空的，又多寫 1 份紀錄。
  - **隔天**：修改資料，讓某款遊戲的分組、時點與甜蜜價改變 → 報告標出 3 種變動和上次的值（SC-005），沒有變動的遊戲 0 誤報。
  - **`--as-of`**：不寫紀錄。
  - **紀錄寫入失敗**：替換 `write_record` 讓它拋錯 → 報告照樣寫出，頁首註明「本次紀錄未保存，下次仍與原比較基準比較」，結束代碼 2；
    再跑一次時的比較基準不變（SC-004）。
  - 紀錄的內容等於報告所用的契約。
- [X] T027 [US3] 把紀錄與變動接進 `report`，讓 T026 通過：
  - 正式執行的流程：`find_baseline` → `compare` → 把變動寫進 decisions 與 `comparison` → `write_record` → `render`。
  - 修改 `src/steamsage/commands.py` 與 `src/steamsage/decision/engine.py`。
  - 摘要加上 `record`、`baseline`、`changed`；略過損壞的紀錄時，結束代碼為 2。
- [X] T028 [US3] 真實資料驗收：
  - 跑兩次 `report`，確認紀錄大小（約 36 KB）與同一天的比較基準行為。
  - 用 `--as-of` 確認不寫紀錄。
  - 寫進 validation.md 的 US3 一節。

**Checkpoint**：US3 完成。commit 並報告。

---

## Phase 6: User Story 4 — 雙擊一次就更新資料並看到報告（P2）

**Goal**：`更新資料.cmd` 串接 update 與 report，並開啟報告；update 失敗或已在執行時仍用既有資料出報告。

**Independent Test**：模擬 update 的 4 種結束代碼，確認報告的資料更新狀態、訊息與整體結束代碼。

- [X] T029 [US4] 修改 `更新資料.cmd`（保持 CRLF）：
  1. 執行 `uv run steamsage update`，記下結束代碼。
  2. 執行 `uv run steamsage report --open --update-exit %code%`。
  3. 依 contracts/cli.md 的表格顯示中文訊息。
  4. 整體結束代碼取較嚴重者，順序為 1 > 3 > 2 > 0。
  5. `--no-pause` 行為不變。
- [X] T030 [US4] 手動驗收 quickstart 情境 F，把 3 種情況的結果寫進 validation.md 的 US4 一節：
  1. 正常雙擊。
  2. `update` 正在執行時再雙擊。
  3. 暫時清空 `ITAD_API_KEY` 的 update（結束代碼 2）。

**Checkpoint**：US4 完成。commit 並請使用者實際雙擊確認。

---

## Phase 7: User Story 5 — 知道甜蜜價規則在過去準不準（P3）

**Goal**：`steamsage backtest-rule` 在 002 的台灣區資料集上評分甜蜜價規則；結果寫進模型定義與 `RULE_BACKTEST`，報告改為引用正式數字。

**Independent Test**：在人工資料上，到價、未到價、截斷、超出窗口、時間誤差、現在買的後續都與手算一致；竄改分析時點之後的資料，決策不變。

- [X] T031 [P] [US5] 在 `tests/unit/decision/test_rule_backtest.py` 用人工序列寫評分測試：
  - 甜蜜時點前跨越目標折扣 → 到價；特賣結束而未跨越 → 未到價；資料截止時還沒結束也還沒跨越 → 截斷。
  - 甜蜜時點超出 12 個月 → `beyond_window`；判為現在買 → 不計入到價率。
  - 時間誤差 = 預測的特賣序號 − 實際跨越所在特賣的序號。
  - 現在買的後續：只計算之後有完整 12 個月資料的案例；12 個月內出現更深折扣的比例，以及多省的元（中位數、p75、p90）。
  - 依信心與分組彙總。
- [X] T032 [P] [US5] 在 `tests/contract/test_rule_no_leak.py` 寫洩漏測試，方式同 002 的 `test_no_future_leak.py`：
  - 兩個資料庫只在分析時點之後不同（竄改折扣、刪除觀測），同一個分析時點的決策完全相同。
  - 放一個故意偷看完整序列的決策函式，測試必須抓得到。
- [X] T033 [US5] 在 `src/steamsage/decision/backtest.py` 實作 `run_rule_backtest(store, dataset, games, events, model, preferences, *,
  out_dir, progress)`，讓 T031、T032 通過：
  - 沿用 `forecast.backtest.dataset.build_dataset(region="TW")`、`predict_one`、`scoring.unit_outcome`。
  - 現價與原價取 ITAD 序列在分析時點的狀態（research R10）。
  - 輸出 contracts/rule-backtest-result.md 的格式，原子寫入 `data/backtests/`。
- [X] T034 [P] [US5] 在 `tests/contract/test_cli_backtest_rule.py` 寫 `steamsage backtest-rule` 的測試（人工資料庫）：
  - 結果檔名與 schema 正確。
  - 摘要欄位齊全。
  - `dataset_id` 與 `steamsage backtest --region TW` 在同一截止時間下相同。
  - 結束代碼：0；有決策錯誤時為 2。
  - 以唯讀方式執行。
- [X] T035 [US5] 在 `src/steamsage/cli.py` 與 `src/steamsage/commands.py` 新增 `backtest-rule` 指令（唯讀；參數 `--cutoff`、`--apps-limit`），讓 T034 通過
- [X] T036 [US5] 真實資料執行 `uv run steamsage backtest-rule`：
  - 把到價率（整體、依分組、依信心）、時間誤差、現在買的後續、資料截止時間、資料集識別碼寫進 `docs/model/model-definition.md` 的決策規則章節，
    並填入 `src/steamsage/decision/rule.py` 的 `RULE_BACKTEST`。
  - 新增 `tests/unit/decision/test_rule_backtest_doc.py`，檢查 `RULE_BACKTEST` 的每個數字都出現在模型定義文件中。
  - 重跑 `report`，確認各組標題改成引用正式數字。
  - 耗時與數字寫進 validation.md 的 US5 一節，並和 research R0 的原型對照。

**Checkpoint**：US5 完成。commit，並把回測數字報告給使用者。

---

## Phase 8: Polish & Cross-Cutting

- [X] T037 [P] 更新 `README.md`：
  - feature 003 狀態改為 ✅。
  - 日常使用：雙擊後會開啟報告，並說明報告的分組與提示。
  - 新指令 `report`、`backtest-rule`。
  - `[preferences]` 的設定方式與預設值，標明是使用者偏好。
  - 資料位置表加上 `data/forecasts/`、`data/reports/`。
- [X] T038 [P] 更新 `HANDOFF.md`，寫給 feature 004：
  - 003 留下的東西：決策契約、紀錄、規則回測。
  - 004 的候選與證據：
    - 發售前的季節特賣被計入：台灣區 305 場、137 款。
    - 非季節折扣：願望清單 16/68 款比季節特賣更深。
    - 比過去更深的折扣：現在買之後 12 個月內 51% 出現更深折扣。
    - 低信心的到價率約 20%。
  - 之後的 feature：版本追蹤（豪華版套件）。
- [X] T039 撰寫 `specs/003-sweet-price-report/validation.md` 的總表：
  - SC-001 到 SC-009 逐項寫結果與證據。
  - quickstart 情境 A–I 的結果。
  - 實作中發現並修正的問題。
  - 功能測試與預測準確度分開寫。
- [X] T040 最後檢查：
  - `uv run pytest` 全部通過（002 的 411 項加上本 feature）。
  - 跑 quickstart 情境 H（偏好設定）與 I（安全）。
  - commit，並詢問使用者是否合併到 master。

---

## Dependencies & Execution Order

- **Setup (T001–T002)** → **Foundational (T003–T008)** → 各使用情境。
- **US1 (T009–T016)**：只依賴 Foundational，是所有後續情境的前提，因為它產生決策契約。
- **US2 (T017–T021)**：依賴 US1。T017、T018（報告）只依賴契約格式，可以和 T013、T014 並行。
- **US3 (T022–T028)**：
  - `records.py`、`changes.py`（T022–T025）只依賴契約格式，可以在 US1 完成後和 US2 並行。
  - T026、T027 依賴 US2 的 `report` 指令。
- **US4 (T029–T030)**：依賴 US2 與 US3 的 `report`。
- **US5 (T031–T036)**：只依賴 US1，因為它用 `rule.decide` 與 002 的回測。
  可以和 US2–US4 並行，但 T036 的「報告引用正式數字」要在 US2 之後。
- **Polish (T037–T040)**：全部完成後。

## Parallel Execution Examples

- **Foundational**：T003（設定測試）、T005（`no_history` 測試）、T007（規則測試）可以同時寫；接著 T004、T006、T008 分別實作。
- **US1**：T009（現價測試）、T011（契約測試）、T013（引擎測試）同時寫。
- **US2 與 US3 交錯**：T017（報告測試）、T022（紀錄測試）、T024（變動測試）同時寫；T018、T023、T025 分別實作。
- **US5**：T031、T032、T034 同時寫。

## Implementation Strategy

- **MVP = Setup + Foundational + US1 + US2**：拿到第一份可以看的報告。先請使用者看真實報告，確認分組與原因的寫法，再做紀錄與一鍵執行。
- **之後依序**：US3（紀錄與變動，憲章 IV 要求）→ US4（一鍵執行）→ US5（規則回測，把報告中的「規則尚未回測」換成正式數字）。
- **每個 Checkpoint** 都要在真實資料上執行，並把結果寫進 validation.md。發現問題時照實說明原因，並提出選項讓使用者決定。
