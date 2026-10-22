# Data Model: 特賣日期自動更新

**Feature**: 012-sale-calendar-sync | **Date**: 2026-09-27

## 1. 資料庫（schema v5 → v6）

升級只建兩張新表與它們的只新增觸發器，不動既有資料；升級前自動備份一次（`steamsage.db.bak-v5`）。

### `calendar_fetches`（每次讀取官方頁面一列）

| 欄位 | 型別 | 說明 |
|---|---|---|
| `fetch_id` | INTEGER PK | 自動編號 |
| `fetched_at` | TEXT | UTC，讀取完成的時間 |
| `url` | TEXT | 讀取的網址（固定為官方季節特賣頁面） |
| `status` | TEXT | `ok`（找到日期區、≥ 1 場採用）／`no_dates`（找不到日期區或 0 場採用）／`failed`（逾時、5xx、3xx、404、不是 HTML、過大）／`denied`（401／403）／`rate_limited`（429） |
| `reason` | TEXT NULL | 失敗原因（已遮蔽金鑰；這個來源沒有金鑰） |
| `http_status` | INTEGER NULL | 有回應時的 HTTP 狀態 |
| `bytes` | INTEGER NULL | 回應大小 |
| `page_sha256` | TEXT NULL | 原始文字的 SHA-256（相同內容可辨識；不存整頁） |
| `accepted` | INTEGER | 採用的行數（失敗時 0） |
| `pending` | INTEGER | 待定（`TBD` 等）的行數 |
| `rejected_json` | TEXT | 不採用的行與原因 `[{"line": "...", "reason": "..."}]`（只含日期區的文字，最多 20 行、每行 200 字） |
| `run_id` | TEXT NULL | 所屬的每日更新（`runs.run_id`）；`calendar --fetch` 時為 NULL |

> 2026-10-22 稽核補記：`status` 的實際判定是「找到日期區，而且至少 1 場採用**或**至少 1 行待定」才是 `ok`；所以頁面只有 `TBD` 待定行（0 場採用）時記為 `ok`：不發「格式改變」提醒、算進 `last_success`（7 天沒成功的提醒從這次重新算）。理由：待定行代表頁面的格式還讀得懂，只是官方還沒公布日期。找到日期區但只有不採用的行時才是 `no_dates`。（`calendar_sync._status`；`tests/unit/test_calendar_sync.py` 的 `test_only_tbd_lines_is_still_a_successful_read`）

### `sale_sightings`（每次成功讀取中每一場一列）

| 欄位 | 型別 | 說明 |
|---|---|---|
| `fetch_id` | INTEGER | → `calendar_fetches.fetch_id` |
| `season` | TEXT | `spring`／`summer`／`autumn`／`winter` |
| `year` | INTEGER | 標題的年份（冬特＝開始年份，和檔案的慣例相同） |
| `starts_at` | TEXT | UTC；頁面的開始日＋預設時刻（太平洋時間 10:00） |
| `ends_at` | TEXT | UTC；頁面的第二個日期（恢復原價那天）＋預設時刻 |

PRIMARY KEY (`fetch_id`, `season`, `year`)。兩張表都有 `BEFORE UPDATE`／`BEFORE DELETE` 觸發器（只新增）。

**衍生值**（查詢時計算，不另存）：

- 某一場的「第一次／最後一次看到」＝ 該（季節, 年份, `starts_at`, `ends_at`）所在讀取的 `MIN/MAX(fetched_at)`；日期改變時新日期是另一組。
- 目前採用的官方場次＝每個（季節, 年份）**最近一次**出現的那一列（R3）。
- 最後一次成功讀取＝`status = 'ok'` 的最大 `fetched_at`；連續失敗天數由它算（FR-014）。
- 「頁面目前列出的場次」＝最近一次 `ok` 讀取的所有列。

## 2. 核心的值型別

### `sources.SeasonalSalesPage`（來源 → 核心）

| 欄位 | 說明 |
|---|---|
| `url`, `fetched_at`, `http_status`, `bytes`, `sha256` | 讀取資訊 |
| `found_dates_section` | 是否找到「Dates」一節 |
| `sales: list[OfficialSale]` | 採用的場次：`season`, `year`, `start_date`, `end_date`（`date`，還沒加時刻） |
| `pending: list[str]` | 待定的行 |
| `rejected: list[RejectedLine]` | `line`, `reason` |

讀取失敗時來源丟出既有的 `SourceError`／`SourceDisabled`／`RateLimited`，行事曆步驟把它轉成 `failed`／`denied`／`rate_limited` 的讀取紀錄。
（2026-10-22，014 T076）429 沒有 Retry-After（或值是 0、看不懂）時，以前丟的是一般的 `SourceError`，記成 `failed`、提醒寫「抓取失敗」；現在一律是 `RateLimited` → `rate_limited`。
其他來源用完重試仍是 429 時也是 `RateLimited`（`SourceError` 的子類別，處理方式不變）。

### `calendar.CalendarDiff`（比對結果）

| 欄位 | 說明 |
|---|---|
| `same` | 官方＝檔案的場次 |
| `new` | 檔案沒有的官方場次（已採用） |
| `conflicts` | `(檔案的 SaleEvent, 官方的日期)`：預測用檔案的日期 |
| `missing` | 檔案有、還沒結束、在頁面範圍內、頁面沒列 |
| `not_in_file` | 已採用但還沒寫回檔案的場次（包括已從頁面消失的） |
| `fetch` | 最近一次讀取的結果與最後一次成功的時間 |

### `SaleEvent`（既有，不變）

採用的官方場次用既有的型別：`status` 為 `announced`／`ended`（依當下時間）、`source` 為官方頁面網址、`confidence = "official"`、
`name`／`name_zh` 取同季最近一筆檔案場次的名稱。報告、決策與擴充功能不需要知道它來自資料庫還是檔案。

## 3. 行事曆檔 `data/steam_sales.toml`

格式（schema_version 1）與欄位不變。只有 `steamsage calendar --sync --write` 會修改（R5）；新增的區塊和人工整理的格式相同。

## 4. 決策輸出 `steamsage.decision/2`（選用欄位，向後相容）

- `comparison.calendar_changes: list[str]`：這次和比較基準之間，甜蜜時點所在的季節特賣從預估變官方或官方日期改變（R6）。
  沒有時為空陣列；舊紀錄沒有這個欄位時當作空陣列。其他欄位不變。
- D1＝A：新的選用欄位 `calendar_notices: list[str]`（只有改期、頁面格式改變、7 天以上沒有成功讀取 3 種；只在正式執行產生，沒有時為空陣列）。擴充功能資料檔 `steamsage.extension/1` 多一個同名的選用欄位（向後相容，舊的擴充功能忽略它）。既有的 `warnings` 不變。

## 5. 狀態轉換（一場季節特賣）

```text
未公告 ──(沒有官方資料)──> 推估（sale_estimates）
   │
   └─ 官方頁面列出 ─┬─ 檔案沒有 → 採用（資料庫）；推估標記取代；每天提醒「尚未寫入」
                    │                └─ calendar --sync --write → 檔案有、一致
                    ├─ 檔案有、日期相同 → 一致（沒有提醒）
                    └─ 檔案有、日期不同 → 不一致：預測用檔案；每天提醒
                                     └─ calendar --sync --write → 檔案改成官方日期、一致
結束 → 從頁面消失（正常，不提醒）；採用的場次保留
```
