# Implementation Plan: 特賣日期自動更新

**Branch**: `012-sale-calendar-sync` | **Date**: 2026-09-27 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/012-sale-calendar-sync/spec.md`

## Summary

1. **來源**（research R1）：新模組 `sources/steam_partner.py`：一個獨立的 `steam-partner` client 讀官方季節特賣頁面（不重試、429 不等待、403 停用），
   純函式解析「Dates」一節（3 種日期寫法＋`TBD`）。可抽換的 `SeasonalSalesSource` Protocol（憲章 VIII）。
2. **儲存**（R2）：schema v6，兩張只新增的表 `calendar_fetches`（每次讀取）、`sale_sightings`（每次成功讀取中的每一場）；第一次／最後一次看到由查詢算出。
3. **合併**（R3）：`calendar.effective_events`＝檔案的場次＋檔案沒有的官方場次（最近一次看到的日期）。**檔案有的一律用檔案**（改期時沿用，clarify Q2）。
   唯一的合併點：`PriceStore._events()`、每日更新的行事曆步驟、`steamsage calendar`。推估的取代沿用 `refresh_estimates`。
4. **每日更新**（R4）：第 5 步多抓一次官方頁面（每次 1 個請求，實測 0.64 秒）；任何失敗只變成提醒與失敗紀錄，其他步驟不受影響。
5. **寫回**（R5）：`steamsage calendar --sync` 列出差異，`--sync --write` 以文字編輯寫入 toml（其他位元組不變，寫入後驗證）；`--fetch` 立即讀取一次。
6. **比較說明**（R6）：正式紀錄的比較多一個 `calendar_changes`，報告顯示「特賣日期更新：2026 冬特 預估 → 官方（…）」。
7. **需要處理的提醒**（D1＝A）：改期、頁面格式改變、7 天以上沒有成功讀取 → 決策輸出的新選用欄位 `calendar_notices`，報告最上方的橫幅與擴充功能彈出視窗的標題下方顯示（和「本次資料更新失敗」同一處）。
8. **不變**：模型、規則、回測（過去時點只看已結束的場次）、行事曆檔格式、既有的 `warnings`。

**plan 階段的原型**（research R0，真實資料、唯讀）：

| 項目 | 結果 |
|---|---|
| 今天的官方頁面（P1、P4） | 4/4 場和 toml 一致；抓取 0.64 秒、解析 12 ms |
| 8 種變形頁面（P1） | 新增、改期、改名、格式改變、沒有日期區、空白頁、提前消失、標點不同：全部分類正確 |
| Wayback 42 份快照（P2，2024-03～2026-08） | 42/42 找到日期區；**104 行日期全部和 toml 一致**、不採用 0、改期 0；`TBD` 56 行 |
| 發現的問題 | 第一版只認 2026 的寫法，過去的快照有 73 行被當成錯誤 → 支援 3 種寫法與 `TBD`；Wayback 的 gzip 差點被誤判成改版 |
| 公告提前多久（P2） | 第一次出現在快照到開始 55–337 天；13 場中 12 場 ≥ 2 個月 |
| 推估有多準（P3） | 過去 30 場只有 **14 場**完全準確；多半差 1–8 天，2025 秋特差 59 天 |
| 採用的影響（P3，68 款） | 2026 冬特若只是推估：24 款的甜蜜時點在那一場；公告後 24 款 預估 → 官方，分組與甜蜜價不變。**既有的逐款比較看不到這個改變** → R6 |
| 洩漏（P3） | 採用前後，過去 94 個時點的特賣清單 0 個不同 |
| 時刻（P4） | 2026 秋特自己的頁面：「at 10am Pacific」＝ toml 的預設時間 |

## 需要使用者決定（D1–D3）

**使用者 2026-09-27 確認 plan，D1–D3 全部依建議 A。**

**D1 的更正**（tasks 前發現）：表中寫「報告與擴充功能既有的『提醒』（`warnings`）」是錯的：`warnings` 目前只印在 `report` 指令的輸出，報告與擴充功能都不顯示它。目的不變（你看得到），做法改成新的選用欄位 `calendar_notices`，報告放在最上方的橫幅、擴充功能放在彈出視窗的標題下方，都和「本次資料更新失敗」同一處；不沿用 `warnings`，因為顯示它會連同既有的其他警告一起改變報告。

| # | 問題 | 選項 | 建議 |
|---|---|---|---|
| D1 | 需要你處理的提醒（改期、官方頁面 7 天以上沒有成功讀取、頁面格式改變）要不要顯示在**報告**上？每日更新的提醒平常只在背景記錄檔裡 | **A** 這 3 種放進報告與擴充功能既有的「提醒」（`warnings`）；「新增已採用、尚未寫回」不放（不影響預測）／**B** 只在每日更新的輸出與 `calendar --check`／**C** 全部提醒都放進報告 | **A**：改期時預測用的是檔案的舊日期，你不看記錄檔就不會知道；「尚未寫回」每天出現會變成雜訊 |
| D2 | 寫回的確認方式 | **A** `--sync` 只列出差異，`--sync --write` 才寫／**B** `--sync` 列出後問「是否寫入？(y/N)」 | **A**：非互動，PowerShell、Git Bash、測試都一樣 |
| D3 | 資料庫升版 | **A** 升到 v6（和 004、009、010 相同：升級前自動備份 `steamsage.db.bak-v5` 約 160 MB，確認沒問題後可刪）／**B** 不升版，讀取端容忍新表不存在 | **A**：版本號代表資料庫的內容；B 要在每個讀取點處理「沒有這張表」 |

## Technical Context

**Language/Version**：Python ≥3.12（開發機 3.14.6），uv。

**Primary Dependencies**：不新增套件（`httpx` 既有；解析用標準函式庫 `re`、`html`）。

**Storage**：SQLite schema v5 → v6（兩張新表，只新增）；`data/steam_sales.toml` 只由 `calendar --sync --write` 修改。

**Testing**：pytest，測試先行；官方頁面用 `tests/fixtures/partner/` 的精簡副本與 `httpx.MockTransport`（不連網）；
擴充功能的 `node --test` 與 `e2e.py` 照舊，另加 `calendar_notices` 的顯示測試（資料檔只多一個選用欄位）。

**Target Platform**：Windows 11 本機；每日背景更新 02:30（主資料夾 master）。

**Project Type**：單一 Python CLI 專案。

**Performance Goals**：每日更新增加 ≤ 3 秒（SC-006；實測抓取 0.64 秒＋解析 12 ms）；`report` 不增加可量測的時間（多讀兩張小表）。

**Constraints**：

- 只連官方頁面一個網址，每次 `update` 1 個請求（SC-006、憲章 VIII）。
- 抓取失敗不影響其他步驟，不被當成沒有特賣（憲章 I、III）。
- 檔案有的場次一律用檔案（clarify Q2）；每日更新不改進版控的檔案（clarify Q1）。
- 過去時點看不到當時還沒開始的場次（憲章 IV）。

**Scale/Scope**：頁面一次列 1–4 場；每天約 4 列；151 筆檔案場次（季節 51）。

## Constitution Check

依憲章 **1.2.0**。

| 原則 | 檢查 | 結果 |
|---|---|---|
| I 未知不是零 | 抓取失敗、解析不到、個別行不採用都有明確的狀態與提醒，不移除、不改動任何場次；`TBD` 記為待定，不當作沒有特賣 | ✅ |
| II 證據可追溯 | 每次讀取記錄時間、網址、HTTP 狀態、SHA-256、不採用的行；採用的場次 `source` 為官方網址；第一次／最後一次看到可查；寫回的 `note` 註明來源與日期 | ✅ |
| III 逐項隔離失敗 | 官方頁面步驟的例外只變成一行提醒與失敗紀錄；寫回驗證失敗保留原檔；抓取與寫入在同一個交易 | ✅ |
| IV 可驗證（不可協商） | 過去時點的過濾不變（P3：0/94）；洩漏測試含反向測試；第一次看到的時間不進入回測；模型與規則不變，不需要回測比較；同一份資料上和 master 的回測相同（SC-004） | ✅ |
| V 規則單一正本 | 沒有新增或改變預測、決策規則；行事曆的合併規則寫在 `calendar.py` 一處，契約寫在 contracts | ✅ |
| VI 簡單優先 | 沒有新參數（7 天、2 秒、30 秒是操作上的門檻，不是模型參數）；不新增套件；不做 Next Fest、主題特賣、其他來源（YAGNI） | ✅ |
| VII 核心與呈現分離 | 報告與擴充功能只顯示核心算好的 `calendar_changes` 與 `calendar_notices`，兩邊的文字相同 | ✅ |
| VIII 資料來源條款 | 官方 Valve 網站、robots.txt 沒有禁止、每次 1 個請求、401/403 停用、429 不等待；可抽換的 Protocol；Wayback 只用於 plan 階段研究格式，正式功能不讀 | ✅ |
| IX 本機與安全 | 資料只存在本機；沒有金鑰；頁面文字只當資料（只取日期，不執行）；寫回的 `note` 不含頁面原文以外的東西 | ✅ |

**Post-design re-check**：data-model 與 contracts 沒有新增違反；D1 的提醒由核心產生，報告與擴充功能只顯示（VII）。

## Project Structure

### Documentation (this feature)

```text
specs/012-sale-calendar-sync/
├── spec.md
├── plan.md              # 本文件
├── research.md          # R0（原型）、R1–R8
├── data-model.md
├── quickstart.md
├── contracts/
│   └── calendar-sync.md
├── checklists/requirements.md
├── prototype/           # p1_parse、p2_wayback、p3_adopt、p4_fetch；out/ 不進版控
└── tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
src/steamsage/
├── sources/__init__.py          # SeasonalSalesSource Protocol、SeasonalSalesPage、OfficialSale、RejectedLine
├── sources/steam_partner.py     # 新：SteamPartnerDocs（client）＋ parse_seasonal_sales（純函式）
├── calendar.py                  # compare_official、effective_events（純函式）
├── calendar_sync.py             # 新：record_fetch、adopted_sales、official_alerts、sync_plan、write_sync（文字編輯＋驗證）
├── store/schema.py              # v6：calendar_fetches、sale_sightings、只新增觸發器、升級
├── store/query.py               # _events() 改用 effective_events
├── pipeline/daily.py            # DailySources.sales_page；update_calendar 抓取、合併、提醒
├── commands.py                  # update 接上來源；calendar --fetch/--sync/--write
├── cli.py                       # calendar 的新參數
├── decision/changes.py          # calendar_changes
├── decision/engine.py           # （D1）正式執行時的 calendar_notices
├── report/html.py               # 「特賣日期更新」一行；calendar_notices 橫幅
└── report/extension.py          # 資料檔帶 calendar_notices

extension/lib.js、popup.js        # 彈出視窗標題下方顯示 calendar_notices

tests/
├── fixtures/partner/            # 精簡的頁面副本：2026-09-27、2025（月在前）、2024-03（年份一次）、含 TBD
├── unit/test_steam_partner.py   # 解析：3 種寫法、TBD、各種不採用；client 的 403／429／逾時
├── unit/test_calendar_sync.py   # 比對、合併、採用的場次、提醒、寫回（位元組不變、驗證失敗保留原檔）
├── unit/test_schema_migration.py  # v5 → v6
├── integration/test_daily_calendar.py  # 每日更新：一致、新增、改期、5 種失敗
├── contract/test_no_future_leak.py     # 採用的未來場次看不到＋反向測試；forecast/decision 不引用新表
└── contract/test_cli_calendar.py       # --fetch、--check、--sync、--sync --write
```

**Structure Decision**：沿用單一專案的結構。解析規則屬於來源（`sources/`），比對與合併是純函式（`calendar.py`），
資料庫與檔案的讀寫放在新的 `calendar_sync.py`，讓 `calendar.py` 維持不依賴來源。

## 實作順序與 checkpoint

1. 解析器與來源（fixtures、單元測試）→ commit。
2. schema v6 與 `record_fetch`、`adopted_sales`、`compare_official`、`effective_events` → commit。
3. 每日更新接上（整合測試：一致、新增、改期、5 種失敗）＋ `PriceStore` 合併＋洩漏測試 → commit；**MVP：在資料庫副本上跑一次真的 `update` 與 `report`，給使用者看**。
4. `calendar --fetch/--check/--sync/--write` → commit。
5. `calendar_changes` 與報告的一行（D1 的提醒）→ commit。
6. 驗證（SC-001–SC-008，和 master 在同一份資料上比對）、README、HANDOFF → commit，詢問是否合併（建議秋特結束後）。

## Complexity Tracking

沒有違反憲章的地方需要說明。
