---

description: "Task list for feature 010: bundles holding several wishlist games"
---

# Tasks: 同時含多款願望清單遊戲的組合包

**Input**：`specs/010-wishlist-bundles/` 的 plan.md、spec.md、research.md、data-model.md、contracts/、quickstart.md

**Tests**：憲章要求核心邏輯測試先行。每個實作任務前都有對應的測試任務：先寫測試並確認它會失敗，再實作。

**Organization**：依使用情境分組。執行順序：Setup → Foundational → US1（純粹組合包的建議，MVP）→ US2（混合組合包）→ US3（每款遊戲的指引）→ US4（可信度的驗證）→ Polish。
US4 也是 P1，但它的原型（p1、p2）已在 plan 完成、數字已在 Foundational 寫進模型定義；剩下的是洩漏測試與 validation，放在功能完成之後。

| 情境 | 內容 | 優先 |
|---|---|---|
| US1 | 兩款都想買時，什麼時候買組合包最划算 | P1 |
| US2 | 混合組合包多付多少、多得什麼 | P2 |
| US3 | 從每款遊戲找到相關的組合包 | P2 |
| US4 | 知道推算可不可信 | P1 |

## Format: `[ID] [P?] [Story] Description`

- **[P]**：可以並行（不同檔案，也不依賴未完成的任務）
- **[Story]**：所屬的使用情境（US1–US4）
- 路徑都相對於 repo 根目錄

## 共用約定（每個任務都適用）

- **組合包的範圍**（research R1）：as_of 以前最新一次購買選項紀錄中，`kind = bundle`、內容含 ≥ 2 款 `in_wishlist` 遊戲的組合包；以組合包編號去除重複。
  角色 `wishlist`、`wishlist-dlc`（父遊戲是這個組合包中的願望清單遊戲）、`other-game`（`type == 0`）、`other`。純粹 = 沒有 `other-game`、`other`。
- **公式**（R3）：`expected = round((1 − b/100) × Σ price_cents)`；一致 ⇔ `|Steam − expected| ≤ max(200, round(0.01 × expected))`（單位：分）。任一內容現價未知 → `unknown`。
- **`bundle-advice` 1.0.0**（R4，模型定義正本）：
  - 分開買的計畫 = Σ（`group == "now"` 用決策現價，否則 `sweet_cents`）；最晚時點 = 各款 `sweet_point.index` 的最大值（全部「現在買」→ 現在）。
  - 單場機率 = 預測 `curve.probabilities[0]`（下一場的累積機率，R0.1 M1）；d = 0 的機率為 1。
  - 同時到價 ≥ 0.5 的折扣組合中，Σ `regular_cents × (100 − d) / 100` 最小的一組，平手取機率較高者；推算價以分計算、四捨五入。
  - 建議依序：組合包現價 ≤ 計畫 → `now`；最晚時點不是現在、同時到價 ≥ 0.5、推算價 ≤ 計畫 → `next-sale`；否則 `separately`。不加容許差距（clarify Q2）。
  - 不給建議（`status = none`）：`no-forecast`、`specified`、`check-mismatch`、`check-unknown`、`stale-price`、`no-sale`。低信心照常建議並標示。
  - 命中率依同時到價機率所在的 0.1 區間查 `BUNDLE_BACKTESTS`（隨機配對，plan D2）。
- **儲存**（R2、data-model §1）：schema v5 只加兩個可為 null 的欄位 `bundle_discount_pct INTEGER NULL`、`before_bundle_cents INTEGER NULL`；
  `contents_json` 的內容在 FR-001 組合包多 `final_cents`（未知為 null）。非願望清單 App **MUST NOT** 寫進 `products`／`product_facts`。
- **不變的保證**：每款遊戲的決策（分組、甜蜜價、甜蜜時點、等待對照表、原因）和 master 逐款相同（SC-002）；回測類指令與資料集識別碼不變。
  回測類指令一律給 `--cutoff 2026-09-25`，只用調參組。
- **時點**：讀取購買選項紀錄只用 `checked_at <= as_of`。
- **分層**：`bundles` 的數字、建議句、指引都由核心產生；`steamsage.report` 只讀決策契約的 dict（憲章 VII）。
- **契約**：只新增選用欄位，`steamsage.decision/2` 不升版（contracts/outputs-bundles.md）。
- **文字**：使用者看得到的文字用繁體中文；組合包與遊戲名稱只當資料顯示（憲章 IX）。
- **改檔案**：多行修改用 Edit 工具或 scratchpad 中的 Python 腳本，不用 Bash heredoc 改程式（HANDOFF §6）；需要專案套件的一次性腳本用 `uv run python`。
- **Checkpoint**：每完成一個，就跑 `uv run pytest`、commit（附 attribution trailer），並向使用者報告。要在真實資料上執行，不能只看測試。

---

## Phase 1: Setup

- [X] T001 [P] 在 `tests/fixtures/steam/` 更新與新增錄製格式的回應（從 `specs/010-wishlist-bundles/prototype/out/s2.json` 精簡）：
  - `getitems_purchase_options.json`：App 1903340、2592160 的組合包 74895 選項，App 1868140、2527500 的組合包 77855 選項，App 1504500、1947910 的組合包 74673 選項，
    都帶 `bundle_discount_pct` 與 `price_before_bundle_discount`（例如 74895：`final_price_in_cents` "115000"、`bundle_discount_pct` 10、`price_before_bundle_discount` "147600"）。
  - `getitems_bundles.json`：補上 74895（1903340、2592160）、77855、74673（457680、742250、1504500、1947910）的 `included_appids`。
  - `getitems_bundle_app_kinds.json`：457680、742250 的 `type` 0。
  - 新增 `getitems_content_prices.json`：457680、742250 的 `best_purchase_option`（NT$300、NT$300），以及一個沒有 `best_purchase_option` 的 App。
- [X] T002 [P] 在 `tests/decision_builders.py` 新增建構組合包測試資料的工具：`option_record(...)`（含 `contents`、`bundle_discount_pct`、`before_bundle_cents`）、
  帶 `group`／`sweet_cents`／`sweet_point`／`current`／`regular_cents` 的決策、帶 `curve.probabilities[0]` 的預測。

---

## Phase 2: Foundational（所有情境的前提；完成後「什麼都沒變」）

- [X] T003 [P] 在 `tests/unit/test_schema_migration.py` 新增 v4 → v5 的測試：遷移前後每張表逐列相同；`purchase_options` 多 `bundle_discount_pct`、`before_bundle_cents` 兩欄且既有列為 NULL；
  只新增的觸發器仍擋住 UPDATE／DELETE；遷移前自動備份 `steamsage.db.bak-v4`（已存在時不覆蓋）；失敗時回滾，維持 v4。
- [X] T004 [P] 在 `tests/unit/test_steam_webapi_versions.py` 新增測試：`parse_purchase_options` 讀出組合包選項的 `bundle_discount_pct`（整數）與 `before_bundle_cents`（字串轉整數）；
  套件選項與缺欄位時為 None。
- [X] T005 [P] 在 `tests/unit/test_store_writer.py` 與 `tests/contract/test_store_options.py` 新增測試：兩個欄位寫入與讀回；`contents` 的 `final_cents` 保留；
  `OptionRecord` 新增 `bundle_discount_pct`、`before_bundle_cents`、`contents`（`contents_json` 解析後的清單，null 時為 None）；v4 寫入的列讀回為 None。
- [X] T006 在 `src/steamsage/store/schema.py` 實作 v5：`SCHEMA_VERSION = 5`、`_migrate_to_v5` 用 `_add_column` 加兩欄、`migrate()` 呼叫；沿用 `backup_before_migration`。
- [X] T007 在 `src/steamsage/sources/__init__.py` 的 `PurchaseOption` 新增 `bundle_discount_pct: int | None = None`、`before_bundle_cents: int | None = None`；
  在 `src/steamsage/sources/steam_webapi.py` 的 `parse_purchase_options` 解析。
- [X] T008 在 `src/steamsage/store/writer.py`（`NewPurchaseOption`、`add_purchase_options`）與 `src/steamsage/store/query.py`（`OptionRecord`、`purchase_options()` 的 SELECT）加入兩個欄位與 `contents`。
- [X] T009 在 `src/steamsage/pipeline/options.py` 把 `PurchaseOption` 的兩個欄位傳進 `NewPurchaseOption`（還不做新的請求）。
- [X] T010 [P] 在 `tests/unit/decision/test_bundle_doc.py` 新增測試（沿用 `test_rule_backtest_doc.py` 的做法）：`BUNDLE_BACKTESTS` 的五個區間（實際比例與單位數）、
  整體（0.731 → 0.800、68,699 個單位）、資料集 `858b3147`、截止 2026-09-25，和模型定義「組合包建議」一節的表格一致。
- [X] T011 在 `docs/model/model-definition.md` 新增「組合包建議 `bundle-advice` v1.0.0（feature 010）」一節（contracts/cli-and-report.md 的 7 項；數字來自 research R0.1、R0.2），
  「現行模型與規則」表加一列，改寫 `sweet-price` 已知限制 1。
- [X] T012 新增 `src/steamsage/decision/bundles.py` 的常數：`RULE = ("bundle-advice", "1.0.0")`、`JOINT_THRESHOLD = 0.5`、`CHECK_MIN_CENTS = 200`、`CHECK_SHARE = 0.01`、`BUNDLE_BACKTESTS`。
- [X] T013 Checkpoint：`uv run pytest`；**先告知使用者**會把真實資料庫升到 v5（自動備份 `bak-v4`），再執行 `uv run steamsage update`（確認 `bak-v4`、遷移秒數）與 `uv run steamsage report`；
  確認組合包列有兩個新欄位、其他輸出不變。commit。

---

## Phase 3: US1 — 兩款都想買時，什麼時候買組合包最划算（P1，MVP）

**Goal**：純粹組合包有比較、推算與建議，報告有「組合包」一節。

**Independent Test**：以現在為分析時點產生報告，E33 x Dispatch、DAVE x MiSide 有比較、推算與建議，數字和 `p3_wishlist.py` 相同，也和決策輸出相同；每款決策和 master 相同。

- [X] T014 [P] [US1] 在 `tests/unit/decision/test_bundles.py` 新增找出與分級的測試：≥ 2 款 `in_wishlist` 才算（`removed_tracking` 不算）；四種角色；
  純粹／混合；`contents` 為 None 的組合包不列出、計入 `contents_unknown`；同一個組合包出現在兩款遊戲的紀錄中只算一次；純粹組合包的一款移出願望清單後改為混合或不列出。
- [X] T015 [P] [US1] 在 `tests/unit/decision/test_bundles.py` 新增公式檢查的測試：115020 vs 115000 為 ok；容許誤差邊界（expected 10,000 分時差 200 ok、201 mismatch；expected 100,000 分時差 1,000 ok、1,001 mismatch）；任一價格未知為 unknown。
- [X] T016 [P] [US1] 在 `tests/unit/decision/test_bundles.py` 新增計畫與推算的測試：
  - 計畫：「現在買」用現價、其他用甜蜜價；最晚時點；全部「現在買」時為現在。
  - 最便宜組合：d = 0 可選；同時到價剛好 0.5 可接受；平手取機率較高；三款；推算價以分四捨五入。
  - 重現 research R0.3：E33 x Dispatch 推算 106,272 分、同時到價 0.728、比計畫便宜 6,888 分、`timing = earlier`；DAVE x MiSide 推算 36,621 分、便宜 4,069 分、`timing = same`。
- [X] T017 [P] [US1] 在 `tests/unit/decision/test_bundles.py` 新增建議的測試：
  - 三個分支（`now`、`next-sale`、`separately` 的句子含組合包折扣 %）。
  - clarify Q1：全部「現在買」時沒有 `next-sale`；clarify Q2：推算價 = 計畫 + 1 分 → `separately`。
  - 命中率查表：0.51 → [0.5, 0.6] 0.685；0.728 → [0.7, 0.8] 0.830；1.0 → [0.9, 1.0]；`now` 時為 null。
  - 低信心（預測 `confidence = low` 或決策 `group = low`）標示；六個不給建議的原因各一例（`specified`：內容遊戲在 `[purchase_options]` 生效；`stale-price`：任一款決策的 `current.stale` 為 true，即 `sweet-price` 的「現價過舊 24 小時」）。
- [X] T018 [P] [US1] 在 `tests/contract/test_bundles_contract.py` 新增契約測試：`batch_to_dict` 有 `bundle_rule`、`bundles`（欄位照 contracts/outputs-bundles.md）、決策的 `bundles`；
  沒有購買選項紀錄時 `bundles` 為 null；**單一組合包**計算出錯時只有那一個 `advice.status = none`（原因寫出），其他組合包照常；整個步驟例外時決策照常、`bundles` 為 null；正式紀錄（`decision/records.py` 寫出的 `data/forecasts/*.json.gz`）寫入並讀回 `bundles`、`bundle_rule`（FR-015）；沒有這些欄位的舊紀錄可讀取與比較（`decision/changes.py`）。
- [X] T019 [P] [US1] 在 `tests/unit/report/test_bundles_html.py` 新增報告測試：「組合包」一節在群組之前、純粹在前；錨點 `bundle-<id>`；比較行、
  「任何一場季節特賣（最早〈下一場〉）」一行、建議句、低信心標籤、不給建議時的原因、`owned_note`；沒有組合包時不顯示；數字只來自 dict（改 dict 就改顯示）。
- [X] T020 [US1] 在 `src/steamsage/decision/bundles.py` 實作 `build_bundles(store, decisions, forecast, as_of, chosen)`：找出、分級、公式檢查、比較、計畫、`advise()`、建議句與原因文字，
  回傳 `(bundles, per_app_ids)`（data-model §2–§3）。
- [X] T021 [US1] 在 `src/steamsage/decision/contract.py` 新增 `Decision.bundles`、`DecisionBatch.bundles`／`bundle_rule` 與序列化；
  在 `src/steamsage/decision/engine.py` 新增 `_with_bundles`，在 `_with_editions` 之後呼叫。隔離失敗（憲章 III）：每個組合包各自 try/except，出錯的那一個 `advice.status = none`、`reason_code = error`；只有整個步驟例外時 `bundles` 為 null。
- [X] T022 [US1] 在 `src/steamsage/report/html.py` 實作「組合包」一節（contracts/cli-and-report.md），內容表格在 390 px 下不截欄（沿用版本表格的水平捲動做法）。
- [X] T023 [US1] 在 `tests/integration/test_report_flow.py` 新增整合測試：人工資料庫（含 74895 的購買選項紀錄與兩款決策）→ 報告有組合包卡片與建議。
- [X] T024 [US1] Checkpoint（MVP）：`uv run pytest`；真實資料 `uv run steamsage report`，比對 `p3_wishlist.py` 的數字；390 px 截圖（`check_390.py`）；
  用 `SendUserFile` 把報告傳給使用者看，等使用者回饋再繼續。commit。

---

## Phase 4: US2 — 混合組合包多付多少、多得什麼（P2）

**Goal**：每天記錄組合包內容的現價；混合組合包列出多付金額與多得的內容。

**Independent Test**：4 個混合組合包的組合包現價、只買願望清單遊戲的現價、差額與多得的內容，和購買選項紀錄手算一致。

- [X] T025 [P] [US2] 在 `tests/integration/test_update_options.py` 新增測試（人工來源）：FR-001 的組合包多一次內容現價請求，`final_cents` 寫進 `contents_json`；
  其他組合包沒有 `final_cents`；請求失敗 → `final_cents` 為 null、提醒一行、購買選項紀錄照常；更新摘要 `bundles`（contracts/cli-and-report.md）；非願望清單 App 沒有寫進 `products`／`product_facts`。
- [X] T026 [P] [US2] 在 `tests/unit/decision/test_bundles.py` 新增混合組合包的測試：`extra_cents`、`extra_games`、`extra_dlc`、名稱清單；任一價格未知時比較為 null；
  混合組合包的公式檢查用 `final_cents`；`advice` 為 null。
- [X] T027 [US2] 在 `src/steamsage/sources/steam_webapi.py` 新增 `content_prices(app_ids)`：GetItems（每次 ≤ 50 個）的 `best_purchase_option.final_price_in_cents`，沒有時為 None；
  在 `tests/unit/test_steam_webapi_versions.py` 用 T001 的 fixture 測試。
- [X] T028 [US2] 在 `src/steamsage/pipeline/options.py` 實作：寫入前找出 FR-001 的組合包、抓內容現價、寫進 `contents`；摘要 `bundles` 與不一致／請求失敗的提醒（`check_mismatch` 呼叫 `decision/bundles.py` 同一個檢查函式，所有內容的價格用當次的 `final_cents`，research R3）；
  在 `src/steamsage/pipeline/daily.py` 串接摘要與提醒。
- [X] T029 [US2] 在 `src/steamsage/decision/bundles.py` 與 `src/steamsage/report/html.py` 完成混合組合包的比較與卡片（「多付 NT$X，多得 N 款遊戲：…」，DLC 只寫數量）。
- [X] T030 [US2] Checkpoint：`uv run pytest`；真實資料 `update`（量購買選項步驟多出的秒數）與 `report`；4 個混合組合包的數字和 research R0.3 一致。commit。

---

## Phase 5: US3 — 從每款遊戲找到相關的組合包（P2）

**Goal**：每款出現在組合包中的願望清單遊戲都有指引行，連到組合包卡片。

**Independent Test**：有指引的遊戲正好是組合包內容中的願望清單遊戲；連結都指向存在的錨點；指定了其他版本的遊戲有註明。

- [X] T031 [P] [US3] 在 `tests/unit/report/test_bundles_html.py` 新增指引行的測試：一款在 2 個組合包 → 2 行；連結 `#bundle-<id>` 存在；不在組合包中的遊戲沒有指引；
  指定了其他版本時有「組合包含的是 Steam 預設的版本，不是你指定的版本」。
- [X] T032 [US3] 每款遊戲的指引行在 `src/steamsage/report/html.py` 的展開內容（版本表格之前）顯示；文字只由 `bundles` 的內容名稱與組合包折扣組成，不計算任何數字（實作時決定放在報告層，契約不必新增欄位）。
- [X] T033 [US3] Checkpoint：`uv run pytest`；真實資料 `report`，抽查 10 款遊戲的指引與連結；390 px 截圖。commit。

---

## Phase 6: US4 — 知道推算可不可信（P1）

**Goal**：洩漏測試、公式交叉檢查與「不變」的證據都完成，寫進 validation。

**Independent Test**：洩漏測試抓得到刻意的偷看；p1、p2 重跑的數字和模型定義相同；每款決策和 master 逐款相同。

- [X] T034 [P] [US4] 在 `tests/contract/test_bundles_no_leak.py` 新增洩漏測試：同一個 as_of，資料庫多一筆之後的購買選項紀錄（不同組合包折扣與內容）時 `bundles` 完全相同；
  刻意讀最新紀錄（忽略 as_of）的版本會被測試抓到。
- [X] T035 [US4] 新增 `specs/010-wishlist-bundles/prototype/t035_same_data.py`（仿 009 的 `t029_same_data.py`，`ADDED_KEYS = {"bundles"}`，批次另外允許 `bundles`、`bundle_rule`）：
  本分支與 master 在同一份資料上逐款比對；master 讀資料庫的副本（v5 欄位保留，master 不讀它們）。
- [X] T036 [US4] 對照每日更新摘要與決策的公式檢查結論（research R3）；重跑 `prototype/s4_itad.py`、`s6_ratio.py`（公式交叉檢查，FR-016）與 `p1_pairs.py`、`p2_cheapest.py`（截止 2026-09-25、只用調參組），
  確認資料集 `858b3147…` 與模型定義的數字相同；結果寫進 `specs/010-wishlist-bundles/validation.md`。
- [X] T037 [US4] Checkpoint：`uv run pytest`；T035 的比對 0 差異；commit。

---

## Phase 7: Polish & Cross-Cutting

- [X] T038 實測耗時（SC-007）：`update` 的購買選項步驟（平常，連續兩次）、遷移、`report`；寫進 `validation.md`。
- [X] T039 [P] 更新 `README.md`（報告的組合包一節）與 `HANDOFF.md`（010 完成、現行組合加 `bundle-advice` 1.0.0、schema v5、下一步候選）。
- [X] T040 `specs/010-wishlist-bundles/validation.md` 逐條對照 SC-001–SC-009；功能測試與「同時到價準不準」分開報告（SC-009）。
- [X] T041 最後一次 `uv run pytest`、commit，向使用者報告並詢問是否合併到 master。

---

## Dependencies & Execution Order

- Setup（T001–T002）→ Foundational（T003–T013）→ US1（T014–T024）→ US2（T025–T030）→ US3（T031–T033）→ US4（T034–T037）→ Polish（T038–T041）。
- Foundational 內：T003–T005、T010 可並行寫測試；T006 → T008 → T009；T007 → T009；T011 → T012（常數照模型定義）。
- US1 依賴 Foundational（組合包折扣欄位、常數）。US2 的內容現價只影響混合組合包，可以在 US1 之後獨立完成。
- US3 依賴 US1 的 `per_app_ids`。US4 的 T035 需要 US1–US3 完成（比對整個決策輸出）。

## Parallel Example: US1

```text
T014, T015, T016, T017（tests/unit/decision/test_bundles.py 的不同測試類別，可以同時寫）
T018（tests/contract/test_bundles_contract.py）
T019（tests/unit/report/test_bundles_html.py）
```

## Implementation Strategy

1. **MVP = Setup ＋ Foundational ＋ US1**：純粹組合包的比較與建議出現在報告中；T024 把真實報告給使用者看。
2. 之後依序加 US2（混合）、US3（指引）、US4（驗證），每個 checkpoint 都在真實資料上執行並 commit。
3. 沒有模型或規則換版，不需要驗證組比較；比較文件不附加。
