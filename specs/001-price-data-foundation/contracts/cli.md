# Contract: CLI

執行方式：`uv run steamsage <command> [options]`。一鍵入口 `更新資料.cmd` 等同於 `steamsage update`。

> 2026-10-22 稽核補記（已被 003 與 014 取代）：`更新資料.cmd` 現在是「沒有設定檔時先 `sweetspot setup` → `sweetspot update` → `sweetspot report --open --update-exit <代碼>`」，
> 見 [003 contracts/cli.md](../../003-sweet-price-report/contracts/cli.md)「`更新資料.cmd`」與 [014 contracts/cli.md](../../014-publish-github/contracts/cli.md) §5。

## 共用規則

- `--config PATH`：預設為專案根目錄的 `steamsage.toml`，格式見 [config.md](config.md)。
- 進度顯示於 stderr，摘要顯示於 stdout。加上 `--json` 時，stdout 改為輸出一個 JSON 物件（見下方「摘要格式」）。
- 同一時間只能有一個指令寫入資料庫。已有指令在執行時，印出 `另一個更新正在執行（PID n）` 並以 exit 3 結束。
- 輸出中不會出現 API 金鑰。

> 2026-10-22 稽核補記：`--config` 的預設是**目前資料夾**的 `sweetspot.toml`（相對路徑，不是專案根目錄；`更新資料.cmd` 先切到自己的資料夾才執行）。
> `[storage] data_dir` 是相對路徑時，以設定檔所在的資料夾為準，不是目前資料夾（`config.py` 的 `data_dir_of`）。

> 2026-10-22 稽核補記（2026-10-18 起，commit 5cb86d7）：**日誌結果行**。日誌開好之後（設定檔讀取成功之後）的每一種結束，包括鎖被占用的 3、例外的 1、摘要印不出來，
> 都在 `<data_dir>/logs/sweetspot-YYYYMMDD.log`（本機日期，一天一檔；以前是 UTC 日期）寫一行「`<指令> 結束：代碼 N，S 秒；<附加說明>；<摘要的短值>`」：
> 摘要最上層的數字、布林與 120 字以內的字串照寫，清單只寫項數（`failures=2 項`），物件不寫；附加說明例如「執行失敗：…」。代碼 0 記 INFO，其他記 WARNING。
> 摘要的 `failures`、`alerts`、`warnings` 不是空的時，各另寫一行「`<指令> <鍵>：<JSON>`」（超過 500 字截斷），一律 WARNING。
> 不寫的：設定檔讀取以前就結束的（設定錯誤的 1、016 的 4、014 的 5）、`migrate`、`schedule`；`setup` 只在寫了設定檔時寫一行。
> `scripts/backup_db.py` 也寫一行「`backup 結束：代碼 N，S 秒；<印出的內容>`」，在專案資料夾的 `data/logs/`（`--dry-run` 不寫）。（`logs.py` 的 `result_lines`、`log_result`；`cli.py` 的 `done`）

> 2026-10-22 稽核補記（2026-10-18 起，commit 2635759）：stdout／stderr 的編碼不是 UTF-8 時（導到檔案、管線或 NUL），程式一開始就改成 UTF-8；
> 真正的主控台本來就是 UTF-8，不動。以編碼判斷而不是 `isatty()`：NUL 是字元裝置，`isatty()` 為真，以前印出 cp950 沒有的字元會失敗。
> `scripts/backup_db.py` 用同一個函式（`cli.py` 的 `_utf8_when_redirected`）。

## Exit codes

| code | 意義 |
|---|---|
| 0 | 全部完成 |
| 2 | 已完成，但有部分遊戲失敗、被拒絕或資料不足；摘要會列出原因 |
| 1 | 整批失敗，例如設定錯誤、資料庫無法開啟、所有來源都不可用。已寫入的資料保持完整 |
| 3 | 已有其他更新在執行 |
| 4 | （feature 016 起）只有改名前的檔案，要先執行 `sweetspot migrate`，見 [016 contracts/migrate.md](../../016-rename-internal-ids/contracts/migrate.md) |
| 5 | （feature 014 起，2026-10-18）還沒設定：沒有設定檔而且不能互動，要先執行 `sweetspot setup`，見 [014 contracts/cli.md](../../014-publish-github/contracts/cli.md) |

> 2026-10-18（feature 014）：設定檔不再於第一次執行時自動建立；只有 `sweetspot setup` 會建立它。

> 2026-10-22（014 T072）：`update` 的「所有來源都不可用」是：願望清單因為連不上（`network`、`rate-limited`）被拒絕，而且沒有任何一款拿到現價。這時以 1 結束，
> 摘要照樣印出，`status` 是 `failed`，`runs` 也記為 `failed`；以前算成部分完成（2），`更新資料.cmd` 因此說「更新完成，但有部分項目需要注意」。只有一個來源連不上時仍是 2。

> 2026-10-22（014 T069）：參數錯誤（不認得的旗標或子指令、選項不在可選的值裡、型別不對）以 **1** 結束，印出用法與原因到 stderr；以前是 argparse 預設的 2，和「完成但需注意」撞號。

> 2026-10-22（014 T049、T057）：代碼 1 的整批失敗在 stderr 與日誌結果行印一行「執行失敗：<例外類型>: <訊息>」，後面接例外附加的說明（PEP 678 notes，例如 `reference` 的接續句）；
> 整行壓成一行，金鑰的值換成 `***`（訊息與附加的說明都換）。

## 指令

### `steamsage update`（日常更新，FR-029）

依序執行：
1. 同步願望清單。被拒絕時保留上次成功的清單，並用上次的清單繼續執行後面的步驟，摘要會明確標示。
2. 以一次批次請求取得清單遊戲與追蹤中遊戲的台灣區現價，每款新增一筆 `steam-current` 觀測。
3. 補齊或更新中繼資料（依快取期限）。
4. ITAD 對應與核對，接著取得台灣區歷史與輔助區域歷史（依快取期限）。
5. 計算區域一致性，並檢查行事曆提醒。
6. 用參考資料集的小批次時間額度（`reference.daily_budget_seconds`）補抓參考遊戲。

選項：`--skip-reference`（不跑步驟 6）、`--no-history`（只更新清單和現價）。

> 2026-10-22 稽核補記：`--no-history` 不建立 ITAD 來源，略過步驟 4、區域一致性與步驟 6（參考資料集小批次），摘要的 `versions`、`purchase_options` 為 `{"skipped": "no-history"}`；
> 但步驟 3（中繼資料）和步驟 5 的特賣日曆照做，日曆步驟會讀一次官方特賣頁（feature 012）。（`pipeline/daily.py` 的 `run_daily`、`update_reference`）

> 步驟 1 被拒絕時仍繼續用上次的清單，這是為了讓現價紀錄不中斷。清單內容不會被不完整的回應覆蓋，
> 所以仍然符合 FR-002。這種情況的 exit code 為 2（部分完成）。

每個步驟都在 stderr 回報進度，格式為「<步驟名稱> 第 n/N 款」（FR-026）。

### `steamsage reference [--limit N] [--budget SECONDS] [--pool related|broad|refresh|all]`

獨立執行參考資料集的建立或更新（FR-016、FR-017）。可以中斷，重跑時會續接。
`--limit` 限制本次處理的遊戲數；`--budget` 限制本次執行的秒數。

`all`（預設）依序做相關樣本、廣泛樣本，再用剩下的額度做 `refresh`；每日更新的小批次也一樣（FR-017a）。
`refresh`（2026-10-14 補上 US4 情境 4）更新過期的參考遊戲價格歷史：所有參考遊戲（含舊專案匯入的），
台灣區歷史最後確認時間早於 `cache.history_hours` 的，從最舊的開始，兩區各抓一次。
略過沒有可用 ITAD 商品（對應被拒絕、版本被拒絕）或從未有過歷史的遊戲。來源錯誤時停止，不把額度花在失敗的來源上。
摘要多一個 `refresh` 欄位：`{"status", "stale", "refreshed", "left", "new_rows"}`。
（2026-10-22，014 T049；014 T071 更正）來源錯誤分兩種：
- 判斷候選時查 Steam 商店資料（appdetails）失敗，例如商店整站 502 → 整次執行以 1 結束。
- 其他來源錯誤 → 寫成提醒，該部分記為失敗，其餘照做，以 2 結束：發行商目錄查詢、抓價格歷史、抓 Steam 遊戲清單（014 T071 起；以前只在摘要寫 `broad.status = "failed"`，以 0 結束）、`refresh`。
  每日更新的參考資料集小批次也一樣，提醒併入 `update` 的 alerts。
（014 T062 原本寫成「判斷候選、抓遊戲清單、`refresh` 都以 1 結束」，與程式不符，由 014 T071 更正。）
以 1 結束時，stderr 與日誌結果行在「執行失敗：…」之後
多一句「已完成的部分都已保存；來源恢復後再執行 uv run sweetspot reference 會接著做。」行為（停止、不把剩下的候選記成失敗）不變。

> 2026-10-22 稽核補記（commit 2beb526）：摘要多一個 `http`，每個這次用到的來源一項：
> `{"<來源>": {"requests": 請求數, "throttle_wait_s": 節流等待秒數, "by_path": {"<URL 路徑>": 請求數}}}`，來源名稱是 `steam-webapi`、`steam-store`、`itad`（沒有 ITAD 金鑰時沒有這項）。
> `update` 的摘要也有 `http`，另多 `steam-partner`（官方特賣頁）；[012 contracts/calendar-sync.md](../../012-sale-calendar-sync/contracts/calendar-sync.md) §2 說的「和 `reference` 相同的格式」就是這個。（`commands.py` 的 `http_usage`）

### `steamsage import-legacy [PATH]`

匯入舊專案快取（FR-019、FR-020），PATH 預設為 `〈前身專案資料夾〉\state\cache`。可以重複執行，不會產生重複資料。

> 2026-10-22 稽核補記（已被 014 T013 取代，014 FR-010）：PATH 沒有預設值了。沒有給 PATH、設定檔的 `[legacy] cache_path` 也是空的 → 說明這個指令只給前身專案的使用者、怎麼指定資料夾，
> 結束代碼 1，摘要 `{"status": "not_configured"}`。

### `steamsage coverage [--app APPID] [--scope wishlist|reference|all] [--csv PATH]`

輸出覆蓋摘要（FR-021）。只讀取資料，不需要鎖。
（2026-10-22，014 T070）以前實際開的是寫入連線：資料庫不存在時會建立一個空的，資料庫是舊版時會在沒有鎖的情況下升級。現在和其他唯讀指令一樣用唯讀連線：
資料庫不存在 → 以 1 結束、什麼都不建立；資料庫是舊版 → 「資料庫是舊版（vN），請先執行 sweetspot update 升級」，以 1 結束。
`--csv` 輸出時，欄位開頭是 `=`、`+`、`-`、`@`、Tab 或 CR 的，前面加上 `'`，避免被試算表當成公式執行（憲章 IX）。

### `steamsage calendar [--check]`

列出已知與預估的特賣。加上 `--check` 時，執行 FR-033 的兩項提醒檢查。

> 2026-10-22 稽核補記（已被 012 的 contracts/calendar-sync.md §4 取代）：多了 `--fetch`（先讀一次官方特賣頁）、`--sync`（列出和 `data/steam_sales.toml` 的差異）、
> `--sync --write`（寫入；`--write` 沒有 `--sync` 以 1 結束，寫入失敗也是 1）。`--check` 有提醒或疑似漏收的特賣時以 2 結束，否則 0。

## 摘要格式（`--json`）

```json
{
  "run_id": "…",
  "kind": "daily",
  "status": "completed | partial | failed | interrupted",
  "started_at": "2026-09-24T12:00:00Z",
  "finished_at": "…",
  "wishlist": {"status": "ok | empty | rejected", "reject_reason": null, "count": 68,
               "added": [123], "removed": [456]},
  "current_prices": {"ok": 66, "failed": 0, "unreleased": 2, "free": 0, "not_purchasable": 0},
  "history": {"fetched": 10, "reused": 56, "rejected": 2, "failed": 0},
  "aux_history": {"fetched": 10, "reused": 50, "unavailable": 6},
  "reference": {"budget_seconds": 120, "processed": 14, "dataset_size": 1732},
  "failures": [{"app_id": 123, "stage": "mapping", "reason_code": "different-product", "message": "…"}],
  "alerts": ["2027 春季特賣尚無公告或預估"]
}
```

> 2026-10-22 稽核補記：`update` 實際的摘要**沒有 `finished_at`**（結束時間只在資料庫的 `runs`）；`status` 只會是 `completed`、`partial` 或 `failed`（`interrupted` 只出現在 `runs`，由下一次執行標記）。
> 代碼 1 時：「所有來源都不可用」（014 T072）照樣印出摘要、`status: failed`；其他整批失敗（例外）stdout 不印摘要，只有 stderr 的「執行失敗：…」，`runs` 那一列留在 `running`。
> 另外依情況多這些最上層欄位：`wishlist` 的 `used_previous`、`tracked`，`metadata`、`mappings`、`price_checks`、`versions`、`purchase_options`、`calendar`、`consistency`、`http`；
> `reference` 是 `{"status": "ok | skipped | failed", "budget_seconds", "dataset_size", …}`；`current_prices` 另有 `unsupported`、`delisted`、`not_found`。（`pipeline/daily.py` 的 `run_daily`；`commands.py` 的 `update`）
