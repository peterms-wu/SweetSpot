# Contract: 名稱對照與保留的識別碼（016）

這份是改名（R1）、搬家（R4）、舊名稱保護（R7）與掃描（R10）的單一依據。程式中的對照表在 `src/sweetspot/legacy.py`，測試要確認它和這份一致。

## 1. 改名對照

| 類別 | 舊 | 新 | 誰處理 |
|---|---|---|---|
| Python 套件 | `steamsage`（`src/steamsage/`） | `sweetspot`（`src/sweetspot/`） | 改名（R1） |
| 套件發行名稱、指令 | `steamsage`（`pyproject.toml` 的 `name`、`[project.scripts]`） | `sweetspot` | 改名；`uv.lock` 重新產生 |
| argparse 的 `prog`、`--version` | `steamsage`、`steamsage 0.2.0` | `sweetspot`、`sweetspot 0.2.0` | 改名 |
| 本機程式模組 | `python -m steamsage.host` | `python -m sweetspot.host` | 改名；啟動檔由搬家重寫（R6） |
| 設定檔 | `steamsage.toml` | `sweetspot.toml` | 搬家 |
| 資料庫 | `data/steamsage.db`（及 `-wal`、`-shm`） | `data/sweetspot.db`（及 `-wal`、`-shm`） | 搬家 |
| 資料庫升級備份 | `data/steamsage.db.bak-v<N>` | `data/sweetspot.db.bak-v<N>` | 由檔名自動產生；舊的不搬 |
| 日誌 | `data/logs/steamsage-YYYYMMDD.log` | `data/logs/sweetspot-YYYYMMDD.log` | 改名；舊的不搬（2026-10-18 起日期改用本機日期，原本是 UTC 日期；見 README） |
| logger | `steamsage`、`steamsage.*` | `sweetspot`、`sweetspot.*` | 改名 |
| 擴充功能資料檔 | `extension/data/steamsage-extension.json` | `extension/data/sweetspot-extension.json` | 搬家；之後由 `report` 寫新名稱 |
| 擴充功能全域名稱 | `globalThis.SteamSage`、`self.steamsageRefresh` | `globalThis.SweetSpot`、`self.sweetspotRefresh` | 改名 |
| 頁面節點 class | `steamsage-panel`、`steamsage-line`、`steamsage-shortcut` | `sweetspot-panel`、`sweetspot-line`、`sweetspot-shortcut` | 改名 |
| 擴充功能版本 | `1.1.0` | `1.2.0` | 改名（R9）。（2026-10-22 稽核補記）之後又升過版（現在的版本見 extension/manifest.json）；搬家的提示寫「1.2.0 以上」（migrate.py） |
| 排程工作 | `SteamSage2 每日背景更新` | `SweetSpot 每日背景更新` | 搬家（R6） |
| 雲端備份 zip 內的檔名 | `data/steamsage.db`、`steamsage.toml` | `data/sweetspot.db`、`sweetspot.toml` | 改名；zip 檔名本來就是 `sweetspot-<tag>.zip` |

不在對照表上、本來就是新名稱的：
- 本機程式名稱 `com.sweetspot.edition`；
- 啟動檔 `data/host/sweetspot-host.bat`；
- 擴充功能的 manifest `key`（固定編號 `ecomigpdpdmcjbndhgiojplbaohkmhcm`）；
- 專案資料夾 `〈專案資料夾〉`。

## 2. 保留不改的識別碼（FR-006）

| 識別碼 | 比對規則 | 為什麼不改 |
|---|---|---|
| 輸出與紀錄的格式名稱 | `steamsage\.[a-z][a-z-]*/\d+`（例如 `steamsage.decision/2`、`steamsage.extension/1`、`steamsage.rule-backtest/1`） | 寫在只新增不修改的紀錄裡；舊紀錄要照常讀取和比較 |
| 004 的分組依據 | `steamsage-004-split` | 改了會改變調參組、驗證組與回測資料集識別碼（憲章 IV） |
| 紀錄欄位 | `steamsage_version` | 已保存的回測與事後對照結果都用這個欄位名 |

改寫工具（R1）先保護這三條規則的命中，再取代，最後還原。掃描（R10）把它們歸為「資料識別碼」。

## 3. 舊名稱的檔案狀態（搬家與保護共用）

每個要搬的檔案（設定檔、資料庫、擴充功能資料檔）在一個資料夾中的狀態：

| 狀態 | 舊名稱 | 新名稱 | 一般指令（R7） | 搬家（R4） |
|---|---|---|---|---|
| `old-only` | 有 | 無 | 設定檔或資料庫：拒絕，結束代碼 4；擴充功能資料檔：不影響 | 搬 |
| `new-only` | 無 | 有 | 照常 | 已搬，不動 |
| `both` | 有 | 有 | 使用新檔，stderr 提醒舊檔還在（FR-011） | 拒絕整個搬家，結束代碼 1 |
| `absent` | 無 | 無 | 照原本的行為（設定檔：建立預設；資料庫：寫入指令建立） | 不動 |

`absent` 是全新安裝（014 之後的新使用者）的情況，行為和改名前完全相同。

> 2026-10-18（feature 014）：`absent` 時不再建立預設設定檔，改由 `sweetspot setup` 詢問願望清單（014 contracts/cli.md）。另外，014 依它的 FR-006 把 `specs/` 與 `docs/` 裡的 SteamID、本機路徑換成代稱（〈專案資料夾〉等），這是本 feature「specs 歷史文件不改」的明確例外，只限這些值。

> 2026-10-22 稽核補記：資料庫 `old-only` 而且**沒有任何設定檔**（新舊都沒有）時，014 的 `setup.ensure` 先跑（cli.py）：背景執行（或不能互動）以 **5** 結束，不是 4；
> 互動執行會先問願望清單、建立 `sweetspot.toml`，之後才以 4 拒絕。使用者 2026-10-22 同意維持。
> 另外，直接執行 `sweetspot setup` 時，設定檔不存在就不檢查資料庫（`_old_database_refused` 只在設定檔存在時看），照常建立設定檔，不以 4 拒絕。
