---

description: "Task list for feature 013: post-sale comparison of the 2026 autumn sale"
---

# Tasks: 事後對照（2026 秋特）

**Input**：`specs/013-post-sale-comparison/` 的 plan.md、spec.md、research.md、data-model.md、contracts/review.md、quickstart.md

**Tests**：憲章要求核心邏輯測試先行。每個實作任務前都有對應的測試任務：先寫測試並確認它會失敗（`uv run pytest -o addopts="" -q <檔案>`），再實作。
測試**不連網**、不用真實資料庫：小型測試資料庫（`tests/forecast_builders.build_db`）＋手寫的測試紀錄；期望值**手算後寫成常數**，不得用被測的程式算。

**Organization**：執行順序：Setup → Foundational（選特賣與紀錄、讀追蹤的價格序列）→ US1（季節機率與決策，含最小的 `review` 指令）→ US2（無法對照與補正）
→ **MVP：在真實資料上跑一次，給使用者看秋特的結果** → US6（`--doc` 與可重現）→ US3（組合包）→ US4（非季節）→ US5（重算）→ Polish。

| 情境 | 內容 | 優先 |
|---|---|---|
| US1 | 秋特前的預測和決策實際準不準（季節機率兩種定義、決策、提早到價、現在買） | P1 |
| US2 | 實際價格不清楚的遊戲明確標示；依每日價格紀錄補正（D2） | P1 |
| US6 | 結果寫進版本化文件（`--doc` 草稿、逐位元組相同） | P1 |
| US3 | 組合包建議的對照 | P2 |
| US4 | 非季節預測：只計已到期 | P2 |
| US5 | 同一時點重算現行與基準模型 | P3 |

**和 plan 的差異**（tasks 時補上，已同步改 plan.md）：
① 測試資料用 `tests/review_builders.py`（沿用 `tests/*_builders.py` 的慣例），不是 `tests/fixtures/review/`；
② `store/query.py` 加一個唯讀查詢 `PriceStore.option_steps`（SQL 留在 store，和其他查詢一致）；
③ 最小的 `review` 指令（JSON＋文字摘要）提前到 US1，MVP 直接用指令在真實資料上跑；`--doc` 留在 US6。

## Format: `[ID] [P?] [Story] Description`

- **[P]**：可以並行（不同檔案，也不依賴未完成的任務）
- **[Story]**：所屬的使用情境
- 路徑都相對於 repo 根目錄（worktree `〈專案資料夾〉-013`）

## 共用約定（每個任務都適用）

- **唯讀**：`review` 加進 `cli.READ_ONLY_COMMANDS`（不開 writer、不取鎖）；資料庫用 `PriceStore.open(config.db_path, calendar_path)`（和 `commands.open_store` 相同）。
  只寫 `--out` 一個檔案（暫存檔再改名）。不連網、不改資料庫、`data/forecasts/`、`data/steam_sales.toml`、`steamsage.toml`。
- **不動模型、規則、報告、擴充功能、每日更新、回測**（FR-020）：`forecast/`、`decision/`、`report/`、`pipeline/` 不改；`store/query.py` 只新增 `option_steps`。
- **追蹤的商品**（data-model §2）：`decision["version"]["itad_id"]`；`version.source == "user"` 時讀 `sources=(OPTION_HISTORY_SOURCE,)`，否則 `ITAD_SOURCES`
  （`store/query.py` 的常數；prototype `common.tracked_key` 已驗證）。序列：`store.series_rows([app], "TW", today, keys={app: itad_id}, sources=...)`
  ＋`store.history_known_until_all("TW", keys={app: itad_id}, apps=(app,))` → `build_series(rows, "TW", known)`。
- **兩種到價**（D1）：主要 `sale-max`＝`sale_outcomes(series, [sale])[0].max_cut ≥ d`（依 D2 補正後）；次要 `crossing`＝`series.first_crossings(as_of, LEVELS)[d]` 不是 None 且 `< sale.end`。
  決策一律用「特賣期間最低價 ≤ 甜蜜價」（`sweet_cents`）。
- **特賣期間**：`[sale.start, sale.end)`，`sale` 取自 `store.calendar_events()` 中 `kind == "seasonal"` 且季節、年份相符的一場（實際日期）。
- **區間**：沿用 `forecast/backtest/compare._bootstrap(values, seed)`（直接 import，不複製；2,000 次、2.5%／97.5%），值是**每款遊戲一個數**；
  種子 `int(hashlib.sha256(record_file_name.encode()).hexdigest()[:8], 16)`，每個彙總數字用同一個種子。
- **回測數字與出處**（research R4）：季節 `只計已結束的 Brier（每款同權重）` 台灣區 **0.0604**（`differs` 依次要定義的區間判定），並列整體 0.0579；
  出處 `docs/model/model-definition.md` 的「`seasonal-record` v1.1.0（現行）／回測結果摘要」。決策的到價率用紀錄自己的 `rule_backtest.hit_rate`；非季節用紀錄的 `non_seasonal.backtest`。
- **數字格式**：機率與分數 4 位小數（`round(x, 4)`）；金額以分（`*_cents`）；JSON 鍵依字母排序、`ensure_ascii=False`；`run` 是唯一隨執行變動的區塊。
- **未知不是零**（憲章 I）：`no-actual`、`not-scored`、`pending` 不進任何分母；`None` 不得被 `or 0` 吞掉。
- **真實資料**：`--config 〈專案資料夾〉\steamsage.toml`，`--out` 一律指到 `specs/013-post-sale-comparison/prototype/out/`（不寫進主資料夾的 `data/`）。
- 在 Bash 印中文前設 `PYTHONIOENCODING=utf-8`；一次性腳本寫到 scratchpad、`PYTHONUTF8=1 uv run python <檔>`。

---

## Phase 1: Setup

- [X] T001 建立 `tests/review_builders.py`（測試用，不含斷言）：
  - `AUTUMN = Sale("autumn", 2026, "2026-10-01T17:00", "2026-10-08T17:00")`、`WINTER = Sale("winter", 2026, "2026-12-17T18:00", "2027-01-04T18:00")`，
    `AS_OF = dt("2026-09-30T18:31:37")`，`RECORD = "20260930T183137Z.json.gz"`；`calendar` 另含 2025 的四場（讓 `build_db` 有過去的特賣）。
  - `review_db(path)`：用 `forecast_builders.build_db`＋`add_history`＋`add_purchase_options` 建 7 款（regular NT$500 = 50000 分）：
    - **A 1**：0% → 特賣開始 60% → 結束 0%；甜蜜 50%（25000）、分組 `soon`、甜蜜時點 2026 秋特。
    - **B 2**：9/29 起 40%、延續到特賣結束（開賣前已在打折）；分組 `now`、紀錄當時現價 30000。
    - **C 3**：0% → 特賣 50%；甜蜜 50%、分組 `wait`、甜蜜時點 2026 冬特（提早到價，特賣中改口）。
    - **D 4**：使用者指定的版本（`version.source = "user"`、`option = {kind: "sub", id: 4001}`）：只有 `itad-option-history` 的列，特賣 75%；App 本身的歷史是 0%（證明讀錯商品會算錯）。
    - **E 5**：價格歷史 `known_until` = 2026-10-05（沒涵蓋到特賣結束）→ `no-actual`。
    - **F 6**：價格歷史整場 0%，但它的預設購買選項每日紀錄（`purchase_options`，10/2–10/8 每天 02:30 台北）是 33%（劍星的情況，D2 補正）。
    - **G 7**：紀錄中 `status = "na"`（無法預測）→ `not-scored`。
  - `pre_sale_record(**overrides) -> dict`：`steamsage.decision/2`、`official: true`、`as_of: AS_OF`，7 款的 `decisions`（含 `version`、`group`、`sweet_cents`、`sweet_pct`、
    `sweet_point`、`current`）與 `forecast.games`（A–F 的 `curve.points[0]` 是 2026 秋特，`probabilities[0]` 依下面 T008 的手算值）；
    用 `tests/decision_builders.py` 既有的 `decision`／`contract_dict` 組，不足的欄位直接寫。
    （實作：紀錄只是 dict，對照只讀其中幾個欄位，所以全部直接寫；沒有用 `decision_builders`。）
  - `during_records(groups_by_day) -> list[dict]`：特賣期間每天一份正式紀錄（`as_of` 10/1 18:35Z … 10/7 18:31Z），`groups_by_day[app]` 指定每天的分組。
  - `write_records(directory, records)`：用 `decision.records.write_record` 寫成 `.json.gz`。
- [X] T002 [P] 測試 `tests/contract/test_store_options.py`（加測試，先寫）：`PriceStore.option_steps(app_id, kind, option_id, start, end)` 回傳該購買選項在 `[start, end)` 內每一次檢查的
  `OptionRecord`（依 `checked_at` 排序；別的選項、別的 App、期間外的列不出現；沒有列時回傳空 list）。然後在 `src/steamsage/store/query.py` 實作（只讀，既有方法不改；欄位與 `purchase_options` 相同的轉換）。

## Phase 2: Foundational（所有情境都需要）

- [X] T003 [P] 測試 `tests/unit/test_review_target.py`（先寫、確認失敗）：`select_target(store, forecasts_dir, *, sale=None, record=None, today, force=False)`
  - 預設選最近一場已結束（`end ≤ today`）的季節特賣（契約 §1；結束不到 3 天時照下一條拒絕，不跳到前一場）；`--sale autumn-2026` 解析成 `("autumn", 2026)`；格式錯、不存在、`kind = themed` → `TargetError`（訊息說明）。
  - 特賣未結束 → `TargetError`；結束不到 3 天 → `TargetError`，`force=True` 時通過且 `forced = True`。
  - 紀錄：`as_of < sale.start`、`official = true`、schema 在 `records.READABLE` 中，取 `as_of` 最大者（以內容的 `as_of` 為準，不信檔名）；
    更晚但 `official = false` 的跳過；讀檔失敗的跳過並列在 `skipped_records`；一份都沒有 → `TargetError`。
  - `record="<檔名或路徑>"` 時用指定的那份（仍要 `as_of < sale.end`，否則 `TargetError`）。
  - `during`：`sale.start ≤ as_of < sale.end` 的正式紀錄（依 `as_of` 排序）＋`missing_days`：特賣期間的台北日期中沒有任何正式紀錄的日子（`records._taipei_day` 的算法）。
  - `hours_before_start = round((sale.start - as_of) 小時, 1)`。
- [X] T004 實作 `src/steamsage/review/__init__.py`（空的套件說明）與 `src/steamsage/review/target.py`：`TargetError(ValueError)`、
  凍結的 `ReviewTarget(sale, record_path, record, during: tuple[(path, record)], missing_days, today, forced, skipped_records, hours_before_start)`
  與 `select_target`（data-model §1；讀檔用 `records.list_records`／`records.load_record`）。讓 T003 通過。
- [X] T005 [P] 測試 `tests/unit/test_review_actual.py` 的「讀哪個商品」部分（先寫）：`tracked_series(store, decision, today)` 對 A 回傳 A 自己的序列；
  對 D 讀 `itad-option-history`（特賣最深 75%，不是 App 本身的 0%）；回傳值帶 `series`、`basis`（`default`／`user`）、`itad_id`、`option`、`known_until`。
- [X] T006 在 `src/steamsage/review/actual.py` 實作 `tracked_series`（共用約定的「追蹤的商品」）。讓 T005 通過。

**Checkpoint**：選得到對照對象，讀得到每款追蹤的價格序列。

---

## Phase 3: User Story 1 - 看秋特前的預測和決策實際準不準 (Priority: P1)

**Goal**：逐款列出分組、甜蜜價、機率與實際最深折扣、最低價、有沒有到價；彙總季節機率（兩種定義）、決策（依分組）、提早到價、現在買。

**Independent Test**：測試資料上逐款結果與彙總等於手算值；`steamsage review` 在測試資料上輸出 `steamsage.review/1`。

### Tests for User Story 1 ⚠️（先寫、確認失敗）

- [X] T007 [P] [US1] `tests/unit/test_review_actual.py` 加：`sale_actual(series, sale, as_of)` →
  A：`max_cut 60`、`min_cents 20000`、`running_cut_at_as_of 0`；B：`max_cut 40`、`min_cents 30000`、`running_cut_at_as_of 40`；
  兩種到價：A 的 `sale_max` 與 `crossing` 都是 5–60% 到、65–95% 沒到；B 的 `sale_max` 5–40% 到，`crossing` 全部沒到。
  最低價＝特賣開始時有效的狀態＋特賣期間的狀態中最低的 `price_cents`（prototype `p1_actual.sale_min_price` 的規則）。
- [X] T008 [P] [US1] `tests/unit/test_review_score.py`（新檔）季節機率：A 的機率 0.8（5–60%）／0.2（65–95%），B 的 0.9（5–40%）／0.1（45–95%）。手算：
  A 每單位 0.04 → 遊戲 0.04（兩種定義相同）；B 主要 0.01、次要 (0.81×8 + 0.01×11)/19 = **0.346842**；
  只對 A、B 兩款呼叫 `seasonal_summary` 時，彙總（每款同權重）主要 **0.025**、次要 **0.1934**（4 位小數）；`differs_games == [2]`（兩種定義結果不同的遊戲）；校準表每 0.1 一組，列預測平均、實際比例、單位數、遊戲數；
  依信心等級分組。曲線第一個時點不是這一場時取對應的時點（`season`、`year` 相符），沒有就 `not-scored` 並寫原因。
- [X] T009 [P] [US1] `tests/unit/test_review_score.py` 決策：A `hit = True`、`gap_cents = -5000`；最低價 25000 時 `hit = True`、`gap 0`，33400 時 `hit = False`、`gap 8400`（spec US1 情境 2）；
  `timing`：甜蜜時點是這一場 → `on-time`，之後的時點且這一場到價 → `early`，之後且沒到 → `not-yet`，`now` 組 → `n/a`；
  B（`now`）：`now_vs_sale = {"kind": "same", "diff_cents": 0}`，紀錄現價 30000、特賣最低 25000 時 `lower`／`-5000`；
  彙總依分組：`on-time` 的到價率（並列 `rule_backtest.hit_rate[group]`）、`early` 款數、`now_vs_sale` 計數。
- [X] T010 [P] [US1] `tests/unit/test_review_score.py` 提早到價（FR-010a）：C 在特賣第 2 份紀錄改成 `now` → `switch = {"state": "first_now", "as_of": <第 2 份的 as_of>}`；
  所有特賣期間紀錄都不是 `now`、沒有缺漏 → `missed`（並寫最後一份的分組）；不是 `now` 但 `missing_days` 非空 → `unknown`（不算錯過）；
  某份紀錄沒有這一款 → 那份不算 `now`。
- [X] T011 [P] [US1] `tests/contract/test_cli_review.py`（新檔）：在 `tmp_path` 建測試資料庫、設定檔、`data/forecasts/`（開賣前＋特賣期間紀錄），`commands.NOW` 固定在 2026-10-12；
  `steamsage review --config <cfg> --sale autumn-2026 --out <tmp>/r.json --no-recompute` → 結束代碼依 contracts §1、檔案的 `schema == "steamsage.review/1"`、
  `definitions == {"primary": "sale-max", "secondary": "crossing"}`、`games` 依 `app_id` 排序且 7 款都在、`summary.counts`；`--json` 時 stdout 是 `summary`；
  特賣未結束 → 代碼 1 且**沒有寫出任何檔案**。

### Implementation for User Story 1

- [X] T012 [US1] `src/steamsage/review/actual.py`：`sale_actual(series, sale, as_of)` → 凍結的 `SaleActual(max_cut, min_cents, running_cut_at_as_of, sale_max: dict[int,bool], crossing: dict[int,bool], regular_changed)`。讓 T007 通過。
- [X] T013 [US1] `src/steamsage/review/score.py`：`review_game(decision, forecast_game, actual, sale, during)` → `GameReview`（data-model §2 的欄位；`status` 先只處理 `reviewed`／`not-scored`）；
  `seasonal_summary(games, seed)`（兩種定義的 Brier＋區間、依信心等級、校準表、`differs_games`、回測並列與 `differs`）；
  `decision_summary(games, record, seed)`（依分組；到價率的區間用每款 0／1）；`early_switch(app_id, during, missing_days)`。讓 T008–T010 通過。
- [X] T014 [US1] `src/steamsage/review/contract.py`：`review_to_dict(target, games, summary, run)`（contracts §2；`run = {"started_at", "seconds", "steamsage_version"}`）、
  `write_review(path, data)`（鍵排序、`ensure_ascii=False`、暫存檔再改名；可用 `forecast.contract.write_json_atomic`，先確認它的 `dumps` 有排序鍵）、
  `summary_text(data)`（contracts §4 的格式，先輸出「對照」「季節機率」「即將到價」「繼續等」「現在買」幾行）。
- [X] T015 [US1] `src/steamsage/cli.py`：`review` 子指令與參數（contracts §1：`--sale`、`--record`、`--today`、`--force`、`--no-recompute`、`--doc`、`--out`；`--doc` 先接受但 US6 才實作），
  加進 `READ_ONLY_COMMANDS`；`src/steamsage/commands.py`：`@command("review") review_command`：`select_target` → 每款 `tracked_series`＋`sale_actual`＋`review_game`
  → 彙總 → 寫檔 → `CommandResult(code, summary, text=summary_text(data))`。單款的例外只讓那一款變成 `no-actual`（原因寫例外類型），`TargetError` → 代碼 1、不寫檔。
  預設 `--out`：`config.data_dir / "reviews" / f"{season}-{year}_{record_stem}_{today:%Y%m%d}.json"`；`--today` 預設 `NOW()`。讓 T011 通過。

**Checkpoint**：US1 在測試資料上完整可用。

---

## Phase 4: User Story 2 - 實際價格不清楚的遊戲明確標示 (Priority: P1)

**Goal**：「無法對照」有原因、不進分母；每日價格紀錄比價格歷史深時補正（D2）。

**Independent Test**：測試資料的 E、F、D 與下列變形各得到對應狀態與原因，彙總分母不含 `no-actual`／`not-scored`。

### Tests for User Story 2 ⚠️

- [X] T016 [P] [US2] `tests/unit/test_review_actual.py` 加「無法對照」5 種（SC-002）：價格歷史沒涵蓋到特賣結束（E；原因寫「價格歷史只到 2026-10-05」）、
  完全沒有序列、序列從特賣開始之後才開始、使用者指定的版本沒有自己的歷史、紀錄的 `version.itad_id` 是 None；每種都是 `status = "no-actual"` 且 `reason` 不同；
  `seasonal_summary`／`decision_summary` 的分母不含它們（加一款 `no-actual` 前後分數不變）。
- [X] T017 [P] [US2] `tests/unit/test_review_actual.py` 加 D2：`cross_check(actual, steps)`（`steps` 是 `option_steps` 的結果）
  - F：價格歷史 0%、每日紀錄 33% → `max_cut 33`、`min_cents 33500`、`corrected = True`、`daily_max_cut 33`；季節計分照常（`sale_max` 5–30% 到）；
    次要定義的到價時間用第一筆 33% 的每日紀錄的 `checked_at`。
  - 價格歷史 75%、每日紀錄 60% → 採用價格歷史、`corrected = False`，列入 `mismatches` 的「只註記」。
  - 開賣當天 02:30 的每日紀錄是 0%（ITAD 已切換、Steam 還沒），之後是 60%，價格歷史 60% → 一致、不註記（不逐日比較，只比整段最深）。
  - 沒有每日紀錄 → `daily_max_cut = None`，不補正也不註記。
- [X] T018 [P] [US2] `tests/unit/test_review_actual.py` 加版本：紀錄之後 Steam 預設購買選項換了版本 → 仍讀紀錄中的 `itad_id`，`series.version_changed = True`（spec US2 情境 4）；
  D 的每日紀錄比對的是 `version.option` 的 `kind`／`id`（`sub`／4001），不是 App 預設。
- [X] T019 [P] [US2] `tests/contract/test_cli_review.py` 加：測試資料（含 E、F）→ 結束代碼 **2**；`summary.counts.no_actual == 1`、`corrected == 1`；`summary.mismatches` 分成 `corrected` 與 `noted`。

### Implementation for User Story 2

- [X] T020 [US2] `src/steamsage/review/actual.py`：`tracked_series` 回傳無法對照的原因（不丟例外）、`version_changed`；`cross_check(actual, steps)`；
  `commands.review_command` 對每款呼叫 `store.option_steps(app, kind, id, sale.start, sale.end)` 並套用 `cross_check`；結束代碼依 contracts §1（`no-actual`、補正、`skipped_records`、`forced` → 2）。讓 T016–T019 通過。
- [X] T021 [US2] `src/steamsage/review/score.py`：`mismatches(games)`；文字摘要加「依每日價格紀錄補正 N 款（名稱）」與無法對照的款數。

**Checkpoint**：P1 的 US1、US2 完成。

### MVP：真實資料（停下來給使用者看）

- [X] T022 [US1] 在真實資料上執行（唯讀）：
  `uv run steamsage review --config 〈專案資料夾〉\steamsage.toml --sale autumn-2026 --no-recompute --out specs/013-post-sale-comparison/prototype/out/review-mvp.json`
  核對 SC-001（68/68 款都有結果或原因；現在買 9、即將到價 26、繼續等 28、低信心 2、無法預測 3）、和 plan 原型的差異（即將到價 25/26、提早到價 6/6 第一天改口、
  主要 Brier ≈ 0.040、次要 ≈ 0.125、補正 1 款劍星、Cyberpunk 2077 一致）；有差異時找出原因再繼續。**把文字摘要與差異給使用者看，等使用者確認再進下一階段。**

---

## Phase 5: User Story 6 - 結果寫進版本化文件 (Priority: P1)

**Goal**：`--doc` 產生 `comparisons.md`「事後對照」一節的草稿；同一份資料結果逐位元組相同；指令不改任何輸入檔。

**Independent Test**：兩次執行（去掉 `run`）逐位元組相同；`--doc` 的每個數字都能在 JSON 找到。

- [X] T023 [P] [US6] `tests/contract/test_cli_review.py` 加：同一份測試資料跑兩次，去掉 `run` 後 bytes 相同（FR-018、SC-004）；執行前後資料庫、`data/forecasts/` 每個檔案、
  行事曆檔、設定檔的 SHA-256 不變；`--doc` 的 stdout 是 Markdown，且其中每個數字（regex 取出的小數與百分比）都能在結果 JSON 的對應欄位找到（SC-009）。
- [X] T024 [US6] `src/steamsage/review/contract.py`：`doc_draft(data)`：標題「事後對照：2026 秋特（紀錄 `<檔名>`）」，寫出資料截止時間（`today`）、紀錄檔名與 `as_of`、
  特賣（台北時間）、模型與規則版本、各項數字＋分母＋區間＋回測數字與出處、兩種定義的差異與原因、補正與無法對照、「和回測一致」或「和回測不同」（只依 `differs`，FR-019、US6 情境 2），
  最後一段「之後可以考慮的候選」（只列出，由使用者決定）。`commands.review_command`：`--doc` 時 `text = doc_draft(data)`、`summary = {}`（不另印摘要），仍寫結果檔。讓 T023 通過。

---

## Phase 6: User Story 3 - 組合包建議的對照 (Priority: P2)

**Goal**：每個組合包建議逐個列出推算價 vs 實際、是否同時到價、折扣是否改變、分開買的計畫實際花多少。

**Independent Test**：測試紀錄的組合包建議與手算的實際價格相同。

- [X] T025 [P] [US3] `tests/unit/test_review_score.py` 加組合包（用 `decision_builders.e33_dispatch()` 的形狀，內容改成 A 與 C）：
  `bundle_review(bundle, steps, actuals, sale)` → `estimate_gap_cents`（實際最低 − 推算）、`discount_same`（特賣期間的 `bundle_discount_pct` 是否和紀錄當時相同）、
  `joint_hit`（每個內容的 `max_cut ≥ levels[].pct`）、`separate_plan`（甜蜜時點是這一場的用特賣最低價，之後的 → `complete = False`）；
  沒有特賣期間的每日紀錄 → `actual = None` 並寫原因、不推算；`grade = "mixed"` → 只列出、不計分；彙總**沒有**命中率欄位（FR-012）。
- [X] T026 [US3] `src/steamsage/review/score.py`：`bundle_review`；`commands.review_command` 對紀錄的每個 `bundles[]`（`advice.kind` 是 `next-sale`／`now`）呼叫 `store.option_steps(app, "bundle", id, sale.start, sale.end)`
  （任一內容的 App 都可以，取第一個有列的）；文字摘要加「組合包」一行。讓 T025 通過。

---

## Phase 7: User Story 4 - 非季節預測：只計已到期 (Priority: P2)

**Goal**：只計期間已結束、價格歷史涵蓋整個期間的單位；其餘列出最早可對照的日期。

**Independent Test**：同一份測試資料、不同的 `--today`：未到期 0 個計分並列出到期日；到期後計入。

- [X] T027 [P] [US4] `tests/unit/test_review_score.py` 加非季節：測試紀錄的 A、C 有 `non_seasonal.probabilities`（3 × 19），C 有 `earlier`（60 天、`sweet_pct` 50）；
  C 的價格歷史在 10/20（不在季節特賣內）有一段 50% 促銷。
  - `today = 2026-10-12` → 0 個 `scored`；`pending` 列出 30／60／90 天的到期日 2026-10-30T18:31:37Z、11-29、12-29。
  - `today = 2026-11-01` 且價格歷史已知到 11/01 → 30 天的單位計入（C 在 50% 以下的等級 `arrived = True`、季節特賣中的 A 60% **不算**到價），60／90 天仍 `pending`；Brier 手算寫成常數。
  - 價格歷史只知道到 10/25 → 30 天的單位 `pending`（原因：價格歷史還沒到到期日），不是 `no-actual`。
  - `earlier`：判斷期間（60 天）結束前不計；結束後列出 `hit`，並列紀錄的 `hit_rate 0.736`。
- [X] T028 [P] [US4] `tests/contract/test_cli_review.py` 加：`--today 2026-10-12` 與 `--today 2026-11-01` 的 `summary.non_seasonal` 符合 T027（SC-005）。
- [X] T029 [US4] `src/steamsage/review/score.py`：`ns_units(decision, series, windows, as_of, today)` → `NSUnit` 列表（data-model §4；到價用
  `events.arrived_levels(events.arrivals(series, windows), as_of, as_of + h, LEVELS)`，`windows = SeasonalWindows.from_events(store.calendar_events())`，計分條件同非季節回測：
  `known_until ≥ as_of + h` 且 `due ≤ today`）；`ns_summary(units, record, seed)`（依期間的 Brier＋區間、`pending` 款數與最早到期日、`earlier` 的結果）。
  `commands.review_command` 接上；文字摘要加「非季節」一行。讓 T027、T028 通過。

---

## Phase 8: User Story 5 - 同一時點重算 (Priority: P3)

**Goal**：在紀錄的 `as_of` 用今天的資料庫重算現行模型與基準模型，和正式紀錄並列，不判定優劣。

**Independent Test**：重算的現行模型等於正式紀錄；分析時點之後的假資料不影響重算，移到之前會影響。

- [X] T030 [P] [US5] `tests/contract/test_review_leak.py`（新檔，沿用 `tests/contract/test_no_future_leak.py` 的做法）：在測試資料庫的 `AS_OF` 之後插入假的價格列（99%）
  → `recompute(...)` 的現行與基準機率逐值相同；把同樣的假資料移到 `AS_OF` 之前 → 結果改變（反向測試，SC-006）。
- [X] T031 [P] [US5] `tests/unit/test_review_score.py` 加：`recompute_summary(record_games, current, baseline, actuals, seed)` 只在三者都有這一場的遊戲上計分，並列三個 Brier＋區間，
  **沒有**「優於」之類的欄位；重算的現行模型和紀錄不同的遊戲列出分組、甜蜜價的差異。
- [X] T032 [US5] `src/steamsage/review/recompute.py`：`recompute(store, record, as_of)`：
  現行＝`run_decisions(store, apps, as_of, current_model(), Preferences(**record["preferences"]), choices=<紀錄中 version.source == "user" 的 (option.kind, option.id)>, official=False)`
  （紀錄的模型版本和 `current_model()` 不同時註明）；基準＝`run_forecast(store, apps, as_of, build_model("seasonal-freq", {"min_sales": 2, "history": "TW"}))`；
  不寫任何紀錄或報告。`score.recompute_summary`；`commands.review_command` 在沒有 `--no-recompute` 時呼叫；文字摘要加「重算」一行（「不判定優劣」）。讓 T030、T031 通過。

---

## Phase 9: Polish & 驗證

- [X] T033 全部測試：`uv run pytest -o addopts="" -q` 與 `node --test "tests/extension/*.test.js"` 全部通過。
- [X] T034 真實資料完整執行（quickstart §2）：`review-a.json`、`review-b.json`（SC-004：去掉 `run` 後逐位元組相同；執行前後主資料夾 `data/steamsage.db`、`data/forecasts/`、
  `data/steam_sales.toml`、`steamsage.toml` 的 SHA-256 不變）、`--today 2026-11-01 --no-recompute`（SC-005）、`run.seconds`（SC-008：不含重算 ≤ 60 秒、含重算 ≤ 300 秒）。
- [X] T035 SC-007：在本分支與 master（主資料夾的 worktree，同一份資料庫，唯讀）各跑 `uv run steamsage backtest --config <主資料夾設定> --cutoff 2026-09-25 --split tuning --out <prototype/out/…>`，
  去掉時間欄位後相同；`report --as-of 2026-09-30` 的決策 JSON 在兩邊相同。（不寫進主資料夾的 `data/`。）
- [X] T036 查 10/7 的紀錄「現在買」從 47 款掉到 39 款的原因（plan 的未解問題；唯讀，看 10/6 與 10/7 紀錄中掉出「現在買」的那 8 款的 `current`、`data_refresh`、甜蜜價），
  結論寫進 `specs/013-post-sale-comparison/research.md` 新的一節 R10；不影響 013 的計分。
- [X] T037 SC-003：把真實資料的 `mismatches`（補正與只註記）與一致的 3 款整理給使用者抽看（劍星、Cyberpunk 2077 必在其中）。
- [X] T038 `docs/model/comparisons.md` 新增「事後對照」一節：由 `--doc` 的草稿整理（數字不得手改；SC-009 用 T023 的方法對真實資料再檢查一次）。
- [X] T039 [P] `HANDOFF.md` §3 加候選：① 模型不看分析時點正在打的折扣（D1 的附帶發現）；② D3 每日更新誤隔離的修補提案（013 之後、014 之前，先提案）；③ T036 的結論；
  ④ 非季節 30 天在 10/30 之後重跑、60／90 天和 2026 冬特一起看。
- [X] T040 [P] `README.md` 的指令列表加上 `review`（一行說明＋唯讀）。
- [X] T041 列出值得重構的點（只列、不改範圍外的程式），寫在交付訊息中；詢問使用者是否合併。

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup（Phase 1）**：沒有依賴。T001 與 T002 可並行。
- **Foundational（Phase 2）**：依賴 Setup；阻擋所有情境。
- **US1（Phase 3）** → **US2（Phase 4）** → **MVP（T022）**：US2 擴充 US1 的 `actual.py` 與指令，必須在 US1 之後。
- **US6（Phase 5）**：依賴 US1 的 `contract.py`；之後每加一個情境，`doc_draft` 要跟著加一段（T026、T029、T032 各自補上）。
- **US3、US4、US5（Phase 6–8）**：都只依賴 US1＋US2，彼此獨立；同一個人做時依優先順序。
- **Polish（Phase 9）**：依賴全部情境。

### Within Each User Story

- 測試先寫並確認失敗，再實作。
- `actual.py` → `score.py` → `contract.py` → `commands.py`／`cli.py`。
- 每個 Phase 結束 commit 一次（plan「實作順序與 checkpoint」）；commit 訊息寫成檔案再 `git commit -F`。

### Parallel Opportunities

- T001 ∥ T002；T003 ∥ T005。
- US1 的測試 T007–T011 可並行（不同檔案或同檔不同測試函式，先寫好再一起跑）。
- US2 的測試 T016–T019；US3 的 T025；US4 的 T027 ∥ T028；US5 的 T030 ∥ T031。
- T039 ∥ T040。

---

## Parallel Example: User Story 1

```text
Task: "T007 sale_actual 的測試 in tests/unit/test_review_actual.py"
Task: "T008 季節機率的測試 in tests/unit/test_review_score.py"
Task: "T011 指令的契約測試 in tests/contract/test_cli_review.py"
```

---

## Implementation Strategy

### MVP First（US1＋US2）

1. Phase 1–2：測試資料、`option_steps`、選對照對象、讀追蹤的序列。
2. Phase 3：季節機率、決策、提早到價、最小的 `review` 指令。
3. Phase 4：無法對照與 D2 補正。
4. **T022：在真實資料上跑，停下來給使用者看秋特的結果。**

### Incremental Delivery

5. US6（`--doc`、可重現）→ US3（組合包）→ US4（非季節）→ US5（重算）；每個 Phase 結束 commit。
6. Polish：驗證 SC-001–SC-009、`comparisons.md`、HANDOFF、README，詢問是否合併。

---

## Notes

- 引用任務一律帶 spec 號（`013 T022`）。
- 實作偏離本文件或 plan 時停下來說明，不要默默調整。
- 進度寫在本文件的勾選框與 HANDOFF，不寫進記憶。
