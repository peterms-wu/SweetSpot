# Contract: 特賣日期自動更新（指令、摘要、提醒、寫回格式）

**Feature**: 012-sale-calendar-sync | 相關：既有的 `specs/001-price-data-foundation/contracts/sales-calendar.md`（行事曆檔格式，不變）

## 1. 官方來源

| 項目 | 值 |
|---|---|
| 網址 | `https://partner.steamgames.com/doc/marketing/discounts/seasonalsales`（只讀這一個） |
| 次數 | 每次 `update` 1 個請求；`steamsage calendar --fetch` 1 個請求；其他指令 0 |
| client | `steam-partner`，間隔 ≥ 2 秒、不重試、429 不等待、401/403 停用、逾時 30 秒、上限 2 MB、`User-Agent` 為專案既有的值 |
| 解析 | 只讀「Dates」一節；3 種日期寫法與 `TBD`（research R0.2、R1）；時刻用行事曆的預設（太平洋時間 10:00） |

## 2. `steamsage update` 的摘要

摘要最上層的 `calendar`（既有的 `{"status", "new_estimates"}`）多一個 `official_page`；另外 `update` 的摘要多一個 `http`（各 client 的請求數，和 `reference` 相同的格式）：

```json
{
  "status": "ok | no_dates | failed | denied | rate_limited | skipped | not_fetched",
  "listed": 4, "pending": 0, "rejected": 0,
  "same": 4, "new": 0, "conflict": 0, "missing": 0, "not_in_file": 0,
  "last_success": "2026-09-27T12:58:48+00:00",
  "seconds": 0.7
}
```

`skipped`：行事曆檔讀取失敗，沒有抓（FR-009）；`not_fetched`：這次沒有官方頁面來源（只在測試或其他呼叫者），比對用資料庫中最近一次成功的讀取。`update` 的結束代碼規則不變（提醒本來就不改變結束代碼）。

> 2026-10-22 稽核補記：行事曆檔讀不到時，`official_page` 只有 `{"status": "skipped"}`，沒有上面的各類計數、`last_success`、`seconds`；外層的 `calendar` 也只有 `{"status": "unavailable", "official_page": {...}}`（沒有 `new_estimates`），另加一行提醒「特賣行事曆無法使用：…」。（`pipeline/daily.py`；`tests/integration/test_daily_calendar.py` 的 `test_calendar_file_error_skips_the_page`）

## 3. 提醒（每日更新的 `alerts`；`calendar --check` 相同）

一致時沒有任何一行。每一類最多一行（同一類的多場寫在同一行），不會每天堆疊。

| 情況 | 文字 |
|---|---|
| 新增並已採用（尚未寫回，每天一行，直到寫回） | `官方特賣頁面公告了 2027 秋特（太平洋時間 9/30–10/7），已用於預測；執行 steamsage calendar --sync --write 寫入 data/steam_sales.toml` |
| 不一致 | `官方特賣頁面的 2026 冬特是 12/18–1/4，data/steam_sales.toml 是 12/17–1/4；預測沿用檔案的日期。確認後執行 steamsage calendar --sync --write` |
| 未寫回的場次被改期 | `官方特賣頁面把 2027 秋特從 9/30–10/7 改成 10/7–10/14（尚未寫入檔案，已改用新日期）` |
| 還沒結束卻從頁面消失 | `官方特賣頁面不再列出 2027 春特（可能取消或改名）；行事曆保留原本的日期` |
| 不採用的行 | `官方特賣頁面有 1 行無法解析，已略過：Holiday Sale 2026 \| 17 December, 2026 - 4 January, 2027（未知的季節）` |
| 解析不到 | `官方特賣頁面格式改變，找不到任何季節特賣日期；特賣日期沿用既有紀錄` |
| 抓取失敗 | `官方特賣頁面抓取失敗（<原因>），特賣日期沿用既有紀錄` |
| 被拒絕 | `官方特賣頁面拒絕存取（HTTP 403），本次停止，不重試；特賣日期沿用既有紀錄` |
| 被限速 | `官方特賣頁面要求等待 <N> 秒（HTTP 429），本次略過；特賣日期沿用既有紀錄` |
| 7 天以上沒有成功讀取 | `官方特賣頁面已 <N> 天沒有成功讀取（最後一次 <台北日期>）` |

日期是太平洋時間的日期（和官方頁面、行事曆檔相同）；報告上的時間照舊用台北時間。

> 2026-10-22 稽核補記（「7 天以上沒有成功讀取」的實際文字）：有成功過時是 `官方特賣頁面已 <N> 天沒有成功讀取（最後一次 YYYY-MM-DD HH:MM 台北）`（台北的日期加時刻，後面接「台北」）；從未成功過時是 `官方特賣頁面已 <N> 天沒有成功讀取（從未成功）`，天數從第一次嘗試讀取算起（還沒嘗試過就不提醒）。N 是整天數（無條件捨去）。這句也算 `calendar_notices`（第 6 節），會出現在報告橫幅與擴充功能的彈出視窗。（`calendar_sync._stale_alert`；`tests/integration/test_daily_calendar.py` 的 `test_stale_official_page`、`test_never_successful_for_a_week`）

## 4. `steamsage calendar`

| 參數 | 行為 | 網路 | 改檔 |
|---|---|---|---|
| （無） | 和現在相同，另外在摘要加 `official_page`（最近一次讀取的比對結果） | 0 | 否 |
| `--check` | 和現在相同＋第 3 節的提醒；有新增未寫回、不一致、頁面沒列、不採用的行、最近一次失敗、7 天以上沒成功時，結束代碼為「部分完成」 | 0 | 否 |
| `--fetch` | 先讀取一次官方頁面（寫入 `calendar_fetches`），再做上面的事 | 1 | 否 |
| `--sync` | 列出會寫入的差異（新增、不一致），不改檔 | 0 | 否 |
| `--sync --write` | 寫入 `data/steam_sales.toml`；沒有差異時顯示「已一致」、不改檔 | 0 | 是 |

`--sync` 的摘要：

```json
{"sync": {"written": false, "add": [{"label": "2027 秋特", "start": "2027-09-30", "end": "2027-10-07", "first_seen": "2027-04-02"}],
          "reschedule": [{"label": "2026 冬特", "file": ["2026-12-17", "2027-01-04"], "official": ["2026-12-18", "2027-01-04"]}],
          "based_on_fetch": "2026-09-27T12:58:48+00:00"}}
```

## 5. 寫回的格式

新增（插在第一個開始時間比它晚的 `[[sale]]` 之前；前後各空一行）：

```toml
[[sale]]
name = "Steam Autumn Sale"
name_zh = "秋季特賣"
kind = "seasonal"
season = "autumn"
year = 2027
start = "2027-09-30"
end = "2027-10-07"
status = "announced"
source = "https://partner.steamgames.com/doc/marketing/discounts/seasonalsales"
confidence = "official"
note = "Listed on the official seasonal sales page; first seen 2027-04-02 (written by steamsage calendar --sync on 2027-04-05)."
```

改期：只改那個區塊的 `start`、`end`、`source`，`note` 後面加
` Rescheduled per the official seasonal sales page (seen 2026-10-02); previously 2026-12-17 to 2027-01-04 from <舊 source>.`
（原本沒有 `note` 時新增一行）。檔案的其他位元組不變；寫入後以 `load_calendar` 驗證，失敗時保留原檔。

## 6. 決策輸出與報告

- `comparison.calendar_changes: list[str]`（選用；research R6）。例：`["2026 冬特 預估 → 官方（太平洋時間 12/17–1/4）"]`、`["2027 春特 官方日期 3/18–3/25 → 3/25–4/1（太平洋時間）"]`。日期是太平洋時間的開始日與官方頁面的第二個日期（恢復原價那天），和第 3 節相同。
- 報告的比較摘要：每一項一行 `特賣日期更新：2026 冬特 預估 → 官方（太平洋時間 12/17–1/4）（部分變動可能來自這個改變）`。
- 甜蜜時點的「官方／預估」標示與日期：既有的顯示，採用後自動變成「官方」。
- D1＝A（plan 已確認）：第 3 節中需要使用者處理的 3 種（「不一致」＝改期；「解析不到」與「不採用的行」＝頁面格式改變；「7 天以上沒有成功讀取」）寫進決策輸出的新選用欄位 `calendar_notices`（字串陣列），報告顯示在最上方的橫幅（和「本次資料更新失敗」同一處），擴充功能的資料檔帶同一個欄位、彈出視窗顯示在標題下方（和資料更新失敗的說明同一處）。其他提醒只在每日更新的輸出與 `calendar --check`。只有正式 `report` 產生；既有的 `warnings` 不變。
