# Research: 特賣日期自動更新

**Feature**: 012-sale-calendar-sync | **Date**: 2026-09-27 | **Spec**: [spec.md](spec.md)

## R0. plan 階段的原型（`prototype/`，輸出在 `out/`，不進版控）

全部唯讀：真實資料只讀主資料夾的 `data/steamsage.db`，不寫入正式紀錄；官方網站共 3 個請求（specify 1、P4 2），Wayback 43 個請求（每 3 秒 1 個）。

### R0.1 解析今天的頁面與 8 種變形（`p1_parse.py`）

| 頁面 | 結果 |
|---|---|
| 2026-09-27 的官方頁面 | 「Dates」一節 4 場，**4/4 和 toml 一致**；新增 0、不一致 0、頁面沒列 0 |
| V1 多一場 2027 秋特 | 新增 1（2027-09-30..10-07） |
| V2 冬特開始日 +1 天 | 不一致 1（兩邊的日期都列出） |
| V3 季節改名 "Holiday Sale" | 那一行不採用（未知的季節）＋冬特「頁面沒列」 |
| V4 日期格式改變 | 那一行不採用（日期格式）＋秋特「頁面沒列」 |
| V5 沒有「Dates」一節、V6 空白頁 | 找不到日期區；0 場，不改任何東西 |
| V7 春特提前消失 | 「頁面沒列」1 |
| V8 en dash、沒有逗號 | 4/4 一致 |

### R0.2 過去 2.5 年的頁面（`p2_wayback.py`）

Wayback 上這個網址有 **42 份內容不同的快照**（2024-03-20 到 2026-08-26）。只用於研究格式與公告時間；正式功能不讀 archive.org。

| 檢查 | 結果 |
|---|---|
| 找到「Dates」一節 | **42/42** |
| 解析出的日期行 | **104 行**，全部和 toml 一致（toml 的日期來自其他官方公告，所以這是獨立的交叉檢查；也證實「第二個日期＝恢復原價那天」） |
| 不採用的行 | **0**（第一版只認一種寫法時是 3＋70 行，見下） |
| `TBD`（列出但還沒有日期） | 56 行，例如 `Spring Sale 2025 \| TBD` |
| 同一場的日期在快照之間改變 | **0** 次 |
| 頁面上的日期寫法 | 3 種：`1 October, 2026 - 8 October, 2026`（2026）、`June 27, 2024 - July 11, 2024`（2024–2025）、`March 14 - March 21, 2024`（2024-03，年份只寫一次；跨年時是 `December 19 - January 2, 2025`） |
| 第一次出現在快照到開始的天數 | 55–337 天（快照稀疏，所以是上限）；13 場中 12 場在開始前 ≥ 2 個月出現 |

**教訓**：第一版解析器只認 2026 的寫法，放到過去的快照上有 73 行被當成錯誤；Wayback 回傳 gzip 壓縮、我的下載沒解壓，差點誤判成「頁面改版」。
正式的解析器要支援 3 種寫法與 `TBD`，測試用這 42 份快照中具代表性的幾份（精簡成只含「Dates」一節）。

### R0.3 官方日期的價值與採用的影響（`p3_adopt.py`，真實資料，68 款）

**(a) 推估和官方日期差多少**：2019–2027 的 30 場季節特賣，用「去年同季、對齊星期幾」推估，**完全準確 14/30**；
其餘多半差 1–8 天，2025 秋特差 **59 天**（從 11 月底移到 9 月底）。這就是自動取得官方日期的價值。

**(b) 把 12 個月內的一場從 toml 拿掉（變成推估），再讓官方頁面「公告」它**：

| 場次 | 甜蜜時點在這一場的遊戲 | A：官方＝檔案的日期 | B：官方晚一週 |
|---|---|---|---|
| 2026 冬特 | 24 | 24 款的標示 預估 → 官方；分組、甜蜜價不變 | 24 款的標示與日期改變；分組、甜蜜價不變 |
| 2027 春特 | 6 | 6 款 預估 → 官方 | 6 款的標示與日期改變 |
| 2027 夏特 | 2 | 2 款 預估 → 官方 | 2 款的標示與日期改變 |

- 推估在這 3 場剛好和官方相同（去年同季對齊星期幾），所以 A 只改標示。
- **既有的逐款比較不會把這些標為變動**：`decision/changes.py` 只比分組、甜蜜時點的名稱（"2026 冬特"）與甜蜜價，三者都沒變。
  所以 FR-015 的批次說明是唯一會留下紀錄的地方（R6）。
- 2027 秋特（在 12 個月之外）沒有任何遊戲的甜蜜時點落在那裡；採用它不影響決策。
- 一次決策 5.4–5.6 秒（和 `report` 相同）。

**(c) 洩漏**：同一份資料上，採用前後，2019-01 到 2026-08 每 30 天一個時點（94 個）的 `PriceStore.sales(as_of)` **0/94 不同**。

### R0.4 實際抓取（`p4_fetch.py`，專案的 `RateLimitedClient`）

| 項目 | 結果 |
|---|---|
| 請求 | HTTP 200、120,094 bytes、**0.64 秒**；解析 12 ms；4/4 一致 |
| 標頭 | `text/html; charset=UTF-8`；`Cache-Control: no-store, no-cache`；沒有 ETag；`Last-Modified` 是當下時間（動態產生）→ 條件式請求沒有用 |
| 時刻 | 2026 秋特自己的頁面（`/doc/marketing/upcoming_events/2026_autumn_sale`）寫「runs October 1 - 8, 2026 at **10am Pacific**」，和 toml 的預設時間相同（FR-004） |

## R1. 來源與解析器

**Decision**：新增 `sources/steam_partner.py`：

- `SeasonalSalesSource` Protocol（`sources/__init__.py`）：`seasonal_sales_page() -> SeasonalSalesPage`（網址、取得時間、原始文字的 SHA-256、解析結果）。
- `SteamPartnerDocs`：一個獨立的 `RateLimitedClient("steam-partner", min_interval=2.0, max_retries=0, max_retry_wait=0)`：
  - 401/403 → 既有的 `SourceDisabled`（停止、不重試）；429 有 Retry-After → 既有的 `RateLimited`（訊息含秒數，本次放棄、不等待）；
    其他錯誤（逾時、5xx、3xx、404）→ `SourceError`，本次放棄。**不重試**：一天一次，明天會再試。
  - `max_bytes` 2 MB（頁面約 120 KB）；不是 `text/html` 當作失敗。
- `parse_seasonal_sales(text) -> ParsedPage`：純函式，放在同一個模組（解析規則屬於這個來源）。
  - 只讀「Dates」一節：去掉標籤後找內容恰好是 `Dates` 的那一行，讀到第一個不是 `<季節> Sale <年> | ...` 的行為止。
  - 每一行 → 採用（季節、年份、開始日、結束日）／待定（`TBD`、`TBA`、`Coming soon`）／不採用＋原因
    （未知季節、日期格式、長度不在 1–30 天、標題年份 ≠ 開始年份、同一季同一年日期不同）。
  - 3 種日期寫法（R0.2）。
  - 不採用的行只會讓那一行不被使用；找不到「Dates」一節或 0 場時，整頁是「解析不到」。

**Rationale**：憲章 VIII 要求來源可抽換；解析結果用值型別交給核心，核心不知道 HTML。分開的 client 讓 403 只停用這個來源，不影響 Steam 商店的 client。

**Alternatives considered**：
- 用 Steam 新聞或 steamcommunity 的 Steamworks 群組公告（toml 現有的 `source` 多半是這些）：格式是自由文字，每次公告的寫法不同，還包含主題特賣；季節特賣頁面是固定格式。
- 每一場自己的頁面（`upcoming_events/<年>_<季節>_sale`）：有時刻，但網址要猜，而且只有即將到來的那一場有頁面。只在 R0.4 驗證時刻用過一次。
- HTML 解析套件：不需要；頁面結構簡單，去標籤後逐行解析已經在 42 份快照上 0 錯誤（不新增相依）。

## R2. 儲存（schema v6）

**Decision**：兩張只新增的表（觸發器禁止 UPDATE／DELETE，和價格表相同），schema 升到 **v6**（見 [data-model.md](data-model.md)）：

- `calendar_fetches`：每次讀取一列（時間、網址、結果、原因、HTTP 狀態、大小、SHA-256、採用／待定／不採用的行數、不採用的行與原因）。
- `sale_sightings`：每次成功讀取中每一場一列（讀取編號、季節、年份、開始、結束）。
  「第一次／最後一次看到」由 `MIN/MAX(fetched_at)` 算出，不另外存；日期改變自然成為不同的列（FR-010「只新增」）。

每天約 4 列，一年約 1,500 列。

**Rationale**：完全只新增，最簡單也最能追溯（憲章 II）；「第一次看到的時間」保留給以後的分析。
升版沿用既有的升級流程：升級前自動備份一次（`steamsage.db.bak-v5`，約 160 MB），只建新表，不動既有資料。
`PriceStore.open` 拒絕舊版資料庫，所以合併後第一次要先跑 `update`（背景更新本來就先跑 `update`）。

**Alternatives considered**：
- 一張表存「每一場目前的狀態」並更新 `last_seen_at`：要 UPDATE，違反只新增的慣例；歷史會遺失。
- 不升版、讓讀取端容忍表不存在：每個讀取點都要處理「沒有這張表」，而且版本號就不再代表資料庫的內容。

## R3. 行事曆怎麼合併

**Decision**：`calendar.py` 新增純函式：

- `compare_official(file_events, official, *, now) -> CalendarDiff`：每一場分成 一致／新增／不一致；另外列出「檔案有、頁面沒列」
  （檔案中的季節特賣，還沒結束，而且開始不晚於頁面列出的最後一場；R0.1 V4 修正過的規則）。
- `effective_events(file_events, adopted) -> list[SaleEvent]`：檔案的場次＋**檔案沒有的**官方場次（`status` 依當下時間、
  `source` 為官方頁面網址、`confidence="official"`）。檔案已有的季節與年份一律用檔案（改期時沿用檔案，clarify Q2）。
- 採用的官方場次＝每一個（季節, 年份）**最近一次看到**的日期（來自最近一次列出它的成功讀取）。所以：
  - 結束後從頁面消失的場次仍然保留（它確實發生過）；
  - 還沒寫回檔案的場次若被 Valve 改期，直接用新日期（沒有檔案可以沿用）並提醒；
  - 提前從頁面消失的場次保留並提醒（FR-008，不當作取消）。

使用 `effective_events` 的地方（唯一的合併點）：`PriceStore._events()`（預測、決策、`calendar_events()`）、
每日更新的行事曆步驟（推估的取代與提醒）、`steamsage calendar`。推估的取代沿用 `refresh_estimates`：傳入合併後的場次，公告的季節就被標記為取代。

**Rationale**：只有一個合併點，預測、報告與回測評分看到的行事曆一定相同；檔案優先讓人工整理的內容永遠有最終決定權。

**Alternatives considered**：讀取時才抓網頁：違反「抓取失敗不影響其他部分」與回測可重現。

## R4. 每日更新與失敗處理

**Decision**：行事曆步驟（`pipeline/daily.py` 的 `update_calendar`，第 5 步）改成：

1. 讀檔案（失敗 → 維持現在的「特賣行事曆無法使用」，也不抓網頁；FR-009）。
2. 若有官方頁面來源：讀取 → 解析 → 寫一列 `calendar_fetches`（和成功時的 `sale_sightings`，同一個交易）。
   任何例外都只變成一行提醒與失敗的讀取紀錄（憲章 I、III）；**不抓取時的行為和現在完全相同**。
3. 從資料庫算採用的場次 → `effective_events` → `refresh_estimates`、`coverage_alerts`、`detect_missed_sales`（都改用合併後的場次）。
4. 比對結果寫進摘要（`calendar.official_page`）與提醒（文字見 [contracts/calendar-sync.md](contracts/calendar-sync.md)）。

- `DailySources` 新增選用欄位 `sales_page: SeasonalSalesSource | None`；`commands.update` 建立 `SteamPartnerDocs`，測試用 `TRANSPORT` 替換（不連網）。
- `--no-history` 也照常抓（和 ITAD 無關）。
- 連續 7 天以上沒有成功讀取 → 提醒（FR-014），依 `calendar_fetches` 算。
- 時間：P4 實測 0.64 秒＋解析 12 ms＋寫入；上限由 SC-006 的 3 秒保證（逾時設 30 秒只在網站異常時發生，當天記為失敗）。

## R5. 寫回 `data/steam_sales.toml`（`steamsage calendar --sync`）

**Decision**：

- `steamsage calendar --sync`：只列出差異（新增、不一致），不改檔。`steamsage calendar --sync --write`：寫入。不用互動式確認，
  這樣在 PowerShell、Git Bash 與測試中都一樣（「確認」＝使用者看過差異後加 `--write` 再執行一次）。
- 比對的是**資料庫中最近一次成功讀取**的結果，不連網；要先取得最新的官方頁面，執行 `update` 或 `steamsage calendar --fetch`（1 個請求）。
- 以**文字**編輯，不重新序列化整個檔案，所以其他內容與註解逐位元組不變（FR-017、SC-007）：
  - 新增：在第一個開始時間比它晚的 `[[sale]]` 區塊之前插入（檔案維持時間順序；沒有就附加在最後）。欄位和人工整理的相同：
    `name`（同季最近一筆的 `name`）、`name_zh`、`kind = "seasonal"`、`season`、`year`、`start`、`end`（只寫日期，沿用預設 10:00）、
    `status`、`source`（官方頁面網址）、`confidence = "official"`、`note`（「Listed on the official seasonal sales page; first seen <日期>
    (steamsage calendar --sync <日期>).」）。
  - 不一致：只改那個區塊的 `start`、`end`（和 `source` 改成官方頁面），在 `note` 後面加「Rescheduled per the official seasonal sales page
    (seen <日期>); previously <舊日期> from <舊 source>.」。
- 寫入流程：產生新文字 → 用 `load_calendar` 驗證 → 暫存檔再改名；驗證失敗保留原檔並回報。沒有差異時不寫檔。
- 寫入後，下一次比對為一致，「尚未寫入」的提醒消失。使用者自己 commit（toml 進版控）。

**Alternatives considered**：`tomllib` 讀＋重新產生整個檔案：會丟掉註解與人工的排版；專案沒有保留格式的 TOML 寫入套件，也不需要新增。

## R6. 正式紀錄比較的說明行（FR-015）

**Decision**：`decision/changes.py` 的 `compare` 另外算 `calendar_changes`：對新舊兩份紀錄中都有的甜蜜時點名稱（例如 "2026 冬特"），
狀態從 `estimated` 變 `announced`，或官方的開始／結束改變時，產生一行，例如
「2026 冬特 預估 → 官方（太平洋時間 12/17–1/4）」或「2027 春特 官方日期 3/18–3/25 → 3/25–4/1（太平洋時間）」（和官方頁面、行事曆檔與提醒相同的日期；報告的甜蜜時點本來只顯示名稱與「官方／預估」，沒有既有的日期格式）。
報告在比較摘要顯示「特賣日期更新：…（部分變動可能來自這個改變）」，和「版本或偏好改變」同一種呈現。

- 決策輸出 `comparison` 多一個選用欄位 `calendar_changes`（字串陣列）；舊紀錄沒有這個欄位，讀取時當作空陣列。擴充功能的資料檔不變。
- 只看得到「某款遊戲的甜蜜時點」的場次；沒有任何遊戲落在那一場時，日期更新本來就不影響任何決策。

**Rationale**：R0.3 證實逐款比較看不到這種改變；不需要在紀錄中另存行事曆。

## R7. 回測與洩漏（憲章 IV）

**Decision**：

- `PriceStore.sales(as_of)` 的過濾不變：過去時點只看到開始 ≤ as_of 的場次，採用的官方場次也經過同一個過濾（R0.3 (c)：0/94）。
- `calendar_fetches`、`sale_sightings` 只由行事曆模組與 `calendar` 指令讀取；靜態測試確認 `forecast/`、`decision/` 不引用這兩張表。
- 洩漏測試：資料庫有一場未來的官方場次時，過去時點查不到；**反向測試**：把過濾拿掉（把採用的場次直接交給過去時點）時，測試會失敗。
- 回測資料集的 `calendar_hash` 由 `calendar_events()` 算，所以採用一場新的官方場次會改變資料集識別碼，**和現在手動改 toml 一樣**；
  已結束的場次不受影響，所以同一截止時間的回測數字不變。驗證時在同一份資料上跑本分支與 master（`--cutoff 2026-09-25`）。
- 「第一次看到的時間」不進入回測。

## R8. 需要使用者處理的情況要不要顯示在報告上（plan 決定 D1）

每日更新的提醒只出現在 `update` 的輸出與背景記錄檔 `data/logs/background-update.log`；使用者平常只看報告與擴充功能。
「改期」（預測沿用檔案的日期，要使用者執行 `--sync --write` 才改）與「官方頁面 7 天以上沒有成功讀取」需要使用者處理；
「新增並已採用、尚未寫回」不影響預測（只是整理檔案）。見 plan 的 D1。
