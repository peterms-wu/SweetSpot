---

description: "Task list for feature 007: non-seasonal discounts"
---

# Tasks: 季節特賣以外的折扣

**Input**：`specs/007-non-seasonal-discounts/` 的 plan.md、spec.md、research.md、data-model.md、contracts/、quickstart.md

**Tests**：憲章要求核心邏輯測試先行。每個實作任務前都有對應的測試任務：先寫測試並確認它會失敗，再實作。

**Organization**：依使用情境分組。執行順序：Setup → Foundational → US2（回測、網格、驗證組、採用）→ US1（輸出與報告，MVP 報告給使用者）→ US3 → US4 → Polish。
US1 顯示機率需要先採用模型，所以 US2 在前；如果模型沒有被採用，US1 仍然交付「只顯示依據」的報告（spec FR-016）。

| 情境 | 內容 | 優先 |
|---|---|---|
| US1 | 報告告訴我「可能不用等到那場特賣」 | P1 |
| US2 | 用回測證明非季節預測比整體比例準 | P1 |
| US3 | 模型定義把非季節折扣的影響講清楚 | P2 |
| US4 | 知道改規則值不值得 | P3 |

## Format: `[ID] [P?] [Story] Description`

- **[P]**：可以並行（不同檔案，也不依賴未完成的任務）
- **[Story]**：所屬的使用情境（US1–US4）
- 路徑都相對於 repo 根目錄

## 共用約定（每個任務都適用）

- **非季節到價**（spec FR-001）：一條 `PriceSeries` 的相鄰狀態 i−1 → i，符合以下全部條件：
  - 不是追蹤起點（`is_tracking_start` 為 false）
  - `cut_i > cut_{i-1}`
  - `start_i` 不在任何季節特賣的 `[start − TOL, end)` 內，`TOL = 1 天`

  「d 的到價」是 `cut_{i-1} < d ≤ cut_i`。
- **非季節促銷**（只用於依據）：從 0 進入 > 0、到回到 0 的一段，和任何季節特賣的 `[start − TOL, end)` 都沒有重疊；深度是期間內最深的折扣。
- **判定用的季節特賣**：
  - 預測時只用分析時點以前已開始的特賣（`start ≤ as_of`）。
  - 評分時用完整行事曆。
  - 「期間內是否有季節特賣」用 `sale_points`（已知或估計），加上正在進行的那一場（research R1「資料的時點」）。
- **模型 `non-seasonal` 1.0.0**（research R1）：
  - **本身比例** f(h, d)：回看 `LOOKBACK = 365` 天，限於看得到的歷史。起點 t 在 [開始, as_of − h] 連續分布時，(t, t+h] 內有 d 到價的比例，以區間聯集精確計算。
  - **歷史來源**：`history = TW+US` 時，台灣區開始追蹤以前用美國區的到價與促銷。
  - **整體比例** b(h, d)：population 中歷史至少 h + 30 天的遊戲，其 f(h, d) 的平均。
  - **平滑**：p1 = (w·f + k·b)/(w + k)。w = 歷史天數/30.44 − h/30.44，k = `smoothing`。歷史不足 h + 30 天時 p1 = b，這個 h 的來源是 `population`。
  - **時鐘**（`clock = true`）：
    - 取樣：population 每款遊戲每 14 天取一個 t。
    - 狀態：過去 365 天促銷次數組（0／1–2／3–4／5+）、相位（距上次開始 ÷ 間隔中位數：<0.5／0.5–1／1–1.5／≥1.5；不足 3 次為第 5 組）、t 時是否折扣、(t, t+h] 是否有季節特賣。
    - 結果：(t, t+h] 內是否有任何非季節到價。
    - 比例逐層平滑（強度 20）：次數組 → 次數組 × 折扣 × 季節特賣 → 完整狀態。
    - 係數 = 完整狀態比例 ÷ 次數組比例（次數組比例為 0 時係數 1）。
  - **輸出**：p = min(p1 × 係數, 0.99)，每個 d 再對 h 取累積最大。
  - **信心**：三個 h 都用本身比例時為 `normal`，否則 `low`。
- **回測**（research R2）：
  - 002 的台灣區資料集與 004 切分，截止 2026-09-25。
  - 只計「已知至 ≥ as_of + h」的單位，已發生的也一樣。
  - Brier 以每款遊戲的平均再平均。參照分數 = 整體比例 b。
  - 重抽樣：依遊戲成對 2,000 次，種子由 `ns_dataset_id` 決定。
- **更早到價**（spec FR-014，門檻 **50%**，使用者 2026-09-26 確認）。條件全部成立才寫：
  - 決策 ∈ {soon, wait, low}
  - 非季節 `status = ok`，而且信心為 `normal`
  - 判斷期間 = 30／60／90 中，as_of + h ≤ 甜蜜時點那場特賣 `start` 的最長一個；沒有就不寫
  - 判斷期間內達到甜蜜價折扣的機率 ≥ 0.5
- **不變**：季節模型、決策規則 2.1.0、`steamsage.backtest/1`、既有決策欄位全部不變（spec FR-012、SC-005）。
- **採用**：`CURRENT_NS_MODEL = None` 直到使用者同意（research R3）。未採用時只顯示依據（spec FR-016）。
- **分層**：`steamsage.report` 只讀決策契約的 dict（憲章 VII）。
- **文字**：使用者看得到的文字用繁體中文，措辭照 [contracts/ns-model-api.md](contracts/ns-model-api.md)。
- **改檔案**：多行修改用 Edit 工具，或 scratchpad 中的 Python 腳本，不用 Bash heredoc 改程式（HANDOFF §6）。
- **Checkpoint**：每完成一個，就跑 `uv run pytest`、commit（附 attribution trailer）並向使用者報告。要在真實資料上執行，不能只看測試。
- **原型輸出**：`prototype/out/` 不進版控。

---

## Phase 1: Setup

- [X] T001 建立子套件 `src/steamsage/forecast/nonseasonal/__init__.py`：
  - 常數：`HORIZONS = (30, 60, 90)`、`TOL = timedelta(days=1)`、`LOOKBACK_DAYS = 365`、`CLOCK_STEP_DAYS = 14`、`CLOCK_SMOOTHING = 20`、`P_CAP = 0.99`、`EARLIER_THRESHOLD = 0.5`。
  - 註冊表：`NS_REGISTRY`、`register_ns`、`build_ns_model(name, params)`（未知模型 → `ValueError`）。
  - `CURRENT_NS_MODEL: tuple[str, str, Mapping] | None = None`、`current_ns_model()`（`None` 時回傳 `None`）、`NS_BACKTESTS: tuple[dict, ...] = ()`。
  - 模組說明寫明 research R1 與 R3。
- [X] T002 [P] 新增 `tests/ns_builders.py`：
  - `series(steps, region="TW", known_until=...)`：用 `[(日期, cut), …]` 建立 `PriceSeries`，第一筆是追蹤起點，原價固定。
  - `windows(*pairs)`：季節特賣期間。
  - 一組固定的人工 population（規律促銷、不規律、從未促銷、歷史很短、只有美國區早期歷史各一款）。
  - 沿用 `tests/forecast_builders.py` 的 `dt()`。

---

## Phase 2: Foundational（所有使用情境的前提）

**Purpose**：非季節的定義、模型的輸入結構與模型本身。完成後 860 個既有測試照樣通過。

### Tests（先寫，確認失敗）

- [X] T003 [P] `tests/unit/forecast/test_ns_events.py`（research R8「定義」）：
  - 追蹤起點不是到價。
  - 開始前 23 小時的變化算季節特賣，25 小時前的算非季節。
  - 從非季節 -50% 延續進季節特賣：開始前的 -50% 是非季節到價，但這段不是非季節促銷。
  - 季節特賣期間內 -50% → -75%：-75% 不是非季節到價。
  - 已經 -50% 時，再變 -60%：只有 d ∈ (50, 60] 到價。
  - 以「as_of 已開始的特賣」判定時，之後才開始的特賣不回頭改判。
  - `window_fraction`：
    - 單一到價、兩個重疊的窗口、邊界裁切，與手算相同（至少 3 個數值案例）。
    - 可用期間 ≤ h 時回傳 `None`。
- [X] T004 [P] `tests/unit/forecast/test_ns_evidence.py`：
  - NSEvidence 只含 as_of 以前的到價與促銷。
  - `history=TW+US` 只用台灣區開始追蹤以前的美國區資料。
  - 依據欄位：`promos_365d`；`interval_days` 為中位數，至少 2 次才有；`common_depth` 同票取較深；`last_start`、`last_depth`、`days_since`、`in_promo_now`。
  - 時鐘樣本：特徵只用 t 以前，結果只用 (t, t+h]。
  - 同一組樣本依 as_of 彙總時，只取 t ∈ [as_of − 365 天, as_of − h]。
  - 整體比例 b 只含歷史至少 h + 30 天的遊戲。
- [X] T005 [P] `tests/unit/forecast/test_ns_model.py`：
  - 平滑公式與權重 w（手算）。
  - 歷史不足 h + 30 天時用 b，這個 h 的來源是 `population`，信心為 `low`。
  - 時鐘逐層平滑與係數（人工表手算），`clock=false` 時係數為 1。
  - 上限 0.99。
  - 單調性（spec SC-003）：d 越深不增加、h 越長不減少。含 200 條隨機價格路徑的性質測試。
  - `from_params`：`smoothing` 為正整數，`history` ∈ {TW, TW+US}，`clock` 接受 `true`／`false` 字串；其他值 → `ValueError`。
  - `confidence_levels()` 有 `normal` 與 `low`。
- [X] T006 [P] `tests/contract/test_ns_no_leak.py`（spec FR-011、SC-002；參考 `tests/contract/test_no_future_leak.py` 的寫法）：
  - 同一 as_of，用「資料庫只存 as_of 以前的觀測」與「完整資料」各算一次，預測完全相同。
  - 以 monkeypatch 建立三個偷看版本，測試必須全部失敗：
    1. 時鐘樣本的結果超過 as_of
    2. 用之後才開始的季節特賣判定過去的到價
    3. 「期間內是否有季節特賣」改用實際行事曆取代 `sale_points`

### Implementation

- [X] T007 `src/steamsage/forecast/nonseasonal/events.py`：
  - `Arrival(at, from_cut, to_cut)`、`Promo(start, end, depth)`
  - `arrivals(series, windows)`、`promos(series, windows)`
  - `arrived_levels(arrivals, lo, hi, levels)`
  - `window_fraction(times, lo, hi, h)`
  - `SeasonalWindows`：`inside(t)`、`overlaps(a, b)`，含 `TOL`

  讓 T003 通過（參考 `prototype/nslib.py`）。
- [X] T008 `src/steamsage/forecast/nonseasonal/evidence.py`：
  - `NSEvidence`、`NSBasis`、`NSPopulation`（data-model）。
  - `game_view(game_data, as_of, history, started_sales, sale_points)`。
  - `ClockSamples`：所有樣本只算一次；`at(as_of)` 回傳彙總後的表與整體比例 b。
  - `population_at(...)`。

  讓 T004 通過。
- [X] T009 `src/steamsage/forecast/nonseasonal/model.py`：`NonSeasonal` 1.0.0，以 `@register_ns` 註冊，照 [ns-model-api](contracts/ns-model-api.md)。
  預設參數 `smoothing=2, history=TW+US, clock=true`，`from_params({})` 使用它們（T005 加一個測試）。
  `predict()` 回傳 `NSOutput(probabilities, confidence, sources, basis, factors)`，讓 T005 通過。
- [X] T010 `src/steamsage/forecast/nonseasonal/engine.py`：
  - `check_output(out, as_of)`：契約保證 1–5，違反 → 原因字串。
  - `predict_ns(model, evidence)`：出錯或違反保證時回傳原因字串（憲章 III）。
  - `ns_forecast(store, app_ids, as_of, model)`：現在時點用。
    - 讀取：`load_games(..., regions=("TW","US"))`。
    - population：付費遊戲，`all_apps`。
    - 特賣：`store.sales(as_of)` 中已開始的，加上 `future_sale_points`。
    - 回傳每款的 NSOutput 或錯誤，以及耗時。

  讓 T006 通過。
- [X] T011 **Checkpoint**：`uv run pytest` 全部通過（860 + 新測試），commit「feat(007): non-seasonal events, evidence and model」。

---

## Phase 3: User Story 2 - 用回測證明非季節預測比整體比例準（Priority: P1）

**Goal**：`ns-backtest`、`ns-grid`、`ns-compare` 可用。調參組選定參數，驗證組比較一次，使用者決定是否採用。

**Independent Test**：人工序列上，每個單位的結果與不計分條件和手算一致；在真實調參組上的分數與 research R0.2 相符。

### Tests（先寫，確認失敗）

- [X] T012 [P] [US2] `tests/unit/forecast/test_ns_backtest.py`：
  - 單位結果：「已知至 < as_of + h」的單位不計分，已發生的也一樣。
  - Brier 以每款遊戲的平均再平均；參照分數用 b；校準每 0.1 一組。
  - `point_hit_rate`；`by_horizon`、`by_confidence`、`by_count` 的分組。
  - `earlier` 統計：傳入人工決策，門檻 0.3–0.7 的次數與命中；另列「特賣在 30 天內」與資料不足的次數。
  - `ns_dataset_id`：輸入相同時相同；期間、`TOL`、任一款的「已知至」改變時就不同。
  - 切分與鹽沿用 004。
- [X] T013 [P] [US2] `tests/unit/forecast/test_ns_compare.py`：
  - 和參照比較、和另一個結果比較。
  - `ns_dataset_id` 或切分不同 → 拒絕。
  - 只有驗證組會判定「優於／未優於」。
  - 驗證組 `--record` 的規則：
    - 必須有 `--attempt`。
    - 第 2 次以後必須有 `--change`。
    - 第 4 次拒絕。
    - 次數和 004 的模型比較、005 的規則比較分開計算。
  - 紀錄只附加，格式照 [cli-and-report](contracts/cli-and-report.md)。
- [X] T014 [P] [US2] `tests/contract/test_cli_ns.py`（參考 `tests/contract/test_cli_grid.py`、`test_cli_compare.py`）：
  - 三個指令的參數與摘要鍵。
  - `ns-grid --split validation` 被拒絕。
  - 結果檔名 `<started>_ns-<name>-<version>_<params6>_TW_<id8>.json`。
  - 結束碼：錯誤時 `EXIT_PARTIAL`，`ns-compare` 優於時 `EXIT_OK`。
  - 用 `tests/forecast_builders.py` 的小資料庫。

### Implementation

- [X] T015 [US2] `src/steamsage/forecast/nonseasonal/backtest.py`：
  - `ns_dataset(...)`：建在 `build_dataset` 的結果上，加上 `ns_dataset_id`。
  - `run_ns_backtest(dataset, games, events, model, *, earlier=True, decisions=None)`：輸出 `steamsage.ns-backtest/1`，欄位照 data-model。
  - 時鐘樣本只算一次。
  - 「更早到價」用 `steamsage.decision.backtest.decisions_multi` 取得規則 2.1.0 的決策；`decisions` 可由網格傳入共用。
  - 讓 T012 通過。
- [X] T016 [US2] 同檔加入網格與比較：
  - `run_ns_grid(...)`：選擇規則照 research R3，Brier 最低；差距 ≤ 0.001 時選較簡單的，順序為 `clock=false` > 較大的 `smoothing` > `TW`。
  - `compare_ns(...)`、`format_ns_grid_record(...)`、`format_ns_compare_record(...)`。
  - 重抽樣重用 `steamsage.forecast.backtest.compare` 的函式，必要時抽出成共用函式，不改它的行為。
  - 讓 T013 通過。
- [X] T017 [US2] `src/steamsage/cli.py`、`src/steamsage/commands.py`：加上 `ns-backtest`、`ns-grid`、`ns-compare`，
  參數與摘要照 [cli-and-report](contracts/cli-and-report.md)，進度訊息同 `backtest`。讓 T014 通過。
- [X] T018 [US2] **真實資料：和原型對照**。
  1. 執行 `uv run steamsage ns-backtest --split tuning --param smoothing=2 --param history=TW+US --param clock=true`，比對 research R0.2 的 M3：
     - Brier 0.1271
     - 30／60／90 天：0.1088／0.1392／0.1396
     - 參照分數 0.1906
     - 門檻 50% 時說這句話 3,614 次、命中 71.8%
  2. 任一差距超過 0.005，或次數差超過 2%，**逐項查明原因**再往下走（006 的教訓）。
  3. 另寫 `specs/007-non-seasonal-discounts/prototype/t018_parity.py`：
     - 用正式 `events.py` 與 `prototype/nslib.py`（兩者都有開始前 1 天的容許），分別算出調參組的到價、促銷次數與深度，逐款必須相同（spec SC-001）。
     - 另外列出和 P0（`out/p0_out.json`）的差異。P0 判斷整段促銷時沒有 1 天容許，逐項說明差異都來自這一點。
  4. 實測耗時，寫進 `validation.md` 草稿：調參組，以及有、無 `--no-earlier`。
- [X] T019 [US2] **Checkpoint**：pytest、commit「feat(007): ns-backtest, ns-grid, ns-compare」、向使用者報告 T018 的對照。
- [X] T020 [US2] **真實資料：調參組網格**。
  1. 執行 `uv run steamsage ns-grid --split tuning --grid smoothing=1,2,5 --grid history=TW,TW+US --grid clock=true,false --record`。要在 10 分鐘內完成。
  2. **停下來**：把 12 組結果與選定的參數給使用者看，使用者同意後才做驗證組。
- [X] T021 [US2] **真實資料：驗證組比較**，只做第 1 次。
  1. 執行 `ns-backtest --split validation`，參數用 T020 選定的。
  2. 執行 `ns-compare <結果> --record --attempt 1`。
  3. **停下來**：把判定、依 h 的分數、校準表、門檻 50% 的次數與命中率給使用者看。使用者的決定以一段文字附加到 `docs/model/comparisons.md`。
- [X] T022 [US2] **採用**（只在使用者同意時）。
  1. `src/steamsage/forecast/nonseasonal/__init__.py` 設定 `CURRENT_NS_MODEL`。
  2. 執行 `uv run steamsage ns-backtest --split all --no-earlier`，要在 2 分鐘內完成（spec SC-008）。
     再執行一次不加 `--no-earlier` 的，取得「更早到價」的命中率，實測耗時另外記錄。
  3. 把 `NS_BACKTESTS` 填成完整資料集的數字：日期、切分、Brier、參照分數、門檻 50% 的命中率、來源。
  4. commit「feat(007): adopt non-seasonal 1.0.0」。

  使用者不同意，或未通過時：維持 `None`，commit 比較紀錄，繼續 US1（只顯示依據）。

**Checkpoint**：模型已有調參組與驗證組紀錄；採用與否已決定。

---

## Phase 4: User Story 1 - 報告告訴我「可能不用等到那場特賣」（Priority: P1）🎯 MVP

**Goal**：決策輸出與報告有非季節的依據，採用後另有機率與「可能提早」；決策本身逐案不變。

**Independent Test**：以現在為分析時點產生報告，每款可決策的遊戲都有「季節特賣以外」一段；決策的既有欄位和沒有非季節預測時完全相同。

### Tests（先寫，確認失敗）

- [X] T023 [P] [US1] `tests/unit/decision/test_ns_decision.py`（用 `tests/decision_builders.py`）：
  - `status` 的四種情況：`ok`、`not-adopted`、`model-error`、`na`。
  - `sweet[h]` 等於 `probabilities[h][sweet_pct 的位置]`。
  - `earlier` 的判斷期間：
    - 甜蜜時點 start 距 as_of 29 天：沒有判斷期間。
    - 45 天：用 30 天。
    - 75 天：用 60 天。
    - 120 天：用 90 天。
  - `earlier` 的其他條件：
    - 門檻剛好 0.5 時要寫。
    - 決策為 now 時不寫。
    - 非季節信心為 low 時不寫。
    - 價格歷史停止更新時，信心改為 low，不寫 earlier。
  - 非季節句子放在 `non_seasonal.reasons`（既有的原因清單不變），措辭照 [ns-model-api](contracts/ns-model-api.md)；
    有 earlier 時加 `earlier-possible` 標籤。
  - **逐欄不變**：同一個預測與現價，有或沒有非季節預測時，所有既有欄位與既有原因句子完全相同。
- [X] T024 [P] [US1] `tests/contract/test_ns_outputs.py`：
  - 序列化照 [outputs-non-seasonal](contracts/outputs-non-seasonal.md)。
  - 保證 1–5 由 `Decision`／`DecisionBatch` 的檢查強制，違反時丟出 `ValueError`。
  - 批次 `non_seasonal` 在未採用時的內容。
  - 沒有 `non_seasonal` 的舊 `/2` 與 `/1` 紀錄可由 `decision.records` 讀取，也可由 `decision.changes.compare` 比較，不出錯、不標示變動。
- [X] T025 [P] [US1] `tests/unit/report/test_ns_report.py`（用 `tests/decision_builders.py` 的 `contract_dict`）：
  - 四種 `status` 的段落。
  - 「可能提早」標籤與句子，附命中率。
  - 未採用時沒有任何機率。
  - 頁首：採用時顯示「· 非季節 non-seasonal 1.0.0」；未採用時顯示「· 非季節預測：只顯示過去紀錄」。
  - 從未採用變成採用的第一份正式報告有註記。
  - HTML 跳脫。
- [X] T026 [P] [US1] `tests/integration/test_ns_report_flow.py`：
  - 用 `build_db` 建立小資料庫：3 款遊戲、兩區歷史、行事曆。
  - 執行決策與報告。
  - 決策既有欄位和關掉非季節時相同。
  - 報告含非季節段落。
  - 正式紀錄 `.json.gz` 含 `non_seasonal`。

### Implementation

- [X] T027 [US1] `src/steamsage/decision/contract.py`：
  - `Decision.non_seasonal`、`DecisionBatch.non_seasonal`，都是選用欄位，預設 `None`。
  - 序列化，以及保證 1–5 的檢查。
  - 模組說明補上 feature 007。

  讓 T024 的契約部分通過。
- [X] T028 [US1] `src/steamsage/decision/engine.py`：
  - `run_decisions` 呼叫 `ns_forecast`。未採用時只算依據：用 `build_ns_model("non-seasonal")` 的預設參數（`smoothing=2, history=TW+US, clock=true`）產生 basis，不輸出機率。
  - 每款附加 `non_seasonal`、`earlier` 的條件、原因句子與 `earlier-possible` 標籤。
  - 批次區塊：模型、是否採用、信心含義、門檻，以及 `NS_BACKTESTS` 的引用。
  - 讓 T023 通過。
- [X] T029 [US1] `src/steamsage/decision/records.py`、`src/steamsage/decision/changes.py`：
  - 讀舊紀錄時，沒有 `non_seasonal` 就當作沒有。
  - 變動比較忽略 `non_seasonal`。
  - 前一次未採用、這一次採用時，在 `comparison` 加上頁首註記。

  讓 T024 的紀錄部分通過。
- [X] T030 [US1] `src/steamsage/report/html.py`：
  - 「季節特賣以外」段落、「可能提早」標籤（`TAGS` 對照表）、頁首。
  - 390px 版面：長句要能換行。

  讓 T025、T026 通過。
- [X] T031 [US1] **Checkpoint**：pytest、commit「feat(007): non-seasonal section in decisions and report」。
- [X] T032 [US1] **真實資料 MVP**（quickstart 5、6）。
  1. **決策不變**：
     - 用 `git worktree add ../SteamSage2-master master` 取得 feature 前的程式。
     - 兩邊用同一個資料庫、同一個 as_of 產生非正式決策，逐款比對 group、甜蜜價、甜蜜時點與等待對照表，必須全部相同。
     - 規則 2.1.0 的規則回測在兩邊重跑，用 `specs/006-version-tracking/prototype/t043_rule_equivalence.py` 比對，逐案相同（spec SC-005）。
     - 比完移除 worktree。
  2. 執行 `uv run steamsage report --open`。實測 `report` 的耗時，增加量要 < 5 秒。
  3. 執行 `uv run --with playwright python specs/006-version-tracking/prototype/check_390.py data/reports/latest.html`，不得有水平捲動。
  4. 抽查特殊情況的措辭：沒有促銷、只有 1 次、用美國區補、歷史太短、正在促銷、停止更新、`model-error`（若有）。
     秋特（10/1）前的「即將到價」應沒有「可能提早」。
  5. 把報告用 `SendUserFile` 傳給使用者，**停下來**等使用者看過。

**Checkpoint**：使用者看過真實報告。

---

## Phase 5: User Story 3 - 模型定義把非季節折扣的影響講清楚（Priority: P2）

**Goal**：模型定義有非季節一節；`seasonal-record` 已知限制 1 的說明正確，附兩種校準數字。

**Independent Test**：模型定義中的每個數字都能用腳本或回測結果重現；`NS_BACKTESTS` 和模型定義一致。

- [X] T033 [P] [US3] `specs/007-non-seasonal-discounts/prototype/t033_censoring.py`：
  - 用現行 `seasonal-record` 在**完整台灣區資料集**上計算三種校準（每 0.1 一組）：
    - 現行 002 計分
    - 只計特賣在資料內已結束的單位
    - 同上，但只算季節特賣的到價
  - 另外算出：最低一格的差距中，非季節折扣與截斷規則各佔多少。
  - 輸出到 `out/`，數字給 T035 使用。
- [X] T034 [P] [US3] `tests/unit/forecast/test_ns_backtests_doc.py`：`NS_BACKTESTS` 和模型定義非季節一節的回測數字一致；未採用時 `NS_BACKTESTS` 為空，模型定義寫「未採用」。
  參考 `tests/unit/decision/test_rule_backtest_doc.py`。
- [X] T035 [US3] `docs/model/model-definition.md`：
  - **新增「`non-seasonal`（非季節預測）」一節**（spec FR-017）：
    - 預測什麼、規則（research R1）、參數與依據（T020 的網格）、結構常數
    - 信心等級、回測結果摘要與校準（T022；未採用時寫驗證組結果與「未採用」）
    - 更早到價的門檻 50% 與命中率、已知限制、版本歷史
  - **現行模型與規則表**加一列「非季節預測」。
  - **評分框架設定**加入：非季節的期間 30／60／90 天、只計已涵蓋整個期間的單位、`TOL` 1 天、理由與日期。
  - **`seasonal-record` 已知限制 1 改寫**（spec FR-018）：
    - 截斷規則的機制，以及 T033 的兩種校準與拆分。
    - 模型間的比較仍然公平，框架不改。
  - **決策規則已知限制 4 改寫**：報告顯示非季節預測，但決策不使用；附 research R0.3 的上限結論。
  - **版本歷史**加一列。
- [X] T036 [US3] **Checkpoint**：pytest、commit「docs(007): model definition for non-seasonal forecasts and the 002 censoring note」。

---

## Phase 6: User Story 4 - 知道改規則值不值得（Priority: P3）

**Goal**：research R0.3 的上限估算和正式程式一致，結論寫進驗收文件。

**Independent Test**：原型的 V0 和正式規則回測的「照建議買（每月）」在調參組逐案相同。

- [X] T037 [US4] 重跑 `specs/007-non-seasonal-discounts/prototype/p2_rule_bound.py`。
  1. 確認 V0 的每一次決策和 `uv run steamsage backtest-rule --split tuning` 結果檔 `cases` 中的 monthly 一列逐案相同（金額與天數）。
  2. 把 R0.3 的表與結論寫進 `specs/007-non-seasonal-discounts/validation.md` 的 FR-020 一節。
  3. 有差異時逐一解釋。

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T038 [P] `README.md`：
  - 報告上的「季節特賣以外」段落與「可能提早」標籤：怎麼看、命中率的意思、未採用時只顯示紀錄。
  - `ns-backtest`、`ns-grid`、`ns-compare` 的用法。
- [X] T039 [P] `specs/007-non-seasonal-discounts/validation.md`：
  - 逐項驗收 SC-001–SC-009（quickstart）。
  - 實測耗時：`report`、`ns-backtest` 調參組與完整資料集、`ns-grid`。
  - 措辭抽查；390px 檢查。
  - 功能測試與「模型是否比基準準」分開寫（spec SC-009）。
- [X] T040 `HANDOFF.md` 改寫給下一個 feature：
  - 現況：非季節模型是否採用、報告的新段落。
  - 候選方向：
    - 用時鐘預測改規則（R0.3）
    - 到價機率的校準
    - 修正 002 評分的截斷
    - 放寬 12 個月
    - 使用者指定版本
    - 新的回測資料集
  - 本 feature 的教訓。
- [X] T041 收尾：
  1. 跑 `uv run pytest`，應全部通過。
  2. 更新專案記憶（`feature007-direction`、`steamsage2-rewrite-goals` 的現況）。
  3. commit。
  4. 詢問使用者是否合併到 master。
     建議用 squash 合併：本分支較早的 commit `92f794d` 含有原型輸出（願望清單名稱），squash 可以不帶進主線。

---

## Dependencies & Execution Order

- **Phase 1 → Phase 2 → US2 → US1 → US3 → US4 → Polish**。
- **US2**：T015 依賴 Phase 2；T016 依賴 T015；T017 依賴 T016。T018 → T020 → T021 → T022 依序執行，都是真實資料。
- **US1**：測試 T023–T026 可以在 Phase 2 之後就寫。實作依序 T027 → T028 → T029 → T030。T032 依賴 T022：已採用，或已確定不採用。
- **US3**：T033 可在 Phase 2 之後任何時候執行。T035 依賴 T020、T021、T022、T033。T034 依賴 T022。
- **US4**：T037 可在 Phase 2 之後任何時候執行。
- **Polish**：T039 依賴 T032、T037；T040、T041 最後。

**使用者決策點**（實作會停下來等）：

| 任務 | 等什麼 |
|---|---|
| T018 | 和原型差距過大時，說明原因與選項 |
| T020 | 看過網格結果，同意選定的參數才做驗證組 |
| T021 | 看過驗證組判定，決定是否採用（最多 3 次；第 2 次以後要記錄改了什麼） |
| T032 | 看過真實報告 |
| T041 | 是否合併、用什麼方式合併 |

## Parallel Opportunities

- **Setup**：T002 可以和 T001 同時。
- **Phase 2**：T003–T006 是不同的測試檔，可以同時寫；實作依序 T007 → T008 → T009 → T010。
- **US2**：T012–T014 可以同時寫。
- **US1**：T023–T026 可以同時寫。
- **US3／US4**：T033、T034、T037 彼此獨立。
- **Polish**：T038、T039 可以並行。

```text
# Phase 2 測試並行
T003 tests/unit/forecast/test_ns_events.py
T004 tests/unit/forecast/test_ns_evidence.py
T005 tests/unit/forecast/test_ns_model.py
T006 tests/contract/test_ns_no_leak.py

# US1 測試並行
T023 tests/unit/decision/test_ns_decision.py
T024 tests/contract/test_ns_outputs.py
T025 tests/unit/report/test_ns_report.py
T026 tests/integration/test_ns_report_flow.py
```

## Implementation Strategy

1. **Foundational 先讓定義與模型正確、沒有洩漏**：既有 860 個測試照樣通過。
2. **US2 用真實資料證明**：
   - 先和原型對照（T018），再做網格（T020）。
   - 驗證組只做一次（T021），使用者決定是否採用。
3. **MVP = US1**：
   - 決策逐案不變，報告加上非季節段落。
   - 採用時有機率與「可能提早」；未採用時只有依據。
   - 真實報告交給使用者（T032）。
4. **US3、US4 與 Polish**：模型定義、上限估算的對照、驗收、交接。
5. **每個 checkpoint**：跑測試、在真實資料上執行、commit、報告。
