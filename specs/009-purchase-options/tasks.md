---

description: "Task list for feature 009: user-chosen purchase option and list of other editions"
---

# Tasks: 使用者指定版本、列出其他購買選項

**Input**：`specs/009-purchase-options/` 的 plan.md、spec.md、research.md、data-model.md、contracts/、quickstart.md

**Tests**：憲章要求核心邏輯測試先行。每個實作任務前都有對應的測試任務：先寫測試並確認它會失敗，再實作。

**Organization**：依使用情境分組。執行順序：Setup → Foundational → US2（列出版本，資料的基礎）→ US1（指定，MVP）→ US3 → US4 → Polish。
US2 和 US1 都是 P1；US1 依賴 US2 的購買選項紀錄與版本歷史，所以先做 US2。

| 情境 | 內容 | 優先 |
|---|---|---|
| US1 | 看到我想買的版本的甜蜜價（指定） | P1 |
| US2 | 知道這款遊戲還有哪些版本、各多少錢（列出） | P1 |
| US3 | 指定的版本不能用時，我會知道 | P2 |
| US4 | 換版本時，變動標示說得清楚 | P2 |

## Format: `[ID] [P?] [Story] Description`

- **[P]**：可以並行（不同檔案，也不依賴未完成的任務）
- **[Story]**：所屬的使用情境（US1–US4）
- 路徑都相對於 repo 根目錄

## 共用約定（每個任務都適用）

- **版本的定義**（research R1）：購買選項的內容包含這個 App，而且其他每個 App 都是「`type == 4`（DLC）且 `parent_app_id` 是這個 App」。
  `role ∈ {default, edition, other-games, without-app, unknown}`（data-model §1）；只有 `edition` 查 ITAD。
  Steam 預設購買選項（006 的 `app_versions`）記為 `role = default`，驗證與歷史仍由 006 負責。
- **擴充驗證**（research R2）：`verify_version` 新增被驗證的購買選項 `option=("sub"|"bundle", id)`：
  別名中**等於這個選項本身**的 `bundle/N` 接受；其他 `bundle/…` 仍拒絕（`reason_code = "bundle"`、`reason_detail = "bundle/<id>"`）；
  價格基準是這個選項自己的台灣區價格；006 對預設選項的行為完全不變（既有測試照樣通過）。
- **儲存**（research R3、data-model）：
  - `purchase_options` 表的欄位照 data-model §1 原文；只新增，加入 `APPEND_ONLY_TABLES`。
  - 版本的歷史：`price_observations.source = 'itad-option-history'`、`external_id` = 版本的 ITAD 商品；
    `history_fetches.source = 'itad-option'`。
  - 組合包內其他 App 的類型 **MUST NOT** 寫進 `products`／`product_facts`（會改變參考資料與回測資料集），只存在 `contents_json`。
- **不變的保證**：
  - 沒有任何指定時，所有決策和本 feature 之前逐款相同（SC-001）。
  - 指定一款遊戲時，其他遊戲逐款相同（SC-002）：整體比例（季節與非季節）只從預設版本計算。
  - 2026-09-25 截止的台灣區資料集識別碼仍是 `d493ac02…`（SC-007）。回測指令一律給 `--cutoff 2026-09-25`。
- **時點**：讀取購買選項紀錄只用 `checked_at <= as_of`；指定依**目前的設定**（決定 D1）。
- **抓取**：版本的台灣區歷史每天抓；美國區只抓指定生效的版本（決定 D2）；和預設版本同一個 ITAD 商品時不抓。
- **分層**：`editions`、`config_line`、`source`、`fallback` 都由核心產生；`steamsage.report` 只讀決策契約的 dict（憲章 VII）。
- **契約**：只新增選用欄位，`steamsage.forecast/1`、`steamsage.decision/2` 不升版（contracts/outputs-options.md）。
- **文字**：使用者看得到的文字用繁體中文；購買選項名稱只當資料顯示（憲章 IX）。
- **改檔案**：多行修改用 Edit 工具或 scratchpad 中的 Python 腳本，不用 Bash heredoc 改程式（HANDOFF §6）；
  需要專案套件的一次性腳本用 `uv run python`。
- **Checkpoint**：每完成一個，就跑 `uv run pytest`、commit（附 attribution trailer），並向使用者報告。要在真實資料上執行，不能只看測試。

---

## Phase 1: Setup

- [X] T001 [P] 在 `tests/fixtures/steam/` 新增錄製格式的回應（從 `prototype/out/` 的真實回應精簡）：
  - `getitems_bundles.json`：組合包 32470（Cyberpunk 2077：1091500 加一個 DLC，`success` 1）、32958（DAVE THE DIVER 1868140 加 DLC）、
    一個含其他遊戲的組合包（DAVE THE DIVER x MiSide 77855）、一個不含本體的組合包（Devil May Cry 5 升級包 10318）、一個 `success` 不是 1 的組合包。
  - 在 `getitems_purchase_options.json` 補上 App 1091500 的選項（套件 367653 NT$1599 預設、組合包 32470 NT$2206）與
    App 812140 的四個套件（349018／349019／349028／349020）。
  - `getitems_bundle_app_kinds.json`：上述組合包內 App 的 `type` 與 `related_items.parent_appid`。
- [X] T002 [P] 在 `tests/fixtures/itad/` 新增 `lookup_options.json`（`bundle/32470`、`sub/349020` 等 → ITAD 商品）、
  `reverse_lookup_options.json`（Cyberpunk 終極版的別名 = 只有 `bundle/32470`；Dying Light 十週年完整版的別名含 `bundle/47759`）、
  `history_cyberpunk_ultimate_TW.json`（精簡為 8 筆，含一次 -60%）。

---

## Phase 2: Foundational（所有情境的前提；完成後「什麼都沒變」）

- [X] T003 [P] 在 `tests/unit/test_schema_migration.py` 新增 v3 → v4 的測試：遷移前後每張既有表逐列相同；`purchase_options` 存在且為空；
  只新增的觸發器擋住 UPDATE／DELETE；遷移前自動備份 `steamsage.db.bak-v3`（已存在時不覆蓋）；失敗時回滾，維持 v3。
- [X] T004 [P] 在 `tests/unit/test_store_writer.py` 新增 `add_purchase_options()` 的測試：欄位照 data-model §1；`role` 與 `kind` 的值域檢查；
  `contents_json`、`aliases_json`、`warnings_json` 以 JSON 保存。
- [X] T005 [P] 在 `tests/contract/test_store_series.py` 新增讀取修正的測試（research R3，證明抓得到 P3 的潛在錯誤）：
  - 構造 `itad-option-history` 的列**比 Steam 現價新**：`latest_observations`、`observations` 在預設 key 下仍回傳預設版本的現價，不回傳版本的列。
  - `series_rows` 不帶 `sources` 時不含版本的列；帶 `sources=("itad-option-history",)` 與版本 key 時只回傳版本的列。
  - `build_series` 接受版本歷史的來源（原型發現 1）。
  - `history_known_until_all` 依 key 只計那個商品的抓取紀錄。
- [X] T006 [P] 在 `tests/unit/test_history_ingest.py`、`tests/unit/test_coverage.py`、`tests/unit/test_calendar.py`、
  `tests/unit/test_consistency.py` 新增「加入版本歷史前後相同」的測試：`fetch_state`、`history_is_fresh`（不帶商品）、coverage 的抓取次數
  只計來源 `itad`；季節特賣偵測（`calendar.py`）、區域一致性、參考資料計數的結果不變。
- [X] T007 [P] 在 `tests/contract/test_cli_backtest_rule.py` 新增資料集識別碼測試：人工資料加入 `itad-option-history` 的列與 `purchase_options` 列後，
  同一截止時間的資料集識別碼與規則回測結果逐案相同。
- [X] T008 [P] 在 `tests/unit/test_config.py` 新增 `[purchase_options]` 的測試（US2 的抓取與 US1 都用到，所以放在 Foundational）：合法值解析成
  `{app_id: ("sub"|"bundle", id)}`；鍵不是正整數、值格式錯、數值相同寫法不同（`"0123"` 與 `"123"`）→ 忽略並回傳警告文字
  （contracts/cli-and-report.md）；完全相同的鍵重複 → `ConfigError`（D3）；`DEFAULT_TOML` 的範例全部註解掉，載入後為空。
- [X] T009 實作 schema v4：`src/steamsage/store/schema.py`（`SCHEMA_VERSION = 4`、`purchase_options` 表與索引
  `(app_id, checked_at)`、`(app_id, kind, option_id, checked_at)`、加入 `APPEND_ONLY_TABLES`、v3 → v4 遷移與備份、`OPTION_ROLES` 等值域常數）。
- [X] T010 實作 `StoreWriter.add_purchase_options()`：`src/steamsage/store/writer.py`。
- [X] T011 實作讀取修正：`src/steamsage/store/query.py`（`OPTION_HISTORY_SOURCE`、`series_rows(sources=)`、`latest_observations`／`observations`
  把 `itad-option-history` 當成依商品過濾的 ITAD 列）、`src/steamsage/forecast/series.py`（`build_series` 接受該來源）、
  `src/steamsage/forecast/engine.py`（`load_games(sources=)`）。
- [X] T012 實作抓取紀錄的來源過濾：`src/steamsage/pipeline/history.py`（`fetch_state`、`history_is_fresh` 只計 `itad`；
  `ingest_history` 新增 `source`／`fetch_source` 參數，預設值維持現行）、`src/steamsage/coverage.py`。
- [X] T013 實作 `src/steamsage/config.py`：`Config.purchase_options`、解析與警告、`DEFAULT_TOML` 的註解範例。
- [X] T014 跑 `uv run pytest`（1011 個既有測試＋新測試全部通過）。**Checkpoint**：commit「Foundational：schema v4、版本歷史的來源、讀取修正與設定」。

---

## Phase 3: User Story 2 — 知道這款遊戲還有哪些版本、各多少錢（P1）

**Goal**：每日更新記錄所有購買選項並判定版本；報告的摘要行顯示「另有 N 個版本」，展開後列出版本、價格、歷史最低價與設定行。

**Independent Test**：真實願望清單上列出 26 款、33 個版本，其中可指定的 25 款、32 個（以當天資料為準）；含其他遊戲或不含本體的選項 0 個出現。

### Tests（先寫、確認會失敗）

- [X] T015 [P] [US2] 在 `tests/unit/test_steam_webapi_versions.py` 新增 `bundle_contents()` 的測試：解析 `included_appids`；`success` 不是 1 的
  組合包回傳「查不到」而不是空內容；分批 50 個；HTTP 錯誤拋出 `SourceError`。
- [X] T016 [P] [US2] 在 `tests/unit/test_itad_prices.py` 新增 `lookup_ids()` 的測試：同一個請求查 `sub/N` 與 `bundle/N`；沒有對應的是 None。
- [X] T017 [P] [US2] 在 `tests/unit/test_verify.py` 新增 R2 的測試：組合包選項的別名只有它自己 → `verified`；別名含另一個組合包 → `rejected`、
  `bundle`、`bundle/47759`；套件選項的價格基準是它自己（AC Odyssey 終極版 NT$3259 不和預設 NT$1699 比）；
  不帶 `option` 時行為和 006 完全相同。
- [X] T018 [P] [US2] 新增 `tests/unit/test_options.py`（購買選項步驟，人工來源）：
  - `role` 判定：套件版本、只含本體與 DLC 的組合包 → `edition`；含其他遊戲 → `other-games`；不含本體 → `without-app`；內容查不到 → `unknown`。
  - 只有 `edition` 查 ITAD；預設選項記 `role = default`、不重複驗證。
  - 組合包內 App 的類型沿用 30 天內紀錄的值（`contents_checked_at` 保留原始時間），只查新出現的 App；不寫 `products`／`product_facts`。
  - 同一 ITAD 商品 7 天內的驗證沿用（`verified_by = cached`，保留原始 `verified_at`）。
  - 來源錯誤：不寫任何列，摘要 `source_error = true`，alert 說明。
- [X] T019 [P] [US2] 在 `tests/unit/test_history_ingest.py` 新增版本歷史的抓取測試：通過驗證的版本抓台灣區（`itad-option-history`、`itad-option`）；
  和預設版本同一個商品時不抓；`history_hours` 內已抓過不重抓；美國區只抓 `Config.purchase_options` 中指定的版本（D2）。
- [X] T020 [P] [US2] 新增 `tests/contract/test_store_options.py`：`purchase_options(app_ids, as_of)` 只回傳 `checked_at <= as_of` 最新一次的列
  （洩漏測試：之後的紀錄加入後，過去時點的結果不變，而且測試證明抓得到偷看）；`option_lows()` 回傳台灣區最低價、日期與第一筆時間，
  沒有歷史時為 None（不是 0）；已指定時，清單中的 Steam 預設版本讀預設版本的歷史（`itad-history`），不是 `itad-option-history`。
- [X] T021 [P] [US2] 在 `tests/integration/test_decision_engine.py` 新增 `editions` 的測試：依 Steam 的順序；只含 `role = edition`；
  未通過的附原因、`config_line` 為 null；可指定的 `config_line` = `1091500 = "bundle/32470"`；沒有購買選項紀錄時為 null、沒有版本時為空陣列。
- [X] T022 [P] [US2] 在 `tests/unit/report/test_html.py` 新增報告測試：摘要行「另有 N 個版本」（N = `len(editions)`）；沒有版本時不顯示；
  展開內容的表格欄位（名稱、現價、原價、歷史最低價與日期、歷史起點、設定行與複製按鈕、未通過的原因）；沒有歷史顯示「—（還沒有價格歷史）」。
- [X] T023 [P] [US2] 在 `tests/integration/` 新增 `test_update_options.py`：人工來源跑 `update`，寫出購買選項紀錄與版本歷史，摘要 `purchase_options`
  的欄位照 contracts/cli-and-report.md；`--no-history` 與沒有 ITAD 金鑰時略過。

### Implementation

- [X] T024 [US2] `src/steamsage/sources/__init__.py`（`BundleContents`、`VersionSource.bundle_contents`）與
  `src/steamsage/sources/steam_webapi.py`（GetItems `bundleid`）。
- [X] T025 [US2] `src/steamsage/sources/itad.py`：`lookup_ids(ids)`（`sub/N`、`bundle/N` 同一個請求，每批 200）。
- [X] T026 [US2] `src/steamsage/pipeline/verify.py`：`verify_version(..., option=None)`（R2）。
- [X] T027 [US2] 新增 `src/steamsage/pipeline/options.py`：購買選項步驟（判定、內容與類型的沿用、ITAD 對應、驗證與快取、Steam 現價筆數、
  寫 `purchase_options`、摘要與 alerts）。重用版本步驟取得的購買選項（`resolve_versions` 回傳或傳入 `options`），不另外請求。
- [X] T028 [US2] `src/steamsage/pipeline/daily.py`：步驟順序（現價 → 版本 → 購買選項 → 歷史價格）；歷史價格加入版本的台灣區與指定版本的美國區；
  摘要 `purchase_options`、alerts；`--no-history`／沒有金鑰時略過。
- [X] T029 [US2] `src/steamsage/store/query.py`：`purchase_options()`、`option_lows()`；`src/steamsage/decision/engine.py` 與
  `src/steamsage/decision/contract.py`：產生 `editions`（含 `config_line`、`is_default`、`unset_hint`）。
- [X] T030 [US2] `src/steamsage/report/html.py`：摘要行的版本數、展開內容的版本表格與複製按鈕（390px 不水平捲動）。
- [X] T031 [US2] 跑 `uv run pytest`；在真實資料上執行 `uv run steamsage update`（第一次遷移到 v4，記下各步驟耗時）與 `uv run steamsage report`：
  版本數是否等於當天清點（2026-09-27 為 26 款、33 個，其中可指定 25 款、32 個）；**SC-001**：沿用原型 P3 的方法——本分支讀完整的 v4 資料庫；
  master 讀一份副本，副本刪掉 `itad-option-history`／`itad-option` 的列與 `purchase_options` 表（只在副本上移除只新增的觸發器；
  master 沒有讀取修正，不能直接讀含版本歷史的資料庫）；68 款逐款相同（只多 `editions` 與選用欄位；比對腳本放
  `prototype/t029_same_data.py`，輸出在 `prototype/out/`）。
  **Checkpoint**：commit，並向使用者報告耗時與清單（附報告，`SendUserFile`）。

---

## Phase 4: User Story 1 — 看到我想買的版本的甜蜜價（P1，MVP）

**Goal**：設定檔指定一個版本後，那款遊戲的預測、甜蜜價、分組、現價與原因改用那個版本；其他遊戲逐款不變。

**Independent Test**：人工資料上兩個版本折扣不同，指定後只用指定版本的歷史；真實願望清單上指定 Cyberpunk 2077 終極版，原價 NT$2,206，其他 67 款不變。

### Tests（先寫、確認會失敗）

- [X] T032 [P] [US1] 在 `tests/contract/test_cli_report.py` 新增：`report` 把 `Config.purchase_options` 傳給 `run_decisions`（設定解析本身已在 T008）。
- [X] T033 [P] [US1] 在 `tests/contract/test_store_options.py` 新增 `option_keys()` 的測試：可用的版本 → `basis = user`、`source = user`；
  指定的剛好是 Steam 預設 → 仍是 `user`，之後 Steam 換預設也不變（FR-006）；版本商品等於預設商品 → `same_as_default`；
  版本最新紀錄 `itad_steam_deals = 0` 且仍在販售 → `stopped`，「已知至」截在最後確認時間、決策為低信心（006 FR-010），**不退回預設**。
- [X] T034 [P] [US1] 在 `tests/integration/test_forecast_engine.py` 新增 `run_forecast(targets=)` 的測試：指定的遊戲只用版本的歷史；
  其他遊戲的預測逐款相同；整體比例（`population_view`）只從預設版本計算——構造「把版本放進整體比例會改變其他遊戲」的資料，證明測試抓得到。
- [X] T035 [P] [US1] 在 `tests/integration/test_ns_report_flow.py` 新增 `ns_forecast(targets=)` 的測試：同上，非季節預測的整體比例不受指定影響。
- [X] T036 [P] [US1] 在 `tests/unit/decision/test_prices.py` 新增指定選項的現價測試：取購買選項紀錄與版本歷史中較新者；確認時間是那一列的時間；
  原價不一致和版本歷史的原價比較；過期判定不變。
- [X] T037 [P] [US1] 新增 `tests/contract/test_options_contract.py`（contracts/outputs-options.md 的保證 1–5）：`version.source`、`option`、`basis = user`；
  決策與預測的 `version` 完全相同；沒有指定時結果和 006 相同。
- [X] T038 [P] [US1] 在 `tests/unit/report/test_html.py` 新增版本行：`source = user` 時一律顯示「追蹤 X（使用者指定）· 歷史從 …」；
  美國區歷史還沒抓時，原因寫出「美國區歷史下一次更新才會取得」（D2）。

### Implementation

- [X] T039 [US1] `src/steamsage/commands.py`：`report` 讀 `ctx.config.purchase_options` 並傳給 `run_decisions`（設定解析已在 T013）。
- [X] T040 [US1] `src/steamsage/store/query.py`：`OptionKey`、`option_keys(choices, as_of, default_keys)`（research R4 的表格，先實作可用的情況，
  含 `stopped`／`last_confirmed`）；`HistoryKey.basis` 新增 `user`。
- [X] T041 [US1] `src/steamsage/forecast/engine.py`、`src/steamsage/forecast/contract.py`：`run_forecast(targets=)`（整體比例只用預設版本）、
  `VersionInfo` 新增 `source`、`option`、`fallback`；`version_to_dict` 輸出新欄位。
- [X] T042 [US1] `src/steamsage/forecast/nonseasonal/engine.py`：`ns_forecast(targets=)`（整體比例與模型準備用預設版本，指定遊戲的證據另外建）。
- [X] T043 [US1] `src/steamsage/decision/prices.py`：指定選項的現價；`src/steamsage/decision/engine.py`：`run_decisions` 讀設定的指定
  （新增參數 `choices`，`commands.py` 的 `report` 傳入 `ctx.config.purchase_options`）、解析、讀版本歷史、傳 `targets`、決策原因加一行
  「價格歷史來自使用者指定的購買選項 X（ITAD 從 YYYY-MM-DD 開始追蹤）」。
- [X] T044 [US1] `src/steamsage/report/html.py`：版本行的使用者指定與美國區提示。
- [X] T045 [US1] 跑 `uv run pytest`；在真實資料上把 Cyberpunk 2077 終極版的設定行加進 `steamsage.toml`（實驗完照使用者意思保留或移除），
  產生報告：原價 NT$2,206、甜蜜價依終極版；另外抽查指定 Granblue Fantasy: Relink 無盡黃昏（一般版）判為低信心、不借用標準版（FR-011）；**SC-002**：同一資料庫、指定前後，其他 67 款逐款相同（`prototype/t043_specify_same_data.py`）。
  **Checkpoint（MVP）**：commit，把報告交給使用者看（`SendUserFile`），**停下來等使用者確認**再繼續。

---

## Phase 5: User Story 3 — 指定的版本不能用時，我會知道（P2）

**Goal**：指定的版本下架、不是版本、ITAD 沒有對應或驗證未通過時退回預設並說明；設定錯誤被忽略並警告。

**Independent Test**：人工資料上 R4 表格的每一種情況都有明確原因或警告，其他遊戲不受影響。

- [X] T046 [P] [US3] 在 `tests/contract/test_store_options.py` 新增退回的測試：`not-offered`、`not-edition`、`not-in-itad`、`rejected`（附 006 的原因）、
  `no-record`（as_of 早於第一筆購買選項紀錄）；來源錯誤沒寫紀錄時沿用上一次並帶確認時間（FR-009）。
- [X] T047 [P] [US3] 在 `tests/integration/test_decision_engine.py` 新增：退回時 `version.source = user-fallback`、`fallback` 的 code／detail／requested，
  決策原因的文字照 contracts/outputs-options.md 的表格；設定中不在追蹤範圍的 App 被忽略，`run_decisions` 回傳警告。
- [X] T048 [P] [US3] 在 `tests/contract/test_cli_report.py` 新增：不在追蹤範圍的 App 的警告出現在摘要與 stderr；`update` 的 alerts 列出指定不能用的遊戲。
- [X] T049 [US3] 實作退回：`src/steamsage/store/query.py`（`option_keys` 的其他情況）、`src/steamsage/decision/engine.py`（原因與警告）、
  `src/steamsage/pipeline/options.py`（摘要 `specified.fallback`／`ignored` 與 alerts）、`src/steamsage/commands.py`（report 的警告輸出）、
  `src/steamsage/report/html.py`（退回時的版本行）。
- [X] T050 [US3] 跑 `uv run pytest`；在真實資料上試 quickstart §5 的四種設定，確認原因措辭（FR-016 抽查），試完移除。**Checkpoint**：commit 並報告。

---

## Phase 6: User Story 4 — 換版本時，變動標示說得清楚（P2）

**Goal**：指定、取消指定、退回預設後的第一份報告標示版本更換與原因；決策紀錄保存追蹤的選項與來源。

**Independent Test**：人工紀錄的四種 `cause` 都在第一份報告出現、第二份不再出現；舊紀錄（沒有 `option`）照常比較。

- [X] T051 [P] [US4] 在 `tests/unit/decision/` 新增 `test_changes_options.py`：`cause` 的四種情況（`user`、`unset`、`fallback`、`steam`）；
  前一次紀錄沒有 `option` 時用 `package_id` 視為 `sub/<id>`；只換套件、商品相同不算更換；甜蜜價與分組的「上次」照常。
- [X] T052 [P] [US4] 在 `tests/unit/report/test_html.py` 新增變動欄的四種文字（contracts/outputs-options.md）。
- [X] T053 [US4] 實作：`src/steamsage/decision/changes.py`（比較追蹤的購買選項、`cause`）、`src/steamsage/report/html.py`（變動文字）。
- [X] T054 [US4] 跑 `uv run pytest`；在真實資料上：指定 → 正式報告（出現「使用者指定」）→ 再一次（不出現）→ 取消指定（出現「取消指定」）。
  注意正式紀錄會寫入 `data/forecasts/`，實驗前先告訴使用者，完成後照使用者意思保留或恢復設定。**Checkpoint**：commit 並報告。
  （2026-09-27：已用只讀腳本 `prototype/t054_changes.py` 以正式的比較程式驗證四種情況；使用者 2026-09-27 決定不另外寫入正式紀錄。）

---

## Phase 7: Polish & Cross-Cutting

- [X] T055 [P] 更新 `docs/model/model-definition.md`：資料定義（使用者指定版本、版本歷史的來源、整體比例只用預設版本）；
  「決策規則」已知限制 1 改寫（其他版本可列出與指定；含其他遊戲的組合包仍不支援）。不附加比較文件（模型與規則沒有改）。
- [X] T056 [P] 更新 `README.md`：如何指定版本（複製報告的設定行）、如何取消；`[purchase_options]` 範例。
- [X] T057 跑 quickstart 全部步驟，寫 `specs/009-purchase-options/validation.md`：SC-001～SC-009 的結果、實測耗時（update 各步驟、report）、
  指定前後的逐款比對、原因措辭抽查（Cyberpunk、Granblue 無盡黃昏、Dying Light 十週年完整版）、
  `uv run steamsage backtest-rule --cutoff 2026-09-25` 的資料集識別碼仍是 `d493ac02…`（SC-007）；功能測試與預測準確度分開報告（SC-009）。
- [X] T058 更新 `HANDOFF.md`（009 完成、現況、下一個方向的候選：同時含多款願望清單遊戲的組合包等）與專案記憶
  （`feature009-preSpec` 改為 009 的決定與結果、`MEMORY.md` 索引）。
- [X] T059 跑 `uv run pytest`（全部通過）；commit，並詢問使用者是否合併到 master。

---

## Dependencies & Execution Order

- **Phase 1 → Phase 2 → US2 → US1 → US3 → US4 → Polish**。
- **US2** 依賴 Phase 2 全部（含 T013 的設定解析，T019、T028 用到）。
- **US1** 依賴 US2 的 T027–T029（購買選項紀錄、版本歷史、`purchase_options()`）。
- **US3** 依賴 US1 的 T040、T043。**US4** 依賴 US1 的 T041（`version.source`、`option`）。
- **Polish**：T057 依賴 T054；T058 依賴 T057。

**使用者決策點**（實作會停下來等）：

| 任務 | 等什麼 |
|---|---|
| T031 | 看過版本清單與耗時（若 SC-008 超過 30 秒，先說明原因與選項） |
| T045 | 看過 MVP 報告（指定 Cyberpunk 2077 終極版） |
| T054 | 同意在真實資料上寫入測試用的正式紀錄 |
| T059 | 是否合併 |

## Parallel Opportunities

- **Setup**：T001、T002 同時。
- **Phase 2**：T003–T008 是不同的測試檔，可以同時寫；實作 T009 → T010 → T011 → T012，T013 獨立。
- **US2**：T015–T023 可以同時寫；實作 T024、T025、T026 可以並行，之後 T027 → T028 → T029 → T030。
- **US1**：T032–T038 可以同時寫；實作 T039 → T040 → T041 → T042 → T043 → T044。
- **US3**：T046–T048 同時寫。**US4**：T051、T052 同時寫。
- **Polish**：T055、T056 並行。

```text
# US2 測試並行
T015 tests/unit/test_steam_webapi_versions.py
T016 tests/unit/test_itad_prices.py
T017 tests/unit/test_verify.py
T018 tests/unit/test_options.py
T019 tests/unit/test_history_ingest.py
T020 tests/contract/test_store_options.py
T021 tests/integration/test_decision_engine.py
T022 tests/unit/report/test_html.py
T023 tests/integration/test_update_options.py
```

## Implementation Strategy

1. **Foundational 先確保「什麼都沒變」**：schema v4、版本歷史的來源與讀取修正上線後，既有測試全部通過，資料集識別碼不變。
2. **US2**：每日記錄購買選項、列出版本；在真實資料上確認 26 款、33 個（可指定 25 款、32 個）與耗時（T031）。
3. **MVP = US1**：指定 Cyberpunk 2077 終極版，其他遊戲逐款不變，報告交給使用者（T045）。
4. **US3、US4**：退回預設與變動標示。
5. **Polish**：文件、驗收、HANDOFF。
6. **每個 checkpoint**：跑測試、在真實資料上執行、commit、報告。
