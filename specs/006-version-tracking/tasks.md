---

description: "Task list for feature 006: version tracking"
---

# Tasks: 版本追蹤

**Input**：`specs/006-version-tracking/` 的 plan.md、spec.md、research.md、data-model.md、contracts/、quickstart.md

**Tests**：憲章要求核心邏輯測試先行。每個實作任務前都有對應的測試任務：先寫測試並確認它會失敗，再實作。

**Organization**：依使用情境分組。執行順序：Setup → Foundational → US1（MVP，先給使用者看報告）→ US3 → US2 → US4 → Polish。

| 情境 | 內容 | 優先 |
|---|---|---|
| US1 | 預測用的是我買得到的那個版本 | P1 |
| US2 | 版本換了或 ITAD 停止追蹤時，我會知道（含規則 2.1.0） | P1 |
| US3 | 無法正確對應時，清楚說明原因 | P2 |
| US4 | 知道這個 feature 對回測的影響 | P3 |

## Format: `[ID] [P?] [Story] Description`

- **[P]**：可以並行（不同檔案，也不依賴未完成的任務）
- **[Story]**：所屬的使用情境（US1–US4）
- 路徑都相對於 repo 根目錄

## 共用約定（每個任務都適用）

- **版本的定義**（research R1）：預設購買選項 = App 在 `GetItems`（`include_all_purchase_options`）的購買選項中，
  **只看有 `packageid` 的選項**，原價（`original_price_in_cents`，沒有時用 `final_price_in_cents`）與售價都和同一次更新的
  `price_overview`（`initial`、`final`）相同的那一個。剛好 1 個才算；0 個或 2 個以上是 `ambiguous`。
- **擴充驗證**（research R2）：
  - `bundle/…` 拒絕，`reason_code = "bundle"`，`reason_detail = "bundle/<id>"`。
  - `app/X`：X 必須是 N 或 Steam 的 canonical app id 為 N（沿用 001）。
  - `sub/X`：內容是 N 加零或多個 DLC（`GetItems` 的 `type == 4` 且 `related_items.parent_appid == N`），否則 `other-games`；
    價格**取自 App 自己的購買選項**：X 在販售中而價格和預設選項不同 → `price-mismatch`；X 不在販售或無法公開查詢 → 只警告。
  - 版本商品和 App 本身的 001 對應相同、而且 001 已通過：沿用（`verified_by = "own-mapping"`），不發請求。
  - 同一商品 7 天內（`mapping_days`）已驗證：沿用（`verified_by = "cached"`）；商品一變就重新驗證。
- **資料表**（data-model）：`app_versions` 的欄位、`status ∈ {ok, no-option, ambiguous, not-in-itad}`、
  `verification ∈ {verified, rejected}`（`status ≠ ok` 為 NULL）、`verified_by ∈ {own-mapping, version-check, cached}`，
  `verified_at` = 驗證實際執行的時間（沿用時保留原始時間，憲章 II），照 data-model §1 原文實作。
- **時點**：所有讀取只用 `checked_at <= as_of` 的版本紀錄；本 feature 之前沒有紀錄的時點用 App 本身的商品。
- **資料集不變**：2026-09-25 截止的台灣區資料集識別碼必須仍是 `d547c29d…`（FR-016）。
- **只新增**：`app_versions` 加入 `APPEND_ONLY_TABLES`；既有表只在 v2 → v3 遷移中補 `external_id`。
- **分層**：`steamsage.report` 只讀決策契約的 dict（憲章 VII）；`version` 由預測核心決定，決策逐欄複製。
- **文字**：使用者看得到的文字用繁體中文；ITAD 與 Steam 的名稱只當資料顯示（憲章 IX）。
- **改檔案**：多行修改用 Edit 工具或 scratchpad 中的 Python 腳本，不用 Bash heredoc 改程式（HANDOFF §6）。
- **Checkpoint**：每完成一個，就跑 `uv run pytest`、commit（附 attribution trailer），並向使用者報告。要在真實資料上執行，不能只看測試。

---

## Phase 1: Setup

- [X] T001 [P] 在 `tests/fixtures/steam/` 新增錄製格式的回應（從 prototype 的真實回應精簡）：
  - `getitems_purchase_options.json`：App 239140（選項：套件 1345940 NT$670/134、套件 1265945 NT$749/149、組合包 49425）、
    App 9500003（套件 9900011 NT$226/56、組合包 99003）、App 1402110（套件 492077 NT$790/790、組合包 36647 比較便宜）。
  - `getitems_version_packages.json`：套件 1345940（`included_appids` = 239140 加 10 個 DLC）、1345941（`success` 15，無法公開查詢）、
    9900011（9500003）、一個含其他遊戲的套件。
  - `getitems_dlc_apps.json`：DLC `type` 4、`related_items.parent_appid` 239140；另一個 `type` 0 的遊戲。
- [X] T002 [P] 在 `tests/fixtures/itad/` 新增 `lookup_subs.json`（`sub/1345940` → Essentials、`sub/9900011` → 範例分季作品）、
  `reverse_lookup_versions.json`（Essentials：`sub/1345941`、`sub/1345940`；範例分季作品：`sub/9900011`、`bundle/99003`）、
  `prices_versions.json`（Essentials 1 筆 Steam 現價；舊 Dying Light 0 筆；範例分季作品 2 筆）、`history_essentials_TW.json`（原型 P3 的 23 筆）。
---

## Phase 2: Foundational（所有使用情境的前提）

**⚠️ 這個階段完成前，不開始任何使用情境。完成後所有既有測試（748）必須照樣通過，行為完全不變。**

- [X] T003 [P] 在 `tests/unit/test_schema_migration.py` 寫 v2 → v3 的測試：
  - v2 資料庫（兩款 App，各有 `source_mappings` 的一個 ITAD id；一款有兩個 id）遷移後：ITAD 歷史列與 `history_fetches` 補上 `external_id`；
    有兩個 id 的 App 保持 NULL；`steam-current` 保持 NULL；其他欄位逐列相同。
  - `app_versions` 存在且為空；`schema_version` 為 3；UPDATE／DELETE 觸發器（含 `app_versions`）都存在，UPDATE 會拋出 `append-only`。
  - 唯一索引：同一 App、同一時間、同一價格、不同 `external_id` 的兩列可以並存；相同 `external_id` 的重複列被忽略。
  - 備份：遷移前產生 `steamsage.db.bak-v2`，已存在時不覆蓋。
  - 遷移中途失敗（模擬例外）時回滾，資料庫仍是 v2。
  - 既有的 v1 測試改成 v1 → v3 連續遷移，斷言 `schema_version` 為 3。
- [X] T004 [P] 在 `tests/unit/test_store_writer.py` 寫測試：`NewObservation.external_id`（預設 None）寫入；`add_version()` 寫入 `app_versions` 一列並回傳 id；
  `record_price_check` 寫入 `external_id` 與 `itad_steam_deals`。
- [X] T005 [P] 在 `tests/contract/test_store_series.py` 寫測試：`series_rows(..., keys={app: ext})` 只回傳相符的列，NULL 列視為 App 本身商品；
  `history_known_until_all(region, keys=…)` 依 `(app_id, external_id)` 計算；`keys` 為「App 本身商品」時，結果和 v2 的呼叫完全相同。
  另外：`PriceStore.open` 開啟 v2 資料庫拋出錯誤，訊息「資料庫是舊版（v2），請先執行 steamsage update 升級」；`report` 對 v2 資料庫結束代碼 1。
- [X] T006 實作 `src/steamsage/store/schema.py`：`SCHEMA_VERSION = 3`、新欄位、`app_versions`（data-model §1 的欄位與索引 `(app_id, checked_at)`）、
  `APPEND_ONLY_TABLES` 加 `app_versions`、唯一索引重建為 data-model §2 的定義、`_migrate_v2_to_v3()`（data-model §3：先用 sqlite backup API 備份，
  同一交易中暫時移除 UPDATE 觸發器、補值、重建索引、恢復觸發器），`migrate()` 支援 v1 → v2 → v3。
- [X] T007 在 `tests/forecast_builders.py` 新增 `add_version(writer, app_id, checked_at, *, external_id, package_id=…, status="ok",
  verification="verified", itad_steam_deals=1, price_cents=…)`，以及寫入帶 `external_id` 的 ITAD 歷史列的 helper。依賴 T006。
- [X] T008 實作 `src/steamsage/store/writer.py`：`NewObservation.external_id`、INSERT 帶 `external_id`、`add_version()`；
  `src/steamsage/pipeline/history.py` 的 `record_price_check` 帶 `external_id`、`itad_steam_deals`。
- [X] T009 實作 `src/steamsage/store/query.py`：`own_keys(app_ids)`（`source_mappings` 最新的 ITAD id）、`series_rows`／`observations`／
  `latest_observations`（只過濾 ITAD 列）／`history_known_until(_all)` 的 `keys` 參數。唯讀開啟 v2 以下的資料庫時拋出清楚的錯誤：
  「資料庫是舊版（v2），請先執行 steamsage update 升級」。
- [X] T010 寫入路徑都帶 `external_id`：`src/steamsage/pipeline/history.py`（`to_observations`、`ingest_history`、`history_fetches`）、
  `src/steamsage/pipeline/reference.py`、`src/steamsage/pipeline/legacy_import.py`；`src/steamsage/pipeline/consistency.py` 與 `src/steamsage/coverage.py`
  改用 App 本身商品的 `keys` 過濾。先在 `tests/unit/test_history_ingest.py`、`test_legacy_import.py`、`test_consistency.py`、`test_coverage.py`
  加上「寫入帶 id」與「另一個商品的列不混入」的測試。
- [X] T011 `src/steamsage/sources/itad.py`：`parse_prices` 另外回傳每個商品的 Steam 現價筆數（新函式 `steam_deal_counts`，或 `current_prices` 回傳附帶筆數的結構），
  `src/steamsage/sources/__init__.py` 的 `HistorySource` 同步；先在 `tests/unit/test_source_protocols.py` 或新檔寫 0／1／2 筆的測試。
- [X] T012 **Checkpoint**：`uv run pytest` 全部通過。在**資料庫複本**上（scratchpad，用 backup API 複製）執行遷移並記錄耗時；
  在複本上以 `--cutoff 2026-09-25` 重建台灣區資料集，識別碼仍是 `d547c29d…`。commit，向使用者報告遷移耗時。

---

## Phase 3: User Story 1 - 預測用的是我買得到的那個版本（Priority: P1）🎯 MVP

**Goal**：每日更新記錄每款遊戲的版本並抓它的歷史；預測、決策與報告都用目前版本的歷史。

**Independent Test**：人工資料中 App 本身與預設選項對應到不同 ITAD 商品，預測只用後者的歷史；真實願望清單上 Dying Light 的原價是 NT$670，不再原價不一致。

### Tests for User Story 1

- [X] T013 [P] [US1] `tests/unit/test_steam_store.py`（或新檔 `tests/unit/test_steam_webapi_versions.py`）：
  - `parse_purchase_options`：只取有 `packageid` 的選項，原價缺漏時用售價；組合包（`bundleid`）不當成套件。
  - 套件查詢解析 `included_appids`、`success`；App 查詢解析 `type` 與 `related_items.parent_appid`。
  - 使用 T001 的 fixture。
- [X] T014 [P] [US1] `tests/unit/test_verify.py` 新增 `verify_version` 的測試（共用約定的擴充驗證）：
  - Essentials（本體＋10 個 DLC、`sub/1345941` 無法公開查詢）→ `verified`，一個警告。
  - 含 `bundle/99003` → `rejected`、`bundle`、detail `bundle/99003`。
  - 套件含 `type 0` 的其他遊戲 → `other-games`，detail 列出 App id。
  - 別名中的另一個套件在販售、價格不同 → `price-mismatch`；不在販售 → 只警告。
  - Eternights 情境：套件本身 `best_purchase_option` 是組合包，但價格取自 App 的購買選項 → `verified`。
  - 001 的 `verify_mapping` 行為不變（既有測試照樣通過）。
- [X] T015 [P] [US1] `tests/unit/test_versions.py`（新檔）測 `src/steamsage/pipeline/versions.py`：
  - 預設選項：唯一相符 → `ok`；0 個或 2 個 → `ambiguous`；沒有 `price_overview` → `no-option`；ITAD 查不到 → `not-in-itad`。
  - 和 App 本身相同且 001 已通過 → `verified_by = own-mapping`，不呼叫驗證的來源（用計數的假來源證明）。
  - 不同 → `version-check`，`verified_at = checked_at`；隔天同一商品 → `cached`，`verified_at` 是前一天那次驗證的時間；
    `own-mapping` 的 `verified_at` 是 001 對應的 `checked_at`；7 天後重新驗證；商品改變立刻重新驗證（FR-004）。
  - 每款寫一列 `app_versions`，含 `package_name`、價格、`itad_title`、別名、`itad_steam_deals`。
  - 版本來源拋出 `SourceError` → 不寫任何列、回傳 alert，其他步驟照常（FR-011）。
- [X] T016 [P] [US1] `tests/contract/test_store_versions.py`（新檔）：`PriceStore.versions()`、`history_keys()`：
  - 依 `checked_at <= as_of` 取最新一列；`verified` → basis `version`；`rejected` → basis `rejected`；
    `no-option`／`ambiguous`／`not-in-itad`／沒有紀錄 → basis `own` 與對應的 `basis_reason`。
  - **洩漏**：as_of 之後才寫的版本紀錄不影響結果；另外寫一個「故意偷看」的查詢版本，證明測試會失敗（002 的寫法）。
- [X] T017 [P] [US1] `tests/integration/test_forecast_engine.py` 新增：同一 App 有兩個 ITAD 商品的歷史，版本紀錄指向新商品時，
  `run_forecast` 只用新商品的台灣區與美國區歷史、`regular_price_cents` 是新商品的原價，輸出 `version`（contracts/outputs-version.md 的欄位）；
  沒有版本紀錄時結果和現在完全相同。
- [X] T018 [P] [US1] `tests/unit/decision/test_prices.py`：`current_prices` 的 `history_regular` 與確認時間依版本商品計算；
  Dying Light 情境（Steam NT$670、新商品 NT$670）→ `regular_mismatch` 為假。
- [X] T019 [P] [US1] `tests/integration/test_update_versions.py`（新檔，沿用 `test_update_us1.py` 的 FakeSteam 寫法，加上假的 ITAD）：
  - `update` 在「現價」之後、「歷史價格」之前跑版本步驟，進度文字 `版本 n/N`。
  - 換過版本的 App 只抓新商品的歷史（台灣區、美國區），列帶新 `external_id`；不再抓舊商品。
  - 摘要 `versions`（contracts/cli-and-report.md 的欄位）與 alert「…改用 … 的價格歷史」。
  - v2 資料庫第一次 `update` 自動遷移，stderr 出現「資料庫升級到 v3」。
  - `update --no-history`：不跑版本步驟、不寫 `app_versions`，摘要 `versions = {"skipped": "no-history"}`；
    沒有 `ITAD_API_KEY`：`{"skipped": "no-itad-key"}` 加 alert（contracts/cli-and-report.md）。
- [X] T020 [P] [US1] `tests/unit/report/test_html.py`：決策 dict 的 `version.itad_title` 和 App 名稱不同時，名稱下方顯示
  「追蹤 <package_name> · 歷史從 <history_start 日期> 起」；相同時不顯示。

### Implementation for User Story 1

- [X] T021 [US1] `src/steamsage/sources/__init__.py`：`PurchaseOption`、`VersionPackage`、`AppKind` 資料類別與 `VersionSource` 協定；
  `src/steamsage/sources/steam_webapi.py`：`purchase_options(app_ids)`、`version_packages(package_ids)`、`app_kinds(app_ids)`（都用 `GetItems`，50 個一批）。
- [X] T022 [US1] `src/steamsage/pipeline/verify.py`：`verify_version(app_id, aliases, *, default_package, options, packages, kinds, metadata)`，
  回傳 `VerifyResult` 加 `reason_detail`。
- [X] T023 [US1] `src/steamsage/pipeline/versions.py`：`resolve_versions(writer, sources, apps, lookups, own_mappings, *, run_id, now, max_age)`：
  判定預設選項 → ITAD `lookup_steam` 的 `sub/` 版本（`CachedHistory` 擴充 `lookup_subs`）→ 沿用或驗證 → 查 Steam 現價筆數 → 寫 `app_versions` → 回傳每款的版本與摘要。
- [X] T024 [US1] `src/steamsage/store/query.py`：`versions(app_ids, as_of)`、`history_keys(app_ids, as_of)`（data-model §4）。
- [X] T025 [US1] `src/steamsage/pipeline/daily.py`：新步驟 `update_versions`；`update_history` 依版本商品抓歷史、寫 `external_id`，
  價格核對用版本商品；摘要 `versions` 與 alerts。`src/steamsage/pipeline/history.py` 的新鮮度檢查依 `(app_id, region, external_id)`。
- [X] T026 [US1] `src/steamsage/forecast/engine.py`：`load_games` 用 `history_keys(apps, cutoff)`；`src/steamsage/forecast/contract.py`：
  `Forecast.version` 與 JSON 輸出；`src/steamsage/decision/prices.py`：依版本商品的原價與確認時間；
  `src/steamsage/decision/engine.py`、`contract.py`：決策逐欄複製 `version`。
- [X] T027 [US1] `src/steamsage/report/html.py`：名稱下方的版本行（T020）。
- [X] T028 [US1] **Checkpoint（真實資料，MVP）**：
  1. `uv run pytest` 全部通過。
  2. 真實資料執行 `uv run steamsage update`（會遷移），記錄遷移與版本步驟耗時；摘要應為 Dying Light 更換、範例分季作品 被拒絕（quickstart §3）。
  3. `uv run steamsage report --open`：Dying Light 原價 NT$670、不再原價不一致、決策與原型 P3 一致（即將到價，2026 秋特 NT$101），逐項解釋差異。
  4. **SC-002 在同一份資料上驗證**：scratchpad 腳本對同一個資料庫、同一個 as_of 跑兩次 `run_decisions`，一次照常（版本商品），
     一次把 `history_keys` 強制成 App 本身的商品（monkeypatch），逐款比較組別、甜蜜價、甜蜜時點、信心與原因；
     只允許 Dying Light 與 範例分季作品 不同，其他 100% 相同。不拿前一天的正式紀錄比（中間資料已更新）。
  5. commit，**用 SendUserFile 把報告給使用者看，等使用者確認再繼續**。

---

## Phase 4: User Story 3 - 無法正確對應時，清楚說明原因（Priority: P2）

**Goal**：驗證失敗、無法確認版本、來源錯誤時，每款遊戲都有明確狀態與人看得懂的原因。

**Independent Test**：人工資料中預設套件的 ITAD 商品含組合包，該遊戲為「無法預測」並寫出組合包；其他遊戲不受影響。

- [X] T029 [P] [US3] `tests/integration/test_forecast_engine.py`：`history_keys` 為 `rejected` 時狀態 `unverified`，`status_reason` 依 `reason_code`：
  - `bundle`：「ITAD 把 Steam 目前的購買選項（<package_name>）和組合包 <detail> 算成同一個商品，價格歷史混了不同商品的價格，無法使用」
  - `other-games`：「Steam 目前的購買選項（<package_name>）還包含其他遊戲（<detail>），不是這款遊戲本身」
  - `price-mismatch`：「ITAD 的商品同時對應到價格不同的購買選項，價格歷史可能混了不同版本」
  - basis `own` 且原因不是 `no-record`：決策原因加一行「無法確認 Steam 目前賣的版本（<原因>），沿用這款遊戲本身的價格歷史」。
  - basis `own` 且原因是 `no-record`（`--as-of` 早於第一筆版本紀錄）：原因加一行「這個時點沒有版本紀錄，沿用這款遊戲本身的價格歷史」（research R7）。
- [X] T030 [P] [US3] `tests/unit/test_versions.py`：來源錯誤的那一天不寫列，隔天的報告仍用前一筆版本，`version` 附確認時間（`checked_at`）。
- [X] T031 [P] [US3] `tests/unit/report/test_html.py`：「無法預測」組顯示 `status_reason`；basis `own`（非 `no-record`）顯示「無法確認 Steam 目前賣的版本，沿用 App 本身的價格歷史」；
  `no-record` 顯示「這個時點沒有版本紀錄，沿用 App 本身的價格歷史」。
- [X] T032 [US3] 實作：`src/steamsage/forecast/engine.py` 的 `_status`（原因文字）、`src/steamsage/decision/engine.py` 的原因行、`src/steamsage/report/html.py`。
- [X] T033 [US3] **Checkpoint**：真實資料 `report`：範例分季作品 - Season 1 的原因寫出 `bundle/99003`（FR-014 措辭抽查）。`uv run pytest`、commit、報告。

---

## Phase 5: User Story 2 - 版本換了或 ITAD 停止追蹤時，我會知道（Priority: P1）

**Goal**：版本更換有紀錄、有變動標示；ITAD 停止追蹤時「已知至」截短、決策降為低信心（規則 2.1.0）。

**Independent Test**：人工資料中版本在某天更換，下一次更新記錄更換、報告出現版本更換；版本紀錄的 Steam 現價筆數為 0 時，「已知至」截在最後確認時間、決策低信心。

### Tests for User Story 2

- [X] T034 [P] [US2] `tests/contract/test_store_versions.py`：
  - 版本更換的衍生（data-model §1）：相鄰兩列 `external_id` 不同 → `change` 含舊、新、偵測時間；只換 `package_id` → 不是更換；A → B → A 記錄兩次。
  - 第一列和 App 本身的 001 對應不同 → 視為一次更換（research R7）。
  - 停止追蹤：最新一列 `itad_steam_deals = 0` 且 `price_cents` 不是 NULL → `tracking = stopped`，`known_until = last_confirmed` =
    （該商品最新觀測, 最後一列 `itad_steam_deals ≥ 1` 的 `checked_at`）取較晚者；舊的 `current_price_checks` 不影響（FR-016）。
- [X] T035 [P] [US2] `tests/unit/forecast/test_series.py` 或 `tests/integration/test_forecast_engine.py`：停止追蹤時模型看不到「已知至」之後的季節特賣
  （原型 P3 stopped：只剩 2024 冬特一場）。
- [X] T036 [P] [US2] `tests/unit/decision/test_rule_v2.py`（2.1.0）與 `test_rule_v3.py`（3.1.0）：
  - `history_stopped=False` 時，2.1.0 對既有所有測試案例的結果和 2.0.0 逐欄相同（除 `rule`）；3.1.0 對 3.0.0 同理（參數化既有案例）。
  - `history_stopped=True` → `confidence = low`、標籤 `history-stopped`、低信心分組；2.0.0／3.0.0 忽略這個旗標（舊版本可重現）。
  - `CURRENT_RULE = "2.1.0"`；`rule_spec("2.1.0")`、`rule_spec("3.1.0")` 存在；`config.for_rule("2.1.0")` 同 2.0.0 的偏好，`for_rule("3.1.0")` 同 3.0.0。
  - `lookup_backtest("2.1.0", 現行模型)` 有數字（T043 之後填入）。
- [X] T037 [P] [US2] `tests/integration/test_decision_engine.py`：停止追蹤的決策原因含「價格歷史停止更新：ITAD 在 <日期> 之後就沒有這個商品在 Steam 的價格，之後的特賣視為未知；決策改為低信心」；
  版本更換的原因含「價格歷史來自 Steam 目前預設的購買選項 <package_name>（ITAD 從 <history_start> 開始追蹤）；<detected_at> 偵測到 Steam 換了版本，舊版本的歷史不使用」。
- [X] T038 [P] [US2] `tests/unit/decision/test_changes.py`：前一次紀錄的 `version.itad_id` 不同 → `change.version = {from, to, detected_at}`、標籤 `version-changed`；
  前一次紀錄沒有 `version` 時和 App 本身的商品比較；相同時不算變動；`/1`、`/2` 舊紀錄可讀。
- [X] T039 [P] [US2] `tests/contract/test_decision_contract.py`、`test_forecast_contract.py`：contracts/outputs-version.md 的保證 1–7。
- [X] T040 [P] [US2] `tests/unit/report/test_html.py`：變動欄「版本更換：舊 → 新（偵測於 日期）」；停止追蹤顯示「價格歷史停止更新（最後確認 日期）」；
  版本行加上「· <日期> 偵測到版本更換」；390px 版面不水平捲動的既有檢查照樣通過。

### Implementation for User Story 2

- [X] T041 [US2] `src/steamsage/store/query.py`：`versions()` 的更換與停止追蹤衍生、`history_known_until_all` 的截短；
  `src/steamsage/forecast/engine.py` 把 `tracking`、`last_confirmed`、`change` 放進 `version`。
- [X] T042 [US2] `src/steamsage/decision/rule.py`：`RULES` 加 `2.1.0`（同 2.0.0 常數，`stopped_low: True`）與 `3.1.0`（同 3.0.0，`stopped_low: True`）；
  `decide(..., history_stopped=False)`；`_path` 的低信心條件 = 信心為低 or 原價不一致 or（規則有 `stopped_low` 且 `history_stopped`）；
  標籤 `history-stopped`；`CURRENT_RULE = "2.1.0"`。`src/steamsage/config.py` 的 `for_rule` 支援新版本。
  `src/steamsage/decision/engine.py`、`prices.py` 傳入旗標與原因；`changes.py` 版本變動；`report/html.py` 顯示。
- [X] T043 [US2] **規則回測**（真實資料，唯讀）：
  1. `uv run steamsage backtest-rule --rule 2.1.0 --cutoff 2026-09-25` 與 2.0.0（同一截止時間重跑）逐案比較：scratchpad 腳本比對 `cases`、
     各組與各信心的彙總；另外在每個分析時點對資料集中每款遊戲直接呼叫 `decide()`，比較 2.0.0 與 2.1.0 的整個 `RuleResult`（除 `rule`），必須完全相同，
     並確認回測中 `history_stopped` 一次都沒有為真。`--split tuning` 同樣比較。
  2. 把 2.1.0 的數字加進 `rule.RULE_BACKTESTS`（`backtest.py` 的 `quoted_figures` 產生），測試 T036 的最後一項通過。
  3. 3.1.0：`backtest-rule --rule 3.1.0 --wait-cost 20` 與 3.0.0 逐案比較，相同後加入 `RULE_BACKTESTS`。
  4. `docs/model/comparisons.md` 只附加一筆「規則 sweet-price 2.1.0／3.1.0：不影響回測的資料品質規則（spec FR-018）」：資料集、逐案相同的證據、使用者同意日期 2026-09-26。
- [X] T044 [US2] **Checkpoint**：`uv run pytest`；真實資料 `report`：頁首出現「規則 sweet-price 2.0.0 → 2.1.0」；
  在資料庫複本上重跑原型 P3 的 stopped 情境（刪掉 Dying Light 的新版本紀錄、寫一列 `itad_steam_deals = 0` 的版本紀錄）確認低信心與原因。commit、報告。

---

## Phase 6: User Story 4 - 知道這個 feature 對回測的影響（Priority: P3）

**Goal**：資料集不變有證據；受影響的序列數寫進驗收文件。

**Independent Test**：同一截止時間重建資料集，識別碼不變；驗收文件有 FR-017 的表。

- [X] T045 [P] [US4] `tests/unit/forecast/test_dataset.py`：人工資料中加入版本紀錄（`checked_at` 晚於截止時間）前後，資料集識別碼相同；
  截止時間晚於版本紀錄時，使用新商品的序列（識別碼改變，符合 research R4 的已知限制）。
- [X] T046 [US4] 真實資料：`uv run steamsage backtest --cutoff 2026-09-25 --region TW` 的資料集識別碼仍是 `d547c29d…`；
  重跑 `prototype/p4_dataset_impact.py`（改讀遷移後的資料庫），數字寫進 `specs/006-version-tracking/validation.md` 的 FR-017 一節：
  停止追蹤、ITAD 多筆 Steam 現價、原價來回切換的款數，依調參組／驗證組分列，並寫建議（是否之後建立新版資料集）。

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T047 [P] `docs/model/model-definition.md`：
  - 資料一節：價格歷史跟著 Steam 預設購買選項（research R1、R2、R4），「已知至」的截短；已知限制 1 改寫（仍只看預設選項；21 款有其他選項）。
  - 決策規則：現行為 `sweet-price` 2.1.0（低信心條件加「價格歷史停止更新」）；3.1.0 候選；版本歷史加一列（2026-09-26 或實際日期）。
  - 規則回測數字標明 2.1.0 與 2.0.0 逐案相同。
- [X] T048 [P] `README.md`：版本追蹤的說明（報告上的版本行、版本更換、停止追蹤、無法預測的原因）、schema v3 與備份檔、`update` 摘要的 `versions`。
- [X] T049 [P] `specs/006-version-tracking/validation.md`：逐項驗收 SC-001–SC-008（quickstart），附實測耗時（遷移、版本步驟、report）；
  決策原因措辭抽查（Dying Light、範例分季作品、停止追蹤的複本）；功能測試與預測準確度分開寫；390px 檢查（`uv run --with playwright python 腳本`）。
- [X] T050 `HANDOFF.md` 改寫給下一個 feature：現況（規則 2.1.0、schema v3）、候選方向（季節特賣以外的折扣、到價機率校準、放寬 12 個月、
  使用者指定版本／其他購買選項的現價、001 驗證的價格來源、之後的新資料集）、本 feature 的教訓（套件的「最佳購買選項」可能是組合包；
  時間比對要用同一次更新的現價；ITAD 新商品的歷史起點可能晚於 Steam 換版本）。
- [X] T051 收尾：
  1. 跑 `uv run pytest`，應全部通過。
  2. 更新專案記憶（`feature006-decisions`、`steamsage2-rewrite-goals` 的現況）。
  3. commit，並詢問使用者是否合併到 master。

---

## Dependencies & Execution Order

- **Phase 1 → Phase 2 → US1 → US3 → US2 → US4 → Polish**。
- **US1** 依賴 Phase 2 全部。**US3** 依賴 T023、T024、T026（版本紀錄與預測輸出）。
- **US2** 依賴 US1；T043 依賴 T042；T044 依賴 T043。
- **US4**：T045 可以在 Phase 2 之後任何時候寫；T046 依賴 T028（真實資料已遷移）。
- **Polish**：T047 依賴 T043；T049 依賴 T044、T046。

**使用者決策點**（實作會停下來等）：

| 任務 | 等什麼 |
|---|---|
| T028 | 看過 MVP 報告（Dying Light 與其他遊戲的變化） |
| T043 | 若 2.1.0 與 2.0.0 **不是**逐案相同，停下來說明原因，不寫比較文件 |
| T051 | 是否合併 |

## Parallel Opportunities

- **Setup**：T001、T002 同時。
- **Phase 2**：T003、T004、T005 是不同的測試檔，可以同時寫；實作 T006 → T008 → T009 → T010，T011 獨立。
- **US1**：T013–T020 是不同的測試檔，可以同時寫；實作 T021 → T022 → T023 → T024 → T025 → T026 → T027。
- **US2**：T034–T040 可以同時寫；實作 T041 → T042。
- **Polish**：T047–T049 可以並行。

```text
# US1 測試並行
T013 tests/unit/test_steam_webapi_versions.py
T014 tests/unit/test_verify.py
T015 tests/unit/test_versions.py
T016 tests/contract/test_store_versions.py
T017 tests/integration/test_forecast_engine.py
T018 tests/unit/decision/test_prices.py
T019 tests/integration/test_update_versions.py
T020 tests/unit/report/test_html.py
```

## Implementation Strategy

1. **Foundational 先確保「什麼都沒變」**：schema v3 與依商品過濾上線後，748 個既有測試照樣通過，資料集識別碼不變。
2. **MVP = US1**：Dying Light 改用 Essentials Edition 的歷史，報告交給使用者（T028）。
3. **US3**：範例分季作品 的原因。
4. **US2**：版本更換與停止追蹤的標示，規則 2.1.0（逐案相同才記錄）。
5. **US4 與 Polish**：資料集影響、文件、驗收。
6. **每個 checkpoint**：跑測試、在真實資料上執行、commit、報告。
