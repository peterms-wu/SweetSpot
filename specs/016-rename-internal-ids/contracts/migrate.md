# Contract: `sweetspot migrate` 與「需要先搬家」（016）

## 1. 指令

```text
uv run sweetspot migrate [--config sweetspot.toml] [--dry-run] [--json]
```

- **主資料夾**是 `--config` 的上一層，預設是目前資料夾。舊設定檔固定是同一層的 `steamsage.toml`。
- **`data_dir`**：從舊設定檔的 `[storage] data_dir` 以 `tomllib` 唯讀取得，不呼叫 `load_config`，因為它會建立檔案。設定檔已是新名稱時從新設定檔取得，沒有設定檔就用預設的 `data`。
- **`--dry-run`**：判斷每個檔案的狀態與每個環境步驟會怎麼做，印出計畫。不取鎖、不改任何檔案、不呼叫 PowerShell 的寫入指令、不寫 `migration.json`，也不寫日誌（不建立日誌檔或日誌資料夾）。結束代碼 0；有 `both` 時為 1。
- **`--json`**：摘要以 JSON 印到 stdout，欄位和 `migration.json` 相同（data-model §2）。
  （2026-10-22 稽核補記）`--json` 也會印出不寫 `migration.json` 的情況與值（`outcome` 的 `refused`、`dry-run`、`already` 等），見 data-model §2 的補記。

## 2. 結束代碼

| 代碼 | 意義 |
|---|---|
| 0 | 搬好了，或已經是新名稱、什麼都沒改；環境步驟都已完成或不適用 |
| 2 | 檔案搬好了，但有環境步驟（本機程式、排程工作）沒能自動完成，已列為手動步驟 |
| 1 | 沒有搬：新舊並存（`both`）、資料庫正在被其他程式使用（checkpoint 忙碌）、備份失敗，或改名、驗證失敗後已改回；印出原因、停在哪一步、每個檔案現在的名稱 |
| 3 | 寫入鎖被占用（背景更新或本機程式正在執行），什麼都沒改 |

## 3. 輸出（一般模式）

依序印出：

1. 每個檔案的狀態與結果，例如 `設定檔 steamsage.toml → sweetspot.toml：已搬（SHA-256 相同）`。
2. 備份資料夾的完整路徑。
3. 每個環境步驟的結果：`完成`／`已完成`／`不適用：<原因>`／`失敗：<原因>，改成手動步驟`。
4. **接下來要你做的事**，逐項編號：
   - 一律有：在 Chrome 開 `chrome://extensions`，對 SweetSpot 按「重新載入」（版本應顯示 1.2.0）；重新載入前，Steam 頁面上的面板與願望清單那一行會暫時不顯示。
     （2026-10-22 稽核補記）程式印的是「版本應顯示 1.2.0 以上」（migrate.py）；擴充功能之後又升過版（現在的版本見 extension/manifest.json）。
   - 一律有：擴充功能面板中的設定檔路徑會在下一次報告後更新；想立即更新可以執行 `更新資料.cmd`，否則等 02:30。
   - 一律有：確認 02:30 背景更新正常後，可以刪除備份資料夾 `<完整路徑>`。
   - 環境步驟失敗時：對應的手動指令。
     - 本機程式：`uv run sweetspot host install`。
     - 排程工作：三行 PowerShell，依序匯出 XML、用新名稱建立、刪除舊的。

正式搬家（不是 `--dry-run`）的每一步也寫進當天的日誌 `data/logs/sweetspot-YYYYMMDD.log`，日誌照常經過遮蔽金鑰的過濾。`migration.json`、輸出與日誌都不包含 API 金鑰（FR-015）。

## 4. 「需要先搬家」（FR-010）

`migrate` 以外的每個子指令，在 `load_config` 之前、以及開啟資料庫之前各檢查一次（research R7）。設定檔或資料庫為 `old-only` 時：

- stderr 印出一行：

  ```text
  找到舊名稱的檔案（<檔名>），請先執行搬家：uv run sweetspot migrate
  ```

- 結束代碼 **4**；
- 不建立設定檔、資料庫、日誌資料夾或任何其他檔案；
- 不取鎖。

`--help`、`--version` 由 argparse 在檢查之前處理，不受影響。

新舊並存（`both`）時照常執行，stderr 每個檔案印一行：

```text
警告：舊名稱的檔案還在（<檔名>），沒有使用；確認不需要後可以自行刪除
```

## 5. 結束代碼 4 在其他地方

| 位置 | 行為 |
|---|---|
| `cli.py` | `EXIT_NEEDS_MIGRATION = 4`；模組說明的結束代碼清單加上 4 |
| `report --update-exit` | 選項為 0–4；收到 4 時報告的更新狀態文字和 1 相同類別（更新沒有完成），另註明原因是需要先搬家。（2026-10-22 稽核補記：014 起選項為 0–5，見 014 contracts/cli.md。收到 5 時報告沒有更新狀態文字；實際上走不到這裡：沒有設定檔時 `report` 自己就以 5 結束。014 T069 起接受任何整數，其他代碼當作 1，見 003 contracts/cli.md。） |
| `更新資料.cmd` | 整體結束代碼優先順序 1 > 4 > 3 > 2 > 0；update 為 4 時印出「找到舊名稱的檔案，請先執行搬家：uv run sweetspot migrate」。（2026-10-22 稽核補記：已被 014 取代）順序改為 1 > 5 > 4 > 3 > 2 > 0（014 data-model「結束代碼」）；update 的代碼不在 0–5 時整體算 1（014 T069）。見 014 contracts/cli.md §5 |
| `背景更新.cmd` | 同樣的優先順序；結束行照常列出 `update <代碼>，report <代碼>，backup <代碼>，整體 <代碼>`。（2026-10-22 稽核補記：已被 014 取代）同上，1 > 5 > 4 > 3 > 2 > 0、不在 0–5 的 update 代碼算 1（014 T069）；update 為 5 時略過備份，結束行寫「backup 略過（還沒設定）」（014 T059）。backup 的代碼不算進整體 |
| `scripts/backup_db.py` | 資料庫為 `old-only` 時印出相同提示，結束代碼 4，不建立 zip、不上傳 |
