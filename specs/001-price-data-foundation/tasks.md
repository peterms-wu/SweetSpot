---
description: "Task list for feature 001-price-data-foundation"
---

# Tasks: 價格資料基礎

**Input**: `specs/001-price-data-foundation/` 下的 plan.md、spec.md、research.md、data-model.md、contracts/、quickstart.md

**Tests**: 憲章「開發流程與品質關卡」要求核心邏輯**測試先行**，所以每個使用情境都先寫會失敗的測試，再實作。

**Organization**: 依使用情境分組。P2 的順序依 plan.md 的建議調整為 US5 → US7 → US4：先匯入舊快取，可以及早驗證資料格式。

## Format: `[ID] [P?] [Story] Description`

- **[P]**：可平行進行（不同檔案、不依賴未完成的任務）
- **[Story]**：所屬使用情境（US1–US7）
- 路徑以專案根目錄為準（`src/steamsage/`、`tests/`），屬於單一專案結構

---

## Phase 1: Setup

- [X] T001 建立 `pyproject.toml`：套件名稱 `steamsage`、`requires-python = ">=3.12"`、依賴 `httpx`、`tzdata`，dev 依賴 `pytest`，
  script 入口 `steamsage = "steamsage.cli:main"`，採 src 版面。執行 `uv sync` 產生 `uv.lock`
- [X] T002 建立 plan.md 列出的套件骨架：`src/steamsage/__init__.py`（含 `__version__`）、`src/steamsage/__main__.py`、
  `src/steamsage/store/__init__.py`、`src/steamsage/sources/__init__.py`、`src/steamsage/pipeline/__init__.py`、
  `tests/unit/`、`tests/contract/`、`tests/integration/`、`tests/fixtures/`、`tests/conftest.py`（提供暫存資料庫 fixture）
- [X] T003 [P] 更新 `.gitignore`，加入 `data/steamsage.db*`、`data/.lock`、`data/logs/`、`.venv/`、`__pycache__/`、
  `.pytest_cache/`、`*.egg-info/`、`steamsage.toml`。**不排除** `data/steam_sales.toml`

---

## Phase 2: Foundational（所有使用情境的前提）

**⚠️ 這個階段完成前，不開始任何使用情境。**

- [X] T004 [P] 在 `tests/unit/test_timeutil.py` 寫測試：
  - `+02:00`／`+01:00` 轉成 UTC
  - ITAD 的 `since` 輸出格式為 `%Y-%m-%dT%H:%M:%SZ`，不得有小數秒
  - Steam 發售日可解析 `%d %b, %Y`、`%b %d, %Y`、`%Y-%m-%d`，無法解析時回傳 None
  - 「加 N 個曆月」在月底沒有同一天時取當月最後一天
- [X] T005 [P] 實作 `src/steamsage/timeutil.py`，讓 T004 通過
- [X] T006 [P] 在 `tests/unit/test_config.py` 寫測試（依 contracts/config.md）：
  - 設定檔不存在時，以預設值建立
  - 未知欄位只警告
  - `market.region` 不是 `"TW"` 時報錯
  - 願望清單網址必須符合 `https://store.steampowered.com/wishlist/profiles/<17 位數字>/`
  - 金鑰從環境變數讀取；程序環境沒有時，改讀 `HKCU\Environment`
  - 金鑰物件的 `repr`／`str` 不會顯示金鑰內容
- [X] T007 [P] 實作 `src/steamsage/config.py`：`Config` dataclass 與 `Secrets`（`itad_api_key`、`steam_web_api_key`，repr 會遮蔽），讓 T006 通過
- [X] T008 [P] 在 `tests/unit/test_lock.py` 寫測試：
  - 第二個鎖取得失敗，並回報持有者的 PID
  - 持有者 PID 已經不存在時，可以接管
- [X] T009 [P] 實作 `src/steamsage/lock.py`，鎖檔為 `data/.lock`，內容為 PID 與開始時間，讓 T008 通過
- [X] T010 [P] 在 `tests/unit/test_store_writer.py` 寫測試：
  - data-model 第 1–8 節的所有資料表都會建立
  - 「金額以分為整數；**NULL 表示未知，0 表示已知零元**」
  - 唯一鍵 (`app_id`, `source`, `region`, `observed_at`, `price_cents`, `regular_cents`, `cut_pct`) 重複寫入時忽略
  - 異常資料標記為 `negative-price`、`price-above-regular`、`observed-after-retrieved`、`currency-mismatch`
  - 單一 app 的 transaction 失敗時整筆 rollback，不影響其他 app
  - 事實與觀測資料表沒有 UPDATE 或 DELETE 路徑
- [X] T011 實作 `src/steamsage/store/schema.py`：依 data-model.md 建立 `runs`、`run_item_results`、`wishlist_syncs`、
  `wishlist_items`、`wishlist_membership`、`products`、`product_facts`、`source_mappings`、`price_observations`、
  `current_price_checks`、`reference_candidates`、`catalog_progress`、`steam_app_list`、`sale_estimates`、
  `region_consistency`，並加上 `schema_version` 與 `migrate()`，使用 `PRAGMA journal_mode=WAL`
- [X] T012 實作 `src/steamsage/store/writer.py`，讓 T010 通過：
  - `start_run`、`finish_run`、`mark_interrupted_runs`（status `running` 且鎖的 PID 已不存在時，改為 `interrupted`）
  - `record_item_result`，stage 限定為 `wishlist`、`current-price`、`metadata`、`mapping`、`history-tw`、`history-aux`、`reference`、`import`；
    status 限定為 `ok`、`reused`、`skipped`、`failed`、`unsupported`
  - `add_observations`：去重並偵測異常
  - `add_facts`：volatility 為 `static` 或 `volatile`
  - `add_mapping`
- [X] T013 [P] 在 `tests/contract/test_store_as_of.py` 寫 contracts/store-api.md 的保證事項：
  - 保證 1：所有回傳的觀測都滿足 `observed_at <= as_of`
  - 保證 2：預設排除異常資料
  - 保證 3：輔助區域的金額欄位一定是 None
  - 保證 5：依 observed_at 升冪排序，同一時點依 source 名稱排序
- [X] T014 實作 `src/steamsage/store/query.py`：唯讀的 `PriceStore.open()`、`observations()`、`wishlist_apps()`，以及
  `Observation`、`Fact`、`ProductFacts`、`SaleEvent` dataclass（依 store-api.md），讓 T013 通過
- [X] T015 [P] 在 `tests/unit/test_http.py` 用 `httpx.MockTransport` 寫測試：
  - 同一來源的請求間隔不小於設定值
  - 5 分鐘滾動視窗的請求上限
  - 429／5xx 等待 `max(Retry-After, 2^n)` 秒，Retry-After 支援秒數與 HTTP-date 兩種格式，最多重試 3 次
  - 401／403 會拋出 `SourceDisabled`，之後同一來源的請求不再送出
  - 錯誤訊息與日誌中的金鑰（query 參數 `key` 與 header `ITAD-API-Key`）都被遮蔽
  - 每個請求都帶自訂 User-Agent
  - 回應超過 8 MB 時中止
- [X] T016 實作 `src/steamsage/sources/http.py` 的 `RateLimitedClient(min_interval, window_limit, window_seconds, timeout)`，讓 T015 通過。
  逾時設定：連線 10 秒、讀取 30 秒
- [X] T017 在 `src/steamsage/sources/__init__.py` 定義 `WishlistSource`、`CurrentPriceSource`、`HistorySource`、`MetadataSource`
  Protocol。pipeline 模組只能依賴 Protocol，不得直接 import 具體的 client（FR-010）。新增 `tests/unit/test_source_protocols.py`：
  用假來源實作 Protocol，並檢查 `src/steamsage/pipeline/` 下沒有任何檔案 import `steamsage.sources.itad`、`steam_store` 或 `steam_webapi`
- [X] T018 [P] 實作 `src/steamsage/logs.py`：寫入 `data/logs/`，並加上遮蔽金鑰的 logging filter（從 Secrets 取得要遮蔽的字串）
- [X] T019 實作 `src/steamsage/cli.py` 骨架（依 contracts/cli.md）：
  - argparse 子指令 `update`、`reference`、`import-legacy`、`coverage`、`calendar`，共用 `--config`、`--json`
  - exit codes：0 完成、2 部分失敗、1 整批失敗、3 已有更新在執行
  - 進度輸出到 stderr，摘要輸出到 stdout
  - 取得鎖，並在啟動時呼叫 `mark_interrupted_runs`

**Checkpoint**：`uv run pytest -q` 全部通過；`uv run steamsage --help` 可以執行。

---

## Phase 3: User Story 1 - 同步願望清單並取得現價 (P1) 🎯 MVP

**Goal**：一鍵同步願望清單，並為每款遊戲新增一筆台灣區現價觀測。

**Independent Test**：用固定 fixture 連續執行兩次 `update --no-history`，每款遊戲都有 2 筆 `steam-current` 觀測，或有明確的失敗原因。

### Tests (US1)

- [X] T020 [P] [US1] 新增 `scripts/record_fixtures.py`，實際呼叫 GetWishlist（steamid 〈SteamID〉）、
  `appdetails?appids=620,413150,1145360&cc=tw&filters=price_overview`、`appdetails?appids=620&cc=tw&l=tchinese`、
  GetItems、`appreviews/620`，並把回應存成 `tests/fixtures/steam/*.json`。存檔前確認不含金鑰。
  另外手寫私人清單、格式錯誤、超過 500 款、含重複 AppID 的 fixture
- [X] T021 [P] [US1] 在 `tests/unit/test_wishlist.py` 寫測試：
  - 拒絕原因 `private`、`rate-limited`、`malformed`、`incomplete`、`duplicate-appid`、`invalid-appid`、`over-limit`（超過 500 款）、`network`，
    被拒絕時不寫入 `wishlist_items`，也不改變 membership 狀態
  - 明確的空清單以 status `empty` 保存
  - 狀態轉換 `in_wishlist → removed_tracking → reference_only`，其中 `track_until = removed_at + 24 個曆月`；重新加入時回到 `in_wishlist`
- [X] T022 [P] [US1] 在 `tests/unit/test_steam_store.py` 寫測試：
  - appdetails 的結果以 `data.steam_appid` 作為 key，不用外層 key
  - `price_overview` 的金額是整數分
  - `filters=price_overview` 的批次解析
  - Indie 判定：genre 的 description 為 "Indie"／"獨立" 或 id 為 "23" 時為 True，沒有 genres 時為 None
  - 分類：`coming_soon` 為未發行；`is_free` 為已知零元；沒有 price_overview 且不是免費時為無法購買；type 為 package 或 bundle 時為 unsupported
  - appdetails 回傳 `success:false` 時，資料庫已有該遊戲的資料則為 `delisted`，沒有則為 `not-found`（FR-006）
- [X] T023 [P] [US1] 在 `tests/integration/test_update_us1.py` 寫測試：MockTransport 兩次執行 `update --no-history`，
  - 每款遊戲有 2 筆觀測，且 `observed_at == retrieved_at`
  - 第二次清單被拒絕時，沿用上次成功的清單
  - JSON 摘要中沒有任何無狀態的遊戲（SC-002）
  - 清單移除的遊戲出現在 `wishlist.removed`

### Implementation (US1)

- [X] T024 [US1] 實作 `src/steamsage/sources/steam_webapi.py`：
  - `get_wishlist(steamid)`，不帶金鑰
  - `get_items(appids, country="TW", language="tchinese")`，批次請求 basic_info、release、reviews、tag
  - `get_app_list(key, last_appid, max_results≤50000)`，給 US4 使用
- [X] T025 [US1] 實作 `src/steamsage/sources/steam_store.py` 的 `appdetails_full(appid)`、`appdetails_prices(appids)`、
  `packagedetails(ids)`、`appreviews_summary(appid)`，節流間隔 1.5 秒，讓 T022 通過
- [X] T026 [US1] 實作 `src/steamsage/pipeline/wishlist.py`：同步、驗證、membership 狀態轉換，讓 T021 通過
- [X] T027 [US1] 實作 `src/steamsage/pipeline/metadata.py`：依 data-model 第 3 節的 field／volatility 表寫入 `product_facts`，
  快取期限 static 30 天、volatile 7 天（從設定讀取）
- [X] T028 [US1] 實作 `src/steamsage/pipeline/daily.py` 的步驟 1–3：
  - 對 `in_wishlist` 與 `removed_tracking`（track_until 之前）的遊戲批次取得現價，寫入 `steam-current` 觀測
  - 未發行、免費、無法購買、unsupported、`delisted`、`not-found` 各自記錄在 run_item_results
  - 每個步驟在 stderr 回報「<步驟名稱> 第 n/N 款」（FR-026）
- [X] T029 [US1] 在 `src/steamsage/cli.py` 接上 `update --no-history`，並輸出 JSON 摘要的 `wishlist`、`current_prices`、`failures` 欄位，讓 T023 通過。
  願望清單被拒絕、改用上次成功的清單繼續時，exit code 為 2

**Checkpoint**：對真實清單執行 `uv run steamsage update --no-history` 可以完成，這就是最小可用版本。

---

## Phase 4: User Story 2 - 取得並核對歷史價格 (P1)

**Goal**：只有核對通過的商品，才寫入 ITAD 的台灣區歷史與輔助區域（美國區）的折扣歷史。

**Independent Test**：用固定的 ITAD 與 Steam fixture 執行。核對通過的商品寫入歷史；被拒絕的商品沒有任何歷史，而且有原因代碼。

### Tests (US2)

- [X] T030 [P] [US2] 擴充 `scripts/record_fixtures.py`：錄製 ITAD 的 lookup、反向 lookup（620 應包含 `app/659`、`sub/7877`）、
  TW 與 US 歷史、prices v3，以及 packagedetails 7877，存到 `tests/fixtures/itad/`。金鑰只從環境變數讀取，fixture 中不得出現金鑰
- [X] T031 [P] [US2] 在 `tests/unit/test_verify.py` 寫 research R2 的五條核對規則：
  - 只有 `["app/N"]` 時通過
  - `app/X` 的 `steam_appid == N` 時視為別名
  - `sub/X` 只包含 N，且台幣原價與售價一致
  - 查不到而且不在目前販售套件中的 sub，只記警告
  - 拒絕原因代碼限定為 `different-product`、`bundle`、`multiple-candidates`、`package-mismatch`、`price-mismatch`、`not-found`
- [X] T032 [P] [US2] 在 `tests/unit/test_history_ingest.py` 寫測試：
  - 台灣區第一筆 cut=0 的紀錄標記 `is_tracking_start=1`
  - 輔助區域的 `currency`、`regular_cents`、`price_cents` 都是 NULL，只保存 `cut_pct`
  - 時區轉成 UTC，並保留 `raw_observed_at`
  - 對應沒有核對通過時，不寫入任何歷史
  - 24 小時內沿用快取時，保留原本的 `retrieved_at`
  - ITAD 與 Steam 現價不一致時，兩者都寫入 `current_price_checks`，且 `match=0`
- [X] T033 [P] [US2] 在 `tests/integration/test_update_us2.py` 寫完整 `update --skip-reference` 的端到端測試，
  檢查摘要的 `history` 與 `aux_history` 計數；沒有 ITAD 金鑰時，歷史停用但現價照常取得；
  `removed_tracking`（track_until 之前）的遊戲，歷史仍會更新（FR-003a）

### Implementation (US2)

- [X] T034 [US2] 實作 `src/steamsage/sources/itad.py`：
  - `lookup_steam(appids)`：`POST /lookup/id/shop/61/v1`，每批不超過 200 款
  - `reverse_lookup(itad_ids)`：`POST /lookup/shop/61/id/v1`
  - `history(itad_id, country, since)`：`since` 精確到秒
  - `prices(itad_ids, country="TW")`：每批不超過 200 款
  - `info(itad_id)`
  - header 使用 `ITAD-API-Key`；限速為間隔 0.4 秒、5 分鐘 750 次
- [X] T035 [US2] 實作 `src/steamsage/pipeline/verify.py`，讓 T031 通過，並把每次核對結果新增一列到 `source_mappings`
- [X] T036 [US2] 實作 `src/steamsage/pipeline/history.py`：取得 TW 與 aux_region 的歷史，`since` 固定為
  `2010-01-01T00:00:00Z`，依 `cache.history_hours` 沿用快取，讓 T032 通過
- [X] T037 [US2] 在 `src/steamsage/pipeline/daily.py` 加入步驟 4：對應、核對、兩區歷史，以及 ITAD 與 Steam 的現價交叉核對（FR-009），讓 T033 通過。
  範圍是 `in_wishlist` 加上 `removed_tracking`（track_until 之前）的遊戲（FR-003a）；每個步驟在 stderr 回報「<步驟名稱> 第 n/N 款」

**Checkpoint**：`update --skip-reference` 對真實清單可以完成；`coverage --app 620` 顯示台灣區從 2024-12-11 開始。

---

## Phase 5: User Story 3 - 以任意過去時點查詢 (P1)

**Goal**：時點查詢完全不洩漏未來資訊，並區分固定屬性與變動屬性。

**Independent Test**：用交錯的測試資料，對 50 個隨機時點查詢，沒有任何洩漏。

- [X] T038 [P] [US3] 在 `tests/contract/test_store_facts_as_of.py` 寫測試：
  - static 欄位回傳最新值並附 `retrieved_at`
  - volatile 欄位只回傳 `retrieved_at <= as_of` 的值，否則為 None（保證 4）
  - 發售日晚於 as_of 時，`released_as_of` 為 False
  - 同一時點的多來源觀測全部回傳
- [X] T039 [P] [US3] 在 `tests/contract/test_store_no_leak.py` 寫測試：用固定種子產生 3 款遊戲、兩區、多個來源的交錯觀測與事實，
  對 50 個隨機的 as_of 驗證保證 1 與保證 4（SC-003）
- [X] T040 [US3] 在 `src/steamsage/store/query.py` 實作 `facts()`、`reference_apps()` 與 `ProductFacts` 的組裝，讓 T038、T039 通過

**Checkpoint**：P1 全部完成。feature 002 可以開始使用 `PriceStore`。

---

## Phase 6: User Story 5 - 匯入舊專案快取 (P2)

**Goal**：匯入舊專案的原始台灣區歷史、中繼資料與發行商作品清單，重複匯入不會產生重複資料。

**Independent Test**：用含各種類型、格式錯誤與 identity 不符的樣本匯入兩次，第二次新增 0 筆。

- [X] T041 [P] [US5] 從 `〈前身專案資料夾〉\state\cache` 複製每種類型 1–2 個真實檔案到 `tests/fixtures/legacy/`，
  另外手寫格式錯誤的 JSON、wrapper 缺欄位、identity 與內容不符的檔案
- [X] T042 [P] [US5] 在 `tests/unit/test_legacy_import.py` 寫測試（依 research R8 的對照表）：
  - 匯入 `itad-steam-verified-v1` 的 identity 與 history、`publisher-metadata-v1`、`steam-release-v1`、`publisher-catalog-v3`
  - 略過 `current`、`publisher-catalog-v1/v2`、`publisher-library-v1`，並記錄原因
  - 保留舊檔的 `retrieved_at`
  - 觀測的 source 為 `legacy-itad`，對應的 verification 為 `verified-legacy`
  - 第二次匯入新增 0 筆（SC-005）
  - 不寫入來源目錄（開啟時使用唯讀模式）
- [X] T043 [US5] 實作 `src/steamsage/pipeline/legacy_import.py`，並在 `src/steamsage/cli.py` 接上 `import-legacy [PATH]`，讓 T042 通過

**Checkpoint**：實際執行 `import-legacy` 兩次，結果符合 quickstart 情境 C。

---

## Phase 7: User Story 7 - Steam 特賣行事曆 (P2)

**Goal**：提供附來源的特賣行事曆，包含預估日期、觀測與特賣的對應，以及提醒。

**Independent Test**：固定的行事曆加上觀測資料：對應正確；尚未公告的季節特賣有預估；公告後保留原預估；漏收偵測會觸發。

- [X] T044 [US7] 依 `specs/001-price-data-foundation/research-sales-calendar.md` 建立 `data/steam_sales.toml`（格式見
  contracts/sales-calendar.md）：
  - 收錄 2019–2027 年的季節特賣、萬聖節特賣，以及 Valve 主辦的主題節慶
  - 每筆都有 `source`（https，不得指向 steamdb.info）與 `confidence`
  - 2019–2022 年的農曆新年特賣以 `kind = "themed"` 記錄
- [X] T045 [P] [US7] 在 `tests/unit/test_calendar.py` 寫測試：
  - contracts/sales-calendar.md 的驗證規則：start < end、季節特賣天數 1–30 天、每年每季最多一筆、`ended` 的 end 不可晚於現在、不得使用 steamdb
  - 對應：[start, end) 重疊即屬於該特賣；重疊的特賣會同時回傳；不重疊時回傳空清單
  - 預估：取最近一年同一季的開始日，移到今年同一個星期幾（前後 3 天內），天數沿用最近一年，並記錄依據。
    用 2025 年秋季特賣（09-29）驗證 2026 年的預估，不能被 2024 年的 11 月拉偏
  - 公告後，舊的預估列標記 `superseded_at` 並保留
  - 提醒 (a)：未來 12 個月內某一季既沒有公告也沒有預估
  - 提醒 (b)：某一天開始打折的**不同發行商數**超過門檻（已知季節特賣開始日中位數的 30%，至少 20 家），卻不在任何已知特賣內；單一發行商自辦的大量折扣不算
  - 特賣的顯示名稱為「2027 春特」這類格式，跨年的冬季特賣以開始的年份為準
- [X] T046 [US7] 實作 `src/steamsage/calendar.py`，讓 T045 通過
- [X] T047 [US7] 在 `src/steamsage/store/query.py` 實作 `sales()`、`sales_for()`；在 `src/steamsage/cli.py` 接上
  `calendar [--check]`；在 `src/steamsage/pipeline/daily.py` 步驟 5 把提醒加入摘要的 `alerts`

**Checkpoint**：`calendar --check` 列出 2024 年起的每一季（SC-009），2027 年秋季與冬季特賣顯示為預估。

---

## Phase 8: User Story 4 - 參考遊戲資料集 (P2)

**Goal**：建立相關樣本與分層隨機的廣泛樣本，可以中斷後續接，並在日常更新時以小批次補抓。

**Independent Test**：執行途中中斷再重跑，已經 fetched 的遊戲不會被重新取得；抽樣結果可以重現。

- [X] T048 [P] [US4] 在 `tests/fixtures/steam/` 新增商店搜尋分頁的 fixture（`search/results?publisher=…&infinite=1`，
  包含正常、重複頁、沒有前進三種情況），以及 GetAppList 分頁的 fixture
- [X] T049 [P] [US4] 在 `tests/unit/test_reference_sampling.py` 寫測試：
  - 分層鍵格式如 `y2019-2020/p300-599/indie`，年份切點 `[2015, 2018, 2020, 2022, 2024]`、價格切點 `[300, 600, 1000]`
  - 同一個 seed 的洗牌順序可以重現；設定改變時 `sample_version` 也會改變
  - 每層上限 25 款，每家發行商或開發商上限 30 款
  - 拒絕原因限定為 `free`、`unreleased`、`few-reviews`（`total_reviews` < 50）、`no-tw-price`、`not-game`、`stratum-full`、`publisher-cap`
  - 同一款遊戲屬於多個 pool 時，全部保留
- [X] T050 [P] [US4] 在 `tests/integration/test_reference_resume.py` 寫測試：在時間額度用完或中斷後重跑，已經 `fetched` 的遊戲不會再被請求；
  翻頁進度從 `catalog_progress` 續接；沒有 `STEAM_WEB_API_KEY` 時，摘要標示「廣泛樣本停用」，相關樣本照常執行
- [X] T051 [US4] 在 `src/steamsage/sources/steam_store.py` 實作 `search_catalog(kind, name, start)`：解析 `results_html` 中的 `data-ds-appid`；
  頁面重複或沒有前進時拋出錯誤
- [X] T052 [US4] 在 `src/steamsage/pipeline/reference.py` 實作相關樣本：從願望清單遊戲的發行商與開發商翻頁取得候選（同時匯入
  legacy 的 catalog-v3 候選），用固定種子取樣，每家最多 30 款，逐款取得中繼資料與兩區歷史（沿用 US2 的 verify 與 history）。
  翻完一家的作品清單後，把總數寫入 `publisher_catalog_size`（volatile fact，FR-005、FR-016a）；願望清單遊戲的發行商也要翻頁計數
- [X] T053 [US4] 在 `src/steamsage/pipeline/reference.py` 實作廣泛樣本：
  - 以 GetAppList 分頁取得全部遊戲，存進 `steam_app_list`
  - 依固定種子洗牌後，逐款取得資料並依配額決定收或不收
  - 沒有金鑰時停用並回報
- [X] T054 [US4] 在 `src/steamsage/cli.py` 接上 `reference [--limit N] [--budget S] [--pool related|broad|all]`，並在 `src/steamsage/pipeline/daily.py`
  加入步驟 6（`reference.daily_budget_seconds`，預設 120，設為 0 時停用），摘要輸出 `reference` 欄位，讓 T049、T050 通過。
  每個步驟在 stderr 回報「<步驟名稱> 第 n/N 款」

**Checkpoint**：`reference --budget 300` 中斷後再執行可以續接（quickstart 情境 E）。

---

## Phase 9: User Story 6 - 資料覆蓋與品質 (P3)

**Goal**：每款遊戲都有覆蓋摘要，並有區域折扣一致性的結果。

**Independent Test**：用含缺口、沒有歷史、未核對、正常四種情況的資料，產生的摘要能正確標示每一種。

- [X] T055 [P] [US6] 在 `tests/unit/test_coverage.py` 寫測試：
  - `history_state` 區分 `none`、`not-fetched`、`available`
  - `data_gaps`：自行保存的 `steam-current` 紀錄中斷超過 90 天；`long_unchanged`：ITAD 歷史超過 90 天沒有變動，
    並附上「ITAD 只記錄變動」的說明（FR-021）
  - `--csv` 中名稱為 `=HYPERLINK("x")` 的遊戲，輸出時會加上 `'` 前綴
  - `paid_sale_count` 以 `cut_pct > 0` 且 `price_cents > 0` 計算
  - 限免次數分開計算
  - 輸出 `mapping_state` 與 `aux_available`
- [X] T056 [P] [US6] 在 `tests/unit/test_consistency.py` 寫測試：
  - 重疊期間從台灣區第一筆**非追蹤起點**的紀錄開始
  - 逐日比較兩區當天的折扣百分比
  - 促銷相符的條件為 ±1 天內有相同折扣
  - 計算 `ALL` 的整體彙總
- [X] T057 [US6] 實作 `src/steamsage/coverage.py`，並接上 `coverage [--app] [--scope] [--csv]`，讓 T055 通過。
  `--csv` 的欄位開頭是 `=`、`+`、`-`、`@`、Tab 或 CR 的，前面加上 `'`（憲章 IX）
- [X] T058 [US6] 實作 `src/steamsage/pipeline/consistency.py`，寫入 `region_consistency`，並在 daily 步驟 5 執行，讓 T056 通過

**Checkpoint**：`coverage --scope wishlist` 可以輸出每款遊戲的摘要，而且有整體一致率（SC-010）。

---

## Phase 10: Polish & Cross-Cutting

- [X] T059 建立 `更新資料.cmd`：設定 `chcp 65001`、`cd /d "%~dp0"`，執行 `uv run steamsage update`，並回傳同樣的 exit code；
  沒有 `--no-pause` 時在結束前 pause。在含中文與空白的路徑中實際測試
- [X] T060 [P] 在 `tests/integration/test_no_key_leak.py` 寫測試：以假金鑰執行整個 update，掃描資料庫、日誌與摘要，都不得出現金鑰字串（SC-008）
- [X] T061 [P] 在 `tests/integration/test_interrupt.py` 寫測試：以子程序執行 update，途中強制結束，確認資料庫可以正常開啟、run 被標為 `interrupted`、
  已完成的遊戲資料完整（SC-007）
- [X] T062 [P] 撰寫 `README.md`：安裝方式、金鑰設定、一鍵更新、各指令、資料位置；註明資料來自 IsThereAnyDeal（ITAD 條款要求標示）
- [X] T063 依 quickstart.md 情境 A–G 實際執行（SC-006 需要累積多次執行，記錄目前規模與預估還需要幾次，不視為驗收失敗），把結果、耗時（SC-001）、區域一致率、行事曆檢查結果記錄到
  `specs/001-price-data-foundation/validation.md`，並明確列出沒有通過或無法驗證的項目

## 補做（2026-10-14）：US4 情境 4「只更新過期的資料」

T048–T054 只做了補抓與中斷續接，沒有任務負責情境 4 與 FR-017a 的「更新」。抽樣在 2026-09 底就滿了，
之後參考遊戲的歷史再也沒有更新：2026-10-14 檢查時，母體 2565 款有特賣紀錄的遊戲中，只有 70 款（願望清單 65）涵蓋 2026 秋特。
使用者 2026-10-14 依提案選 A（含舊專案匯入的遊戲）。

- [X] T064 [US4] 在 `src/steamsage/pipeline/reference.py` 加入 `refresh`（`POOLS` 的第三步，接在兩個樣本之後）：
  所有參考遊戲（`reference_apps`，含舊專案匯入）中，台灣區歷史最後確認時間（`history_known_until_all`，依模型讀的
  `history_keys` 商品）早於 `cache.history_hours` 的，從最舊的開始，兩區各以 `ingest_history`＋`fetch_clock` 抓一次；
  略過對應或版本被拒絕、沒有 ITAD 商品、從未有過歷史的遊戲；來源錯誤時停止並記入警示。CLI `--pool` 加上 `refresh`
- [X] T065 [P] [US4] 在 `tests/integration/test_reference_refresh.py` 寫測試：最舊的先更新、舊專案匯入也更新、新鮮的與被拒絕的不動、
  更新後 `known_until` 越過特賣且模型讀得到特賣那一列、`--limit` 中斷後續接、來源錯誤時停止、沒有 ITAD 時停用、樣本先於更新
- [X] T066 [US4] 真實資料：以 `reference --pool refresh` 一次追上，在同一個分析時點比對追上前後的願望清單決策與創新低機率表，
  結果寫進 `docs/model/comparisons.md`（2026-10-14：2698 款、甜蜜價全部不變、甜蜜時點提前一場 5 款）

---

## Dependencies & Execution Order

- **Setup (P1)** → **Foundational (P2)** → 各使用情境
- US1 → US2：US2 的歷史需要 US1 的 products／metadata 與 daily 流程
- US3 可以在 Foundational 完成後獨立進行，只依賴 store
- US5 依賴 Foundational 與 US2 的 verify 資料結構
- US7 可以在 Foundational 完成後獨立進行；T047 依賴 US1 的 daily
- US4 依賴 US1 與 US2 的抓取與核對流程
- US6 依賴 US2 的歷史資料；一致性計算需要輔助區域資料
- Polish 最後進行

## Parallel Opportunities

- Phase 2：T004／T006／T008／T010／T013／T015 的測試可以同時寫；T005、T007、T009、T018 可以同時實作
- US1：T020–T023 的測試與 fixture 可以同時進行
- US2：T030–T033 可以同時進行
- Foundational 完成後，US3 與 US7 的測試可以和 US1 同時開始
- Phase 10 的 T060、T061、T062 可以同時進行

```text
# Phase 2 測試並行示例
Task: "tests/unit/test_timeutil.py"
Task: "tests/unit/test_config.py"
Task: "tests/unit/test_lock.py"
Task: "tests/unit/test_http.py"
```

## Implementation Strategy

1. **MVP**：Setup、Foundational、US1。先確認真實清單與現價可以每天累積，從第一天開始收集自己的價格紀錄。
2. 接著做 US2 與 US3，P1 就全部完成，feature 002 需要的資料條件也都具備。
3. 然後依序做 US5（舊資料）、US7（行事曆）、US4（參考資料集）、US6（覆蓋摘要）。
4. 每個 Checkpoint 都跑一次 `uv run pytest -q`，並依任務分組 commit。
