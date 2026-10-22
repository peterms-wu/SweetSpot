---

description: "Task list for feature 012: sale calendar auto-update from the official seasonal sales page"
---

# Tasks: 特賣日期自動更新

**Input**：`specs/012-sale-calendar-sync/` 的 plan.md、spec.md、research.md、data-model.md、contracts/calendar-sync.md、quickstart.md

**Tests**：憲章要求核心邏輯測試先行。每個實作任務前都有對應的測試任務：先寫測試並確認它會失敗（`uv run pytest -o addopts="" -q <檔案>`），再實作。
測試**不連網**：官方頁面用 `tests/fixtures/partner/` 的副本與 `httpx.MockTransport`（`commands.TRANSPORT`）。

**Organization**：執行順序：Setup → Foundational（來源、解析、schema v6、比對與合併）→ US1（新增的官方場次）→ US2（失敗處理）→ US5（回測不洩漏）
→ **MVP：資料庫副本上的真實 update＋report，給使用者看** → US3（改期與報告的提醒）→ US4（寫回 toml）→ Polish。

| 情境 | 內容 | 優先 |
|---|---|---|
| US1 | Valve 公告新的一場，報告自動改用官方日期 | P1 |
| US2 | 抓不到或看不懂官方頁面時，照舊運作並明確提醒 | P1 |
| US5 | 回測不會看到當時還沒公告的日期 | P1 |
| US3 | 官方日期和檔案不一致時提醒（含報告與擴充功能的提醒，D1） | P2 |
| US4 | 把自動取得的日期寫回 `data/steam_sales.toml` | P2 |

## Format: `[ID] [P?] [Story] Description`

- **[P]**：可以並行（不同檔案，也不依賴未完成的任務）
- **[Story]**：所屬的使用情境
- 路徑都相對於 repo 根目錄（worktree `〈專案資料夾〉-012`）

## 共用約定（每個任務都適用）

- **官方網址**：`OFFICIAL_URL = "https://partner.steamgames.com/doc/marketing/discounts/seasonalsales"`（`sources/steam_partner.py`），只讀這一個。
- **client**：`RateLimitedClient("steam-partner", min_interval=2.0, max_retries=0, max_retry_wait=0, max_bytes=2 * 1024 * 1024)`，
  由 `commands._client` 建立（沿用 `TRANSPORT`、`SLEEP`）。401/403 → `SourceDisabled`；429 有 Retry-After → `RateLimited`（訊息含秒數）；
  其他非 200、`content-type` 不是 `text/html` → `SourceError`。不重試、不等待。
- **時刻**：頁面只有日期；`start`/`end` 用行事曆檔的 `default_time`／`default_tz`（目前太平洋時間 10:00；research R0.4 已證實）轉成 UTC。
- **冬特的年份**＝標題的年份＝開始年份（和檔案的慣例相同）。
- **檔案優先**（clarify Q2）：檔案有的（季節, 年份）一律用檔案的日期；資料庫的官方場次只補檔案沒有的。
- **只新增**：`calendar_fetches`、`sale_sightings` 有 `BEFORE UPDATE`／`BEFORE DELETE` 觸發器；測試不能 UPDATE／DELETE 觀測。
- **失敗不擴散**（憲章 I、III）：官方頁面步驟的任何例外只變成一列 `calendar_fetches`（`failed`／`denied`／`rate_limited`）＋一行提醒；不移除、不改動任何場次。
- **文字**：提醒的文字照 contracts/calendar-sync.md §3（逐字）；行事曆相關的文字（提醒、報告橫幅、比較說明）的日期一律寫太平洋時間的 `M/D`（和官方頁面、行事曆檔相同）。
- **不動模型與規則**：`forecast/`、`decision/rule.py` 不改；`forecast/`、`decision/` 不得引用 `calendar_fetches`、`sale_sightings`（T027 的靜態測試）。
- **真實資料**只用**複製**到 `specs/012-sale-calendar-sync/prototype/out/` 的資料庫（會升到 v6）；不碰主資料夾的 `data/`（每日背景更新在那裡跑 master）。
- 在 Bash 印中文前設 `PYTHONIOENCODING=utf-8`；一次性腳本用 `uv run python`。

---

## Phase 1: Setup

- [X] T001 建立 `tests/fixtures/partner/`：從 `specs/012-sale-calendar-sync/prototype/out/` 的頁面精簡出只含 `<div class="documentation_bbcode">…</div>` 的 HTML（前後加最小的 `<html><body>`）：
  `seasonalsales-2026-09-27.html`（4 場，日在前）、`seasonalsales-2025-05-17.html`（Wayback `20250517002119`，月在前＋`TBD`）、
  `seasonalsales-2024-03-20.html`（`20240320171123`，年份只寫一次，含跨年的冬特）；每個檔案開頭用 HTML 註解寫來源網址與取得日期。
  另加 `tests/fixtures/partner/README.md` 說明來源與用途（只供測試）。
- [X] T002 [P] 在 `tests/conftest.py` 加 helper `partner_page(name, *, edit=None) -> str`（讀 fixture，`edit` 是 `(old, new)` 字串替換，用來產生新增、改期、改名等變形）
  與 `write_calendar(data_dir, text)`（把測試用的行事曆檔寫到 `data_dir/steam_sales.toml`）。

## Phase 2: Foundational（所有情境都需要）

**解析與來源**

- [X] T003 [P] 測試 `tests/unit/test_steam_partner.py`（先寫、確認失敗）：`parse_seasonal_sales(text)`
  - 2026-09-27 副本 → 4 場 `OfficialSale(season, year, start_date, end_date)`：autumn 2026 10-01..10-08、winter 2026 12-17..2027-01-04、spring 2027 03-18..03-25、summer 2027 06-24..07-08；`pending == []`、`rejected == []`、`found_dates_section is True`。
  - 2025-05-17 副本 → 3 場＋`pending == ["Spring Sale 2026 | TBD"]`；2024-03-20 副本 → 4 場（含 `December 19 - January 2, 2025` → 2024-12-19..2025-01-02）。
  - en dash、沒有逗號（`1 October 2026 – 8 October 2026`）→ 採用。
  - 不採用＋原因：未知季節（`Holiday Sale 2026 | …` → `unknown season`）、日期格式（`October 1 - October 8, 2026` 以外無法辨識的字串）、長度 0 天或 > 30 天、標題年份 ≠ 開始年份、同一季同一年兩個不同日期（兩行都不採用）；同一季同一年兩行日期相同 → 採用一場。
  - 沒有「Dates」一節、空字串 → `found_dates_section is False`、0 場。
  - 日期區只到第一個非日期行為止：「Frequently Asked Questions」之後出現的 `Summer Sale 2030 | …` 不讀。
  - 頁面中的 HTML 實體（`&amp;`）與多餘空白不影響結果。
- [X] T004 在 `src/steamsage/sources/__init__.py` 加值型別 `OfficialSale`、`RejectedLine(line, reason)`、`SeasonalSalesPage(url, fetched_at, http_status, bytes, sha256, found_dates_section, sales, pending, rejected)`
  與 `SeasonalSalesSource` Protocol（`seasonal_sales_page() -> SeasonalSalesPage`，`@runtime_checkable`，和既有的 Protocol 相同寫法）；在 `tests/unit/test_source_protocols.py` 加 `SteamPartnerDocs` 符合 Protocol 的檢查。
- [X] T005 實作 `src/steamsage/sources/steam_partner.py`：`parse_seasonal_sales`（research R1 的規則：去掉 `script`/`style`，區塊標籤換行，`html.unescape`，
  找內容恰好是 `Dates` 的行；3 種日期寫法；`TBD`/`TBA`/`Coming soon` 為待定；長度用 `calendar.MAX_SEASONAL_DAYS`）與 `SteamPartnerDocs(http)`；
  `seasonal_sales_page()` 取 `OFFICIAL_URL`，非 200 或不是 `text/html` 丟 `SourceError`，SHA-256 用回應的 bytes。讓 T003 通過。
- [X] T006 [P] 測試 `tests/unit/test_steam_partner.py` 的 client 部分（`httpx.MockTransport`）：200 → 頁面；403 → `SourceDisabled` 且 client `disabled`；
  429 `Retry-After: 3600` → `RateLimited`，訊息含 `3600`，**只送出 1 個請求、沒有 sleep**；500、404、301 → `SourceError`、1 個請求；`content-type: application/json` → `SourceError`；
  逾時（transport 丟 `httpx.ReadTimeout`）→ `SourceError`、1 個請求；回應超過 2 MB → `ResponseTooLarge`（`SourceError` 的子類別）。然後讓它通過（T005 的 client 設定）。

**Schema v6**

- [X] T007 [P] 測試 `tests/unit/test_schema_migration.py`（先寫）：新資料庫是 v6，有 `calendar_fetches`、`sale_sightings`；v5 資料庫升級：建立 `steamsage.db.bak-v5`、
  既有資料不變、兩張表是空的；兩張表 UPDATE／DELETE 丟 `sqlite3.IntegrityError`（或既有觸發器用的錯誤）；`sale_sightings` 的 (`fetch_id`, `season`, `year`) 重複時失敗；`PriceStore.open` 拒絕 v5。
- [X] T008 實作 `src/steamsage/store/schema.py`：`SCHEMA_VERSION = 6`；DDL 加兩張表（欄位照 data-model §1：`calendar_fetches(fetch_id INTEGER PRIMARY KEY AUTOINCREMENT, fetched_at TEXT NOT NULL, url TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('ok','no_dates','failed','denied','rate_limited')), reason TEXT, http_status INTEGER, bytes INTEGER, page_sha256 TEXT,
  accepted INTEGER NOT NULL DEFAULT 0, pending INTEGER NOT NULL DEFAULT 0, rejected_json TEXT NOT NULL DEFAULT '[]', run_id TEXT)`；
  `sale_sightings(fetch_id INTEGER NOT NULL REFERENCES calendar_fetches(fetch_id), season TEXT NOT NULL CHECK (season IN ('spring','summer','autumn','winter')), year INTEGER NOT NULL,
  starts_at TEXT NOT NULL, ends_at TEXT NOT NULL, PRIMARY KEY (fetch_id, season, year))`）；兩張表加進只新增觸發器的清單；`_migrate_to_v6`（一個交易，只更新版本號，表由 DDL 建立）。讓 T007 通過。

**比對與合併（純函式）**

- [X] T009 [P] 測試 `tests/unit/test_calendar_sync.py` 的純函式部分（先寫）：
  - `calendar.official_event(sale, *, default_time, tz, name, name_zh, now)` → `SaleEvent`（UTC、`status` 依 now、`source == OFFICIAL_URL`、`confidence == "official"`）。
  - `calendar.compare_official(file_events, official_events, *, now)`：一致、新增、不一致（開始或結束任一不同）、`missing`（檔案的季節特賣、`end > now`、`start <=` 頁面最後一場的開始、頁面沒列；research R3）；主題特賣不參與。
  - `calendar.effective_events(file_events, adopted)`：檔案的全部＋檔案沒有的（季節, 年份）；檔案有的一律用檔案（改期時檔案的日期勝出）；結果依 `start` 排序；不重複。
  - 名稱：取檔案中同季最近一筆的 `name`／`name_zh`；檔案沒有這一季時用 `f"Steam {Season} Sale"`／`calendar.SEASON_ZH`。
- [X] T010 實作 `src/steamsage/calendar.py` 的 `official_event`、`compare_official`（回傳 `CalendarDiff`：`same`、`new`、`conflicts`、`missing`）、`effective_events`。讓 T009 通過。

**讀取紀錄與採用的場次（資料庫）**

- [X] T011 [P] 測試 `tests/unit/test_calendar_sync.py` 的資料庫部分（先寫，用 `StoreWriter` 的暫存資料庫）：
  - `calendar_sync.record_fetch(writer, page_or_error, *, now, run_id)`：成功 → 一列 `ok`＋每場一列 `sale_sightings`；0 場 → `no_dates`、沒有 sightings；
    `SourceDisabled` → `denied`；`RateLimited` → `rate_limited`；其他 `SourceError` → `failed`；`reason` 寫例外訊息；`rejected_json` 最多 20 行、每行 200 字；同一個交易。
  - `calendar_sync.adopted_sales(conn, *, default_time, tz, file_events, now)`：每個（季節, 年份）取**最近一次**出現的 sighting；日期改變後用新的；從頁面消失後仍保留；只看 `ok` 的讀取。
  - `calendar_sync.sighting_times(conn, season, year)` → 第一次／最後一次看到（依日期分組）。
  - `calendar_sync.last_success(conn)`、`calendar_sync.latest_fetch(conn)`、`calendar_sync.listed_now(conn)`（最近一次 `ok` 的場次）。
- [X] T012 實作 `src/steamsage/calendar_sync.py`（新模組）：`record_fetch`、`adopted_sales`、`sighting_times`、`last_success`、`latest_fetch`、`listed_now`、`load_effective(conn, path, *, now)`
  （讀檔案 → `adopted_sales` → `effective_events`；檔案讀取失敗時丟 `CalendarError`，不單獨用資料庫的場次，FR-009）。讓 T011 通過。

**Checkpoint**：`uv run pytest -o addopts="" -q` 全部通過（1217＋新測試）→ commit「Feature 012: official seasonal sales page parser and source, schema v6, calendar merge」。

---

## Phase 3: User Story 1 — 新增的官方場次自動採用（P1）🎯

**Goal**：官方頁面列出檔案沒有的場次 → 預測、決策、報告用官方日期；推估被取代；提醒「尚未寫入」；正式紀錄的比較多一行說明。

**Independent Test**：頁面副本多一場 → `update` 的行事曆步驟 → 行事曆有它（官方）、推估被取代、`report` 的甜蜜時點標示官方；`data/steam_sales.toml` 不變。

- [X] T013 [P] [US1] 測試 `tests/integration/test_daily_calendar.py`（先寫）：暫存設定＋`write_calendar`＋ MockTransport 回傳「2026-09-27 副本」（SC-002 用「檔案缺 2027 春特」，因為 2027 秋特在 12 個月之外）：
  - 檔案有頁面上的 4 場 → `history.calendar.official_page` 的 `status == "ok"`、`same == 4`、`new == 0`，**沒有任何官方頁面的提醒**；`steam-partner` 1 個請求。
  - 檔案缺 2027 春特 → `new == 1`、`not_in_file == 1`；`sale_estimates` 中 2027 春特的推估 `superseded_at` 有值；提醒逐字等於 contracts §3「新增並已採用」那一行；再跑一次 `update` 仍然只有一行（不堆疊）。
  - 頁面列出一場**已結束**、檔案沒有的場次（`now` 設在 2026 秋特結束後、檔案刪掉 2026 秋特）→ 仍然新增，`status == "ended"`。
  - 行事曆檔的位元組不變（SC-002）。
- [X] T014 [US1] 實作 `src/steamsage/pipeline/daily.py`：`DailySources.sales_page: SeasonalSalesSource | None = None`；`update_calendar(writer, config, *, now, report, sales_page=None, run_id=None)`：
  讀檔案（失敗 → 現在的行為＋`official_page.status == "skipped"`，不抓）→ 抓取並 `record_fetch`（例外只變成紀錄與提醒）→ `load_effective` → `refresh_estimates`／`coverage_alerts`／`detect_missed_sales` 改用合併後的場次 →
  `calendar_sync.official_alerts(...)`（contracts §3 的文字）→ 摘要 `official_page`（contracts §2 的欄位，含 `seconds`）。`run_daily` 傳入 `sources.sales_page` 與 `run_id`。
- [X] T015 [US1] 在 `src/steamsage/commands.py` 的 `update` 建立 `SteamPartnerDocs(_client("steam-partner", 2.0, ctx, max_retries=0, max_retry_wait=0, max_bytes=2 * 1024 * 1024))`，放進 `DailySources`，
  並加進 `http_usage`。讓 T013 通過。
- [X] T016 [P] [US1] 測試 `tests/contract/test_store_sales.py`（先寫）：`PriceStore` 的 `sales(now)`、`calendar_events()` 包含資料庫採用的場次（`status == "announced"`、`source == OFFICIAL_URL`）；
  檔案有同一季同一年時用檔案的日期；`sales(now)` 不再回傳那一季的推估。
- [X] T017 [US1] 實作 `src/steamsage/store/query.py`：`PriceStore._events()` 改用 `calendar_sync.load_effective(self.conn, self.calendar_path, now=now_utc())`。讓 T016 通過。
- [X] T018 [P] [US1] 測試 `tests/unit/decision/test_changes.py`（先寫）：`compare` 的 `comparison["calendar_changes"]`：
  基準中某款的甜蜜時點 `{"label": "2026 冬特", "status": "estimated", …}`、新的是 `announced` → `["2026 冬特 預估 → 官方（太平洋時間 12/17–1/4）"]`（太平洋時間的 `start` 日期與 `end` 日期，和官方頁面相同）；
  官方日期改變 → `"2027 春特 官方日期 3/18–3/25 → 3/25–4/1（太平洋時間）"`；同一場多款遊戲只一行；沒有基準 → `[]`；基準沒有這個欄位也能比較；逐款的 `change` 不因此改變。
- [X] T019 [US1] 實作 `src/steamsage/decision/changes.py` 的 `calendar_changes`，放進 `compare` 回傳的 `comparison`；`decision/contract.py` 的輸出帶 `comparison.calendar_changes`（選用，預設 `[]`）。讓 T018 通過。
- [X] T020 [P] [US1] 測試 `tests/unit/report/test_html.py`（先寫）：比較摘要有 `calendar_changes` 時，每一項一行「特賣日期更新：…（部分變動可能來自這個改變）」，位置緊接「版本或偏好改變」；
  沒有時 HTML **逐位元組不變**（跑既有的 14 份 golden）。
- [X] T021 [US1] 實作 `src/steamsage/report/html.py` 的 `_comparison` 多出那一行。讓 T020 與 golden 通過。

**Checkpoint**：全部測試通過 → commit「Feature 012 US1: adopt newly listed official sales (daily update, PriceStore, comparison line)」。

---

## Phase 4: User Story 2 — 失敗時照舊運作並提醒（P1）

**Goal**：逾時、403、429、空白頁、格式改變、個別行解析失敗、提前消失：其他步驟照常、行事曆不變、各有提醒。

**Independent Test**：5 種失敗各跑一次 `update`：價格等其他步驟的結果和不抓官方頁面時相同；行事曆＝只讀檔案時；各 1 行提醒（SC-003）。

- [X] T022 [P] [US2] 測試 `tests/integration/test_daily_calendar.py`（先寫）：參數化 5 種失敗（`httpx.ReadTimeout`、403、429 `Retry-After: 7200`、200 空白、200 沒有「Dates」一節）：
  - `update` 結束代碼和「官方頁面正常」時相同；`price_observations` 等其他表的列數和「`sales_page=None`」的同一次執行相同。
  - `calendar_fetches` 一列，`status` 分別為 `failed`／`denied`／`rate_limited`／`no_dates`／`no_dates`；`sale_sightings` 0 列。
  - 提醒逐字等於 contracts §3 對應的那一行（被拒絕、被限速含 `7200`、抓取失敗、解析不到）；429 時 `SLEEP` 沒有被呼叫超過既有的節流。
  - 行事曆（`PriceStore.calendar_events()`）和只讀檔案時相同；已採用的舊場次仍保留（先成功一次、再失敗）。
- [X] T023 [P] [US2] 測試（同檔）：個別行不採用（頁面把冬特改成 `Holiday Sale 2026`）→ 其他 3 場照常，提醒「有 1 行無法解析，已略過：…（未知的季節）」＋「不再列出 2026 冬特」；
  春特從頁面消失（`end > now`）→ 行事曆保留、提醒「不再列出 2027 春特（可能取消或改名）」；已結束的場次消失 → 沒有提醒。
- [X] T024 [P] [US2] 測試（同檔）：`calendar_fetches` 最後一次 `ok` 在 8 天前、之後都失敗 → 提醒「官方特賣頁面已 8 天沒有成功讀取（最後一次 <台北日期>）」；6 天前 → 沒有這一行（FR-014）。
- [X] T025 [US2] 補齊 `src/steamsage/calendar_sync.py` 的 `official_alerts` 與 `pipeline/daily.py` 的例外處理，讓 T022–T024 通過；`--no-history` 也照常抓（T022 加一個 `--no-history` 的案例）。
- [X] T026 [US2] 跑全部測試；既有的 `update` 測試若因官方頁面的請求（假網站回 404）多出提醒或請求數而失敗，**只**在該測試的假網站加 partner 的路由回傳 2026-09-27 副本（或讓它的 `data/` 沒有行事曆檔），不改斷言的意義；在 commit 訊息列出改了哪些測試。

**Checkpoint**：全部測試通過 → commit「Feature 012 US2: failures never change the calendar; alerts for failed, denied, rate-limited, unparsable, missing and stale」。

---

## Phase 5: User Story 5 — 回測不洩漏（P1）

**Goal**：過去時點看不到當時還沒開始的場次；第一次看到的時間不進入預測與回測。

**Independent Test**：洩漏測試＋反向測試；靜態測試；同一份資料上和 master 回測相同（Polish T043）。

- [X] T027 [P] [US5] 測試 `tests/contract/test_no_future_leak.py`（先寫）：資料庫有一場未來的官方場次（2027 秋特）時，`PriceStore.sales(as_of)` 對 2019-01-01 到今天每 30 天的時點都不含它，
  且和「沒有這筆 sighting」時完全相同；**反向測試**：monkeypatch `PriceStore.sales` 的過濾（把 `e.start <= as_of` 換成永遠為真）時，這個測試會失敗（用 `pytest.raises(AssertionError)` 包住同一個檢查函式）。
  靜態測試：`src/steamsage/forecast/`、`src/steamsage/decision/` 的原始碼不含字串 `calendar_fetches`、`sale_sightings`、`calendar_sync`。
- [X] T028 [US5] 若 T027 有失敗，修正 `store/query.py`（預期不需要改，過濾不變）；在 `store/query.py` 的 `sales()` docstring 補一句：資料庫採用的官方場次和檔案的場次經過同一個過濾，第一次看到的時間不使用。

**Checkpoint**：commit「Feature 012 US5: leak tests for adopted official sales」。

---

## MVP：真實資料（給使用者看）

- [X] T029 複製主資料夾的 `data/steamsage.db` 到 `specs/012-sale-calendar-sync/prototype/out/mvp/data/`（複製前先 `sqlite3` 的 `.backup` 或在沒有更新執行時複製；複製 `steamsage.toml` 並把 `data_dir` 指向那裡），
  在 worktree 跑 `uv run steamsage update --config <副本>`（真的抓 1 次官方頁面）與 `report`：記錄 `official_page`、耗時、`http_usage`、升級（v5 → v6、備份）時間；
  和 master 在同一份資料上逐款比對決策（沿用 `specs/010-wishlist-bundles/prototype/t035_same_data.py` 的做法：master 用 git worktree 執行、在刪掉新表的副本上跑），預期 68/68 相同。
  再用 `specs/012-sale-calendar-sync/prototype/` 的腳本模擬「檔案缺 2026 冬特、頁面有」：報告上 24 款的甜蜜時點標示官方。結果寫進 `specs/012-sale-calendar-sync/validation.md`（草稿），
  截圖報告上半部（`check_390.py`），用 `SendUserFile` 給使用者看，**等使用者回覆再繼續**。

---

## Phase 6: User Story 3 — 改期提醒（含報告與擴充功能的提醒，D1）（P2）

**Goal**：官方日期和檔案不同 → 預測沿用檔案、每天提醒兩邊的日期；需要使用者處理的 3 種提醒也顯示在報告與擴充功能上。

**Independent Test**：頁面副本冬特 +1 天 → 提醒兩邊日期、預測用檔案的日期；報告最上方有同一行；擴充功能彈出視窗標題下方有同一行（SC-008 的前半）。

- [X] T030 [P] [US3] 測試 `tests/integration/test_daily_calendar.py`（先寫）：頁面的冬特改成 `18 December, 2026` → `conflict == 1`；提醒逐字等於 contracts §3「不一致」那一行（`12/18–1/4` 對 `12/17–1/4`）；
  `PriceStore.calendar_events()` 的 2026 冬特仍是檔案的日期；隔天再跑仍有那一行。未寫回的已採用場次被改期 → 用新日期＋提醒「官方特賣頁面把 2027 秋特從 9/30–10/7 改成 10/7–10/14（尚未寫入檔案，已改用新日期）」。
- [X] T031 [US3] 補齊 `calendar_sync.official_alerts` 的「不一致」「未寫回的場次被改期」，讓 T030 通過。
- [X] T032 [P] [US3] 測試（先寫）：`calendar_sync.calendar_notices(conn, file_events, *, now) -> list[str]` 只回傳 3 種（不一致；解析不到或不採用的行；7 天以上沒有成功讀取），文字和 §3 相同；
  「新增並已採用」、單次的抓取失敗、頁面消失不在其中。`report`（正式）的輸出有 `calendar_notices`；`--as-of`、預覽時為 `[]`。
  報告：有 notices 時每一項一個 `<p class="banner">`，位置在「本次資料更新失敗」之後；沒有時 golden 逐位元組不變。擴充功能資料檔：`calendar_notices` 陣列（`tests/unit/report/test_extension_data.py`）。
- [X] T033 [US3] 實作：`commands.report` 在正式執行時呼叫 `calendar_sync.calendar_notices` 並傳給 `run_decisions(..., calendar_notices=...)`（`decision/` 不得引用 `calendar_sync`，T027 的靜態測試）；`decision/engine.py` 的 `DecisionBatch` 加 `calendar_notices: tuple[str, ...] = ()`、`decision/contract.py`（輸出 `calendar_notices`）、
  `report/html.py` 的 `_header`（banners）、`report/extension.py`（`calendar_notices`）。讓 T032 通過。
- [X] T034 [P] [US3] 測試 `tests/extension/lib.test.js`（先寫）：`popupModel` 有 `calendarNotices`（資料沒有這個欄位時為 `[]`，舊資料檔相容）。
- [X] T035 [US3] 實作 `extension/lib.js`（`popupModel` 帶 `calendarNotices`）與 `extension/popup.js`（標題下方、資料更新失敗說明之後，每一項一行，`textContent`）；
  跑 `node --test "tests/extension/*.test.js"` 與 `uv run --with playwright python tests/extension/e2e.py`（68/68＋新案例：測試資料有一行 notice 時彈出視窗顯示它）。

**Checkpoint**：全部測試與擴充功能測試通過 → commit「Feature 012 US3: conflicts keep the file's dates; calendar notices in the report and the extension popup」。

---

## Phase 7: User Story 4 — 寫回 `data/steam_sales.toml`（P2）

**Goal**：`calendar --sync` 列出差異，`--sync --write` 寫入；其他位元組不變；`--fetch` 立即讀取一次；`--check` 顯示比對結果。

**Independent Test**：測試用的行事曆副本：新增與改期寫入後驗證通過、其他位元組不變；沒有差異時不改檔（SC-007）；寫回後下一次比對一致（SC-008 後半）。

- [X] T036 [P] [US4] 測試 `tests/unit/test_calendar_sync.py`（先寫）：`calendar_sync.sync_plan(conn, path, *, now)` → 新增（label、start、end、first_seen）與改期（檔案、官方的日期）；
  `calendar_sync.write_sync(path, plan, *, now)`：
  - 新增：區塊插在第一個開始時間比它晚的 `[[sale]]` 之前（沒有就附加在最後），欄位與順序逐字照 contracts §5；寫入後 `load_calendar` 通過；原檔的其他位元組不變（比對插入點前後的原始 bytes）。
  - 改期：只改該區塊的 `start`、`end`、`source`，`note` 後面加 contracts §5 的句子（沒有 `note` 時新增一行）；其他位元組不變。
  - 沒有差異 → 不寫檔（修改時間不變）。
  - 驗證失敗（例如 monkeypatch `load_calendar` 丟 `CalendarError`）→ 原檔不變、回報錯誤。
  - 檔案用 CRLF 或 LF 都保持原本的換行。
- [X] T037 [US4] 實作 `calendar_sync.sync_plan`、`write_sync`（文字編輯、`commands.write_text_atomic` 或同等的暫存檔再改名）。讓 T036 通過。
- [X] T038 [P] [US4] 測試 `tests/contract/test_cli_calendar.py`（先寫）：`calendar`（摘要多 `official_page`，0 個請求）、`--check`（有新增未寫回、不一致、頁面沒列、不採用的行、最近一次失敗、7 天以上沒成功時結束代碼 `EXIT_PARTIAL`；一致時 `EXIT_OK`）、
  `--fetch`（1 個請求、寫一列 `calendar_fetches`、`run_id` 為 NULL）、`--sync`（摘要照 contracts §4，不改檔）、`--sync --write`（寫檔；再 `--sync` 顯示「已一致」）。
- [X] T039 [US4] 實作 `src/steamsage/cli.py`（`--fetch`、`--sync`、`--write`；`--write` 沒有 `--sync` 時報錯）與 `src/steamsage/commands.py` 的 `calendar_command`（改用 `load_effective`；`--fetch` 建立 `SteamPartnerDocs`）。讓 T038 通過。
- [X] T040 [US4] 整合測試 `tests/integration/test_daily_calendar.py`：SC-008 全流程：頁面冬特 +1 天 → `update`（提醒）→ `calendar --sync --write` → `update`（`conflict == 0`、沒有提醒）→ 檔案的冬特是 12/18。

**Checkpoint**：全部測試通過 → commit「Feature 012 US4: calendar --fetch/--check/--sync/--write」。

---

## Phase 8: Polish & 驗證

- [X] T041 [P] 更新 `README.md` 的「資料放在哪裡」（兩張新表、`calendar --sync`）與「資料來源與限制」（官方季節特賣頁面、每次 update 1 個請求、只有季節特賣、Next Fest 與主題特賣仍人工維護）；
  `specs/001-price-data-foundation/contracts/sales-calendar.md` 加一段「自動取得的官方場次」指向本 feature 的 contract；`data/steam_sales.toml` 開頭的說明加一行（`calendar --sync --write` 會寫入這個檔案）。
- [X] T042 [P] `uv run pytest -o addopts="" -q` 全部通過；`node --test "tests/extension/*.test.js"`；`uv run --with playwright python tests/extension/e2e.py`。
- [X] T043 在 MVP 的資料庫副本上做 quickstart §2 的 SC-001–SC-008，全部寫進 `specs/012-sale-calendar-sync/validation.md`：
  SC-004：`uv run steamsage backtest --cutoff 2026-09-25 --split tuning` 在本分支與 master（git worktree、同一份資料）結果相同；SC-005：68/68；SC-006：`update` 5 次的 `official_page.seconds` 中位數與 `http_usage`。
  逐項寫實測數字；有不符合的照實寫原因。
- [X] T044 更新 `HANDOFF.md`（012 完成、013 事後對照是下一個、合併時機：秋特結束後、合併後第一次 `update` 升 v6 並備份 `bak-v5`）與記憶 `feature012-direction`；
  commit「Feature 012: validation, README, HANDOFF」，向使用者報告並詢問是否合併（建議 10/9 01:00 之後）。

---

## Dependencies & Execution Order

- Setup（T001–T002）→ Foundational（T003–T012）→ US1（T013–T021）→ US2（T022–T026）→ US5（T027–T028）→ **MVP（T029，等使用者）**→ US3（T030–T035）→ US4（T036–T040）→ Polish（T041–T044）。
- US2、US5 依賴 US1 的 `update_calendar` 與 `PriceStore` 合併；US3 的 notices 依賴 US2 的提醒；US4 只依賴 Foundational 與 US1（可和 US3 對調）。
- 同一個檔案的任務依序執行：`tests/integration/test_daily_calendar.py`（T013、T022–T024、T030、T040）、`calendar_sync.py`（T012、T025、T031、T033 的 notices、T037）。

## Parallel Opportunities

- Foundational：T003（解析測試）、T007（schema 測試）、T009（純函式測試）可同時寫；T005、T008、T010 分別實作不同檔案。
- US1：T016（`PriceStore` 測試）、T018（changes 測試）、T020（報告測試）可和 T013 同時寫。
- US3：T034（JS 測試）可和 T032 同時寫。
- Polish：T041 可和 T042 同時做。

## Implementation Strategy

1. **MVP**＝Foundational＋US1＋US2＋US5：每日更新能自動採用官方日期、失敗不擴散、回測不洩漏。在資料庫副本上跑真實的 `update`＋`report`，給使用者看（T029）。
2. 使用者同意後做 US3（改期與報告的提醒）與 US4（寫回）。
3. 每個 checkpoint commit 並報告；秋特期間主資料夾不動，合併等使用者決定（建議秋特結束後）。
