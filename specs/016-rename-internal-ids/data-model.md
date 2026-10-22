# Data Model: 內部識別碼改名（016）

這個 feature 不改資料庫結構（schema 仍是 v7），也不改任何已保存紀錄的格式。新增的只有程式內的名稱對照，以及搬家時寫的一份紀錄。

## 1. 名稱對照（`src/sweetspot/legacy.py`）

程式內的常數，內容即 contracts/names.md §1 中「搬家」與「舊名稱保護」用到的部分。

| 欄位 | 說明 |
|---|---|
| `kind` | `config`、`db`、`extension_data` |
| `label` | 給人看的名稱：`設定檔`、`資料庫`、`擴充功能資料檔` |
| `old` | 相對於所在資料夾的舊檔名：`steamsage.toml`、`steamsage.db`、`data/steamsage-extension.json` |
| `new` | 新檔名：`sweetspot.toml`、`sweetspot.db`、`data/sweetspot-extension.json` |
| `base` | 所在資料夾：`config` 在主資料夾，`db` 在 `data_dir`，`extension_data` 在主資料夾的 `extension/` |
| `companions` | 只有 `db`：`("-wal", "-shm")`，存在就跟著改名 |
| `blocks` | `config`、`db` 為 true：`old-only` 時一般指令以 4 拒絕（FR-010）；`extension_data` 為 false |

另有兩個常數：
- 排程工作名稱：舊「SteamSage2 每日背景更新」、新「SweetSpot 每日背景更新」；
- 舊本機程式模組 `steamsage.host`：用來判斷啟動檔要不要重寫。

**狀態**：`old-only`／`new-only`／`both`／`absent`。由「舊檔是否存在、新檔是否存在」直接決定，見 contracts/names.md §3。

## 2. 搬家紀錄 `migration.json`

位置：`data/pre-016-backup-<YYYYMMDD-HHMMSS>/migration.json`，UTF-8，縮排 2。

搬家時寫兩次：
- 檔案段結束、釋放鎖之後；
- 環境段結束後覆寫一次。

失敗時也寫，記錄停在哪一步。`--dry-run` 不寫。

```json
{
  "format": "sweetspot.migration/1",
  "started_at": "2026-10-16T05:00:00Z",
  "finished_at": "2026-10-16T05:00:09Z",
  "folder": "〈專案資料夾〉",
  "outcome": "migrated",
  "failed_step": null,
  "error": null,
  "files": [
    {"kind": "db", "old": "data\\steamsage.db", "new": "data\\sweetspot.db", "state_before": "old-only",
     "result": "moved", "bytes": 206405632, "sha256": "…",
     "companions": [{"old": "data\\steamsage.db-wal", "new": "data\\sweetspot.db-wal", "bytes": 0}]}
  ],
  "backup": {"dir": "data\\pre-016-backup-20261016-130000",
             "files": [{"name": "steamsage.db", "bytes": 206405632, "check": "ok"}]},
  "environment": [
    {"step": "host", "result": "done", "detail": "重寫 data\\host\\sweetspot-host.bat"},
    {"step": "task", "result": "done", "detail": "SteamSage2 每日背景更新 → SweetSpot 每日背景更新"}
  ],
  "manual_steps": ["在 Chrome 開 chrome://extensions，對 SweetSpot 按「重新載入」（版本應顯示 1.2.0）", "…"]
}
```

| 欄位 | 規則 |
|---|---|
| `format` | 固定 `sweetspot.migration/1`。新格式用新名稱；只有既有格式保留舊名（contracts/names.md §2） |
| `started_at`、`finished_at` | UTC，ISO 8601，到秒 |
| `folder` | 主資料夾的完整路徑 |
| `outcome` | `migrated`（有檔案被搬）或 `failed`（已改回）。檔案已是新名稱（只補做環境步驟），或被拒絕（`both`、鎖被占用、checkpoint 忙碌）時，不建立備份資料夾，也不寫這份紀錄；這些情況和每一次搬家的每一步，都另外寫進當天的日誌 `data/logs/sweetspot-YYYYMMDD.log` |
| `failed_step` | `outcome` 為 `failed` 時：`backup`、`rename`、`verify` 之一，否則 null |
| `error` | 失敗原因（一行，給人看），否則 null |
| `files[].result` | `moved`、`already`（這一項本來就是新名稱）、`absent`、`rolled-back` |
| `files[].sha256`、`bytes` | 改名前記錄。驗證時新檔的值必須相同，否則 `failed_step = verify` |
| `backup.files[].check` | 資料庫為 `PRAGMA quick_check` 的結果（`ok` 或第一行錯誤）；其他檔案為 `copied` |
| `environment[].step` | `host`、`task` |
| `environment[].result` | `done`、`already`、`skipped`（不是這個資料夾的登記，或沒有登記）、`failed`（轉成手動步驟） |
| `manual_steps` | 和輸出的「接下來要你做的事」逐項相同 |

> 2026-10-22 稽核補記（migrate.py）：`--json` 印出的物件還會有上表沒列的值，這些情況都不寫 `migration.json`（沒有建立備份資料夾）：
> - `outcome`：`refused`（`both`、寫入鎖被占用、checkpoint 忙碌）、`dry-run`（`--dry-run`）、`already`（沒有要搬的檔案，只補做環境步驟）；
> - `files[].result`：`pending`（`old-only`、還沒搬）、`conflict`（`both`）；
> - `environment[].result`：`planned`（`--dry-run` 時會做的步驟）；
> - 讀不了設定檔中的資料夾設定時，整個物件只有 `{format, outcome: "refused", error}`。
>
> 例外：備份資料夾已建立、之後備份失敗（`failed_step = backup`）時，`migration.json` 會寫進那個資料夾，這時還沒搬的檔案的 `files[].result` 是 `pending`。
> 另外，`manual_steps` 第一項的程式字串是「版本應顯示 1.2.0 以上」，不是上例的「1.2.0」；擴充功能之後又升過版（現在的版本見 extension/manifest.json）。

不寫入：API 金鑰、環境變數、設定檔內容（願望清單網址含 Steam ID，不需要）。

## 3. 既有資料的變化

| 資料 | 變化 |
|---|---|
| 資料庫內容 | 無。只改檔名，搬家前後 SHA-256 相同 |
| 設定檔內容 | 無。只改檔名 |
| 擴充功能資料檔 | 搬家時只改檔名。下一次 `report` 起寫新檔名，`config_path` 指向 `sweetspot.toml` |
| 正式紀錄 `data/forecasts/` | 無。舊紀錄的格式名稱、`steamsage_version` 照舊；新紀錄也照舊用 `steamsage.decision/2` |
| 日誌 | 舊檔不動，新日誌寫 `sweetspot-YYYYMMDD.log` |
| 資料庫升級備份 | 下一次 schema 升級時才會產生 `sweetspot.db.bak-v7` |
