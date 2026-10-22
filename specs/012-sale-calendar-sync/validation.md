# Validation: 特賣日期自動更新

**Feature**: 012-sale-calendar-sync | **Date**: 2026-09-27 | 腳本：`prototype/t029_mvp.py`、`prototype/t029_shot.py`（輸出在 `out/`，不進版控）

真實資料全部在主資料夾資料庫的**副本**上執行（sqlite backup API，主資料夾只讀）；主資料夾的每日背景更新仍在 master。

## 測試

| 套件 | 結果 |
|---|---|
| `uv run pytest -o addopts="" -q` | **1323 passed**（master 1217；新增 106） |
| `node --test "tests/extension/*.test.js"` | **32/32**（新增 1：彈出視窗的 `calendarNotices`） |
| `uv run --with playwright python tests/extension/e2e.py` | **69/69**（新增 1：彈出視窗顯示特賣日期提醒）；擴充功能發出的請求 0 |

改到的既有測試（都是欄位或版本的預期改變，不改斷言的意義）：`test_update_versions`（升級訊息 v5 → v6）、`test_schema_migration`（升級後的版本改用 `SCHEMA_VERSION`）、
`test_changes` 兩項（`comparison` 多一個空的 `calendar_changes`）、`test_extension_contract`（資料檔多一個 `calendar_notices`）。

## 成功標準

| SC | 怎麼驗證 | 結果 |
|---|---|---|
| SC-001 | `test_parses_todays_page`＋`test_matching_page_changes_nothing`（2026-09-27 的頁面副本＋真實 toml）；真實 `update` 與 5 次 `calendar --fetch` | ✅ 4/4 一致，新增 0、不一致 0、提醒 0（真實頁面同樣 4/4） |
| SC-002 | `test_new_official_sale_is_adopted`（檔案缺 2027 春特）；真實資料模擬（檔案缺 2026 冬特，下方 §3） | ✅ 採用、推估標記取代、檔案不變；真實資料 24 款 預估 → 官方 |
| SC-003 | `test_failures_keep_the_calendar`（逾時、403、429、空白頁、沒有日期區）＋`test_update_command_other_steps_are_unaffected`（真正的 client：403、逾時） | ✅ 行事曆不變、各 1 行提醒；價格、中繼資料與結束代碼和正常時相同 |
| SC-004 | 洩漏測試＋反向測試（`test_no_future_leak`）；同一份資料上 `backtest --cutoff 2026-09-25 --split tuning`（本分支 vs master） | ✅ 95 個過去時點 0 差異，反向測試抓得到；回測結果只差執行時間（`run.started_at` 等），資料集識別碼 `db8663…/19d50568`、所有數字相同 |
| SC-005 | 同一份資料上的決策（68 款）與 `--as-of` HTML 報告 | ✅ 決策 **68/68** 相同；HTML **逐位元組相同**（219,038 bytes）；擴充功能資料檔只多 `calendar_notices: []`（單元測試） |
| SC-006 | 真實 `update` 1 次＋`calendar --fetch` 5 次 | ✅ 官方頁面 0.59 秒（update 中）；`--fetch` 0.21–0.31 秒，**中位數 0.25 秒**；每次 `steam-partner` 1 個請求，沒有其他新網站 |
| SC-007 | `test_write_inserts_and_reschedules_leaving_everything_else`、`test_write_back_on_the_real_calendar_file`、`test_no_difference_leaves_the_file_alone`、`test_crlf_files_keep_crlf`、`test_invalid_result_keeps_the_original` | ✅ 其他位元組不變（真實檔案只改冬特的 2 行＋新區塊）、驗證通過、沒有差異時修改時間不變、CRLF 保留、驗證失敗保留原檔 |
| SC-008 | `test_conflict_keeps_the_file_dates`、`test_reschedule_round_trip`、`test_check_is_partial_on_a_conflict_or_a_failure` | ✅ 提醒兩邊日期、預測用檔案的日期；寫回後下一次比對一致、沒有提醒 |

## 真實資料（T029、T043）

### 1. 真實的 `update`＋`report`（副本 `out/mvp/`）

| 項目 | 結果 |
|---|---|
| 升級 | v5 → v6，0.4 秒（含備份 `steamsage.db.bak-v5`） |
| `update` | 結束代碼 0、**79.5 秒**（平常約 80 秒）；提醒 **0** |
| 官方頁面 | `status ok`、列出 4、一致 4、新增 0、不一致 0、頁面沒列 0、尚未寫回 0；**0.59 秒** |
| 請求數 | `steam-partner` **1**；其他 client 和平常相同（steam-webapi 8、steam-store 4、itad 135） |
| `report` | 結束代碼 0、5.9 秒；現在買 11、即將到價 24、繼續等 28、低信心 2、無法預測 3；和前一天比較 3 款有變動（來自價格，不是這個 feature） |

### 2. 和 master 在同一份資料上比對（SC-004、SC-005）

更新後的副本 → `out/master.db`（刪掉兩張新表、schema 5）。master 用 `uv run --project 〈專案資料夾〉` 執行，
已確認載入的是主資料夾的程式碼（`SCHEMA_VERSION` 5），本分支是 6。

| 比對 | 結果 |
|---|---|
| 決策（分析時間 2026-09-27T13:45:16Z） | **68/68** 相同，批次層級沒有差異 |
| `--as-of` HTML 報告 | 逐位元組相同 |
| 調參組回測（`--cutoff 2026-09-25`，各約 66 秒） | 相同（只差執行時間） |

### 3. 模擬「檔案缺 2026 冬特、官方頁面有」（SC-002 的報告部分）

副本 `out/sim/`：行事曆檔刪掉 2026 冬特、官方頁面的兩張表清空 → `calendar`（建立冬特的推估）→ `report`（紀錄 A）→
把紀錄 A 的**檔名**改成前一天（比較基準依檔名的日期選；只用於模擬）→ 放回真實 `update` 的讀取紀錄 → `report`（紀錄 B）。

| 紀錄 | 甜蜜時點是 2026 冬特的遊戲 | 狀態 | `calendar_changes` | 逐款的變動 |
|---|---|---|---|---|
| A（只有推估） | 24 | 預估 | `[]` | 0 |
| B（採用官方） | 24 | **官方** | `["2026 冬特 預估 → 官方（太平洋時間 12/17–1/4）"]` | 0 |

- 報告最上方：「特賣日期更新：2026 冬特 預估 → 官方（太平洋時間 12/17–1/4）（部分變動可能來自這個改變）」；遊戲卡片「2026 冬特（官方）」。
- 390／1100 px 都沒有水平捲動。
- 「與 2026-09-27 21:46 的紀錄比較」顯示今天的時間，是因為只改了紀錄 A 的檔名、內容的時間沒改；正式執行時是前一天的紀錄。

## 已知限制

- 只有季節特賣。Next Fest 與主題特賣在這一頁沒有日期，仍由人工維護。
- 官方頁面只列接下來幾場；在頁面列出之前，季節特賣仍用推估（過去 30 場只有 14 場完全準確，research R0.3）。
- 「第一次看到」的時間從 2026-09-27 起記錄，但每日一次，所以是公告時間的上限；回測不使用它。
- 提醒在每日更新的輸出與背景記錄檔；報告與擴充功能只顯示需要處理的 3 種（改期、頁面格式改變、7 天以上沒有成功讀取）。
