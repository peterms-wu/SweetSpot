# Contract: Steam 特賣行事曆 `data/steam_sales.toml`

這是隨專案維護的正本（FR-033）。每一場特賣都**必須**附上來源網址。

```toml
schema_version = 1
default_time = "10:00"            # 沒有提供精確時間時使用
default_tz = "America/Los_Angeles"

[[sale]]
name = "Steam Summer Sale"
name_zh = "夏季特賣"
kind = "seasonal"                 # seasonal 或 themed
season = "summer"                 # spring、summer、autumn、winter；themed 則省略
year = 2025
start = "2025-06-26"              # 只寫日期時，時間使用 default_time 與 default_tz
end = "2025-07-10"                # 也可以寫完整時間，例如 "2025-07-10T10:00:00-07:00"
status = "ended"                  # ended 或 announced
source = "https://store.steampowered.com/news/..."
confidence = "official"           # official 或 secondary
note = ""
```

## 驗證規則（載入時檢查，違反時 exit 1 並指出是哪一筆）

- `start` 必須早於 `end`；季節特賣的天數必須在 1 到 30 天之間。
- 同一個 `year` 加 `season` 最多一筆，例如 2025 年只能有一場夏季特賣。
- `status = "ended"` 時，`end` 不可晚於現在；`announced` 表示特賣還沒結束。
- `source` 必須是 https 網址，不能指向 steamdb.info（憲章 VIII）。
- `confidence = "secondary"` 表示只有次要來源。可以使用，但在查詢結果中要標示。

> 2026-10-22 稽核補記：「違反時 exit 1」只對 `sweetspot calendar` 成立。`sweetspot update` 遇到行事曆讀不到或驗證失敗時，只在 `alerts` 加一條「特賣行事曆無法使用：…」、
> 略過官方特賣頁、預估與漏收檢查，結束代碼不因此改變。見 [012 contracts/calendar-sync.md](../../012-sale-calendar-sync/contracts/calendar-sync.md) §2 的補記。（`pipeline/daily.py` 的 `update_calendar`）

## 季節特賣的名稱對照

| season | name_zh | 顯示範例 |
|---|---|---|
| spring | 春季特賣 | 2027 春特 |
| summer | 夏季特賣 | 2027 夏特 |
| autumn | 秋季特賣 | 2027 秋特 |
| winter | 冬季特賣 | 2027 冬特。跨年的冬季特賣以開始的年份為準 |

2019–2022 年的「農曆新年特賣」不算春季特賣，以 `kind = "themed"` 記錄。從 2023 年起，春季特賣取代了農曆新年特賣。

秋季特賣從 2025 年起改到 9 月底或 10 月初舉行。11 月的「黑色星期五優惠」不是全站特賣，不收錄為季節特賣。

`end` 是恢復原價的時間，所以最後一天有折扣的日子是 `end` 的前一天。

初始資料的來源見 [research-sales-calendar.md](../research-sales-calendar.md)。

## 自動取得的官方場次（feature 012）

每日更新讀取官方季節特賣頁面，把檔案沒有的季節特賣記在資料庫並用在預測（檔案有的一律用檔案）；`steamsage calendar --sync --write` 以文字編輯把它們寫入本檔，其他內容不變。詳見 [feature 012 的契約](../../012-sale-calendar-sync/contracts/calendar-sync.md)。
