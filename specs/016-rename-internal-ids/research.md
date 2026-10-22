# Research: 內部識別碼改名 steamsage → sweetspot（016）

日期：2026-10-15。每一項：決定、理由、考慮過的其他做法。標示「使用者選定」的是 2026-10-15 列出選項後由使用者決定的。

## 盤點時確認的前提（2026-10-15，程式與真實環境逐項讀過）

| 前提 | 實際狀況 | 影響 |
|---|---|---|
| 設定檔不存在時 | `load_config` 會用 `DEFAULT_TOML` **建立**新設定檔（`config.py`） | FR-010 的檢查必須在 `load_config` 之前 |
| 資料庫不存在時 | 寫入指令用 `sqlite3.connect` 會**建立**空資料庫；唯讀指令用 `mode=ro`，打不開但不建立 | 檢查必須在開啟 `StoreWriter` 之前 |
| 資料庫檔 | 真實 `data/steamsage.db` 206 MB，WAL 模式；`-wal` 0 位元組、`-shm` 32 KB | 搬家前先 checkpoint，連同 `-wal`／`-shm` 一起改名 |
| 升級備份 | `backup_before_migration` 用資料庫自己的檔名加 `.bak-v<N>` | 改 `db_path` 後自動變成 `sweetspot.db.bak-v<N>`，不需另外改；目前沒有舊的 bak 檔 |
| 寫入鎖 | `data/.lock`（`WriterLock`）；本機程式的指定版本先取 `data/.host.lock` 再取 `data/.lock` | 搬家只要取 `data/.lock` 就和背景更新、本機程式互斥 |
| `report` | 在 `READ_ONLY_COMMANDS`，**不取鎖**，但會開資料庫 | 搬家時 report 剛好開著資料庫 → Windows 上改名失敗 → 走回復（US2 情境 4） |
| 結束代碼 | 0 完成、1 整體失敗、2 部分問題、3 另一個更新正在執行（`cli.py`）；`report --update-exit` 只接受 0–3 | 新增 4；`--update-exit` 也要接受 4，否則 argparse 錯誤會以 **2** 結束，被誤認為「部分問題」 |
| 排程工作 | 「SteamSage2 每日背景更新」：`LogonType=Interactive`、`RunLevel=Limited`、`conhost.exe --headless cmd.exe /d /c "〈專案資料夾〉\背景更新.cmd"`、工作目錄 `〈專案資料夾〉`、`StartWhenAvailable=True`，上次結果 0 | 重建同一位使用者、一般權限的工作不需要系統管理員或密碼；工作內容只指向 `背景更新.cmd`，名稱裡的 `steamsage` 不影響執行 |
| 本機程式 | 啟動檔 `data/host/sweetspot-host.bat` 內容是 `"<python>" -m steamsage.host --config "<…\steamsage.toml>"`；登錄機碼名稱 `com.sweetspot.edition` 已是新名 | 合併後啟動檔同時指錯模組與設定檔，必須重寫；登錄機碼的值（清單檔路徑）不變 |
| 開發環境 | `uv run` 預設會先同步 `.venv` | 合併後第一次 `uv run sweetspot …` 會自動裝上新套件。**更正（2026-10-15 合併時實測）**：`uv run` 只補裝、不移除多出來的套件，舊的 `steamsage`（可編輯安裝與 `steamsage.exe`）會留在 `.venv`；要再執行一次 `uv sync`（嚴格同步）才會移除。另外 `src/steamsage/` 會留下被忽略的 `__pycache__`，要手動刪除。主資料夾在合併當下已處理 |
| 測試基準 | pytest 收集 1597 個、node 55 個（worktree，2026-10-15） | SC-001 的下限 |
| 改名前的盤點（016 T001） | `specs/` 以外、`git ls-files -z` 列出的檔案中，有 231 檔含 `steamsage`（不分大小寫），共 1366 處：`src` 76、`tests` 137、根目錄 7、`extension` 4、`scripts` 3、`docs` 2、`data` 1、`.specify` 1；另有 4 個二進位檔略過。依寫法分：`steamsage` 1321、`SteamSage` 22、`SteamSage2` 13、`steamsage_version` 6、`steamsageRefresh` 2、`_steamsage` 2 | spec 背景寫的「根目錄 5 檔」少算了兩個中文檔名的 `.cmd`：`git ls-files` 預設會把非 ASCII 路徑加引號跳脫，原本的盤點腳本因此開不了那兩個檔。掃描腳本（R10）必須用 `git ls-files -z` |

## R1 改名的做法

- **決定**：`git mv src/steamsage src/sweetspot`，再用一支一次性的改寫工具處理檔案內容。工具依序套用「保護 → 取代 → 還原」：先把 R2 的保留識別碼換成占位字串，再取代 `steamsage`／`SteamSage` 的各種寫法，最後還原占位字串。工具放在 `specs/016-rename-internal-ids/rename_tool.py`（specs 是歷史紀錄，掃描排除），只跑一次；結果由 R10 的掃描與全部測試驗證。`uv.lock` 由 `uv lock` 重新產生，不手改。
- **理由**：分布在 137 個測試檔、76 個原始碼檔，共 45 種寫法，手改一定會漏；用工具改，再用掃描和測試把關。保護清單先套用，保留的識別碼就不會被誤改。
- **考慮過**：用編輯器的全域取代，但保留識別碼會被一起改掉。另一種做法是保留 `steamsage` 當相容別名，但 spec 的 Assumptions 已經決定不保留。

## R2 保留不改的識別碼（FR-006）

- **決定**：下列三類照原樣保留，改寫工具與掃描都用同一組規則認它們。規則的正本寫在 `contracts/names.md`。
  - 格式名稱：`steamsage\.[a-z][a-z-]*/\d+`，例如 `steamsage.decision/2`、`steamsage.extension/1`。
  - 分組依據：`steamsage-004-split`（`forecast/backtest/split.py` 的 `SALT`）。
  - 紀錄欄位：`steamsage_version`。
- **理由**：格式名稱與欄位寫在已保存、只新增不修改的紀錄裡，舊紀錄要能照常讀。分組依據一改，調參組、驗證組與回測資料集識別碼都會變（憲章 IV）。
- **考慮過**：把格式名稱升成 `sweetspot.decision/3` 等新版本。這要所有讀取端同時認兩種名稱，比較時還要處理新舊混雜，而改名本身不改格式，沒有理由升版。

## R3 搬家的入口（使用者選定）

- **決定**：子指令 `uv run sweetspot migrate`，另有 `--dry-run`（只列出會做什麼）。它在 `cli.main` 裡**先於** FR-010 檢查與 `load_config` 處理，因為搬家前新名稱的設定檔還不存在。
- **理由**：直接沿用寫入鎖、日誌與結束代碼的機制；FR-010 的提示可以只寫一行指令。014 公開時再決定要不要拿掉這個指令。
- **用語**：程式裡的 `migrate`／`migration` 已用在「資料庫升級」，例如 `writer.migration`、`_migrate_to_v4`。中文文字一律區分：
  - 改名稱叫「搬家」；
  - schema 升級叫「資料庫升級」。

  模組 `sweetspot/migrate.py` 的說明第一行寫明「改名搬家（016），不是資料庫升級」。
- **考慮過**：獨立腳本 `scripts/migrate_names.py`。說明裡看不到它，用完就能刪；但鎖、日誌、結束代碼都要另外接，提示的指令也比較長。

## R4 搬家的步驟與回復（FR-008、FR-009、FR-009b）

- **決定**：一次搬家分成兩段。
  - **檔案段**：可回復，任一步失敗就改回。
  - **環境段**：盡力而為，失敗就轉成手動步驟。

  步驟：
  1. **判斷狀態**（不取鎖、不改檔）。主資料夾是 `--config` 的上一層。逐項判斷設定檔、資料庫、擴充功能資料檔的新舊狀態，`data_dir` 從舊設定檔讀（用 `tomllib` 只讀，不呼叫會建立檔案的 `load_config`）。每項狀態是下列之一：
     - `old-only`：要搬；
     - `new-only`：已搬；
     - `both`：衝突；
     - `absent`：兩邊都沒有（擴充功能資料檔可以不存在）。
     - 任一項是 `both` → 拒絕，結束代碼 1，不改任何檔案。
     - 檔案全是 `new-only`／`absent` → 檔案段「已經是新名稱」，只檢查環境段。
  2. **取寫入鎖** `data/.lock`。被占用時立即拒絕，結束代碼 3，不改任何檔案。
  3. **checkpoint**：開啟舊資料庫，執行 `PRAGMA wal_checkpoint(TRUNCATE)` 後關閉。checkpoint 回報忙碌（其他程式開著資料庫）→ 拒絕，結束代碼 1，不改任何檔案。
  4. **備份**（R5）。
  5. **記錄雜湊**：每個要搬的檔案記下 SHA-256 與大小。
  6. **改名**：依序處理資料庫（連同存在的 `-wal`、`-shm`）、設定檔、擴充功能資料檔。用 `os.rename`：Windows 上目標存在時會失敗，不會覆蓋；改名前另外確認目標不存在。
  7. **驗證**：新檔的 SHA-256 與大小都要和第 5 步相同。
  8. 第 6、7 步任一失敗 → 依相反順序把已改名的檔案改回，再驗證雜湊。報告失敗原因、停在哪一步、目前每個檔案的名稱。結束代碼 1。
  9. **釋放鎖**，寫 `migration.json`（data-model §2）。
  10. **環境段**（R6）：本機程式、排程工作。每一步獨立成功或失敗，失敗就列為手動步驟，結束代碼 2。
  11. 結束時逐項列出手動步驟（R6），結束代碼 0；有環境步驟失敗時為 2。
- **為什麼要分段**：檔案段是使用者資料，必須「全有或全無」。環境段失敗時不會讓每日更新消失，因為舊排程工作執行的是同一個 `背景更新.cmd`，而它已經用新名稱。所以環境段不回復檔案段，只轉成手動步驟。
- **為什麼要先 checkpoint**：資料庫的內容都寫回主檔，`-wal` 變成 0 位元組，改名後主檔的雜湊就代表全部內容。連同 `-wal`／`-shm` 一起改名，是為了不刪任何檔案。
- **考慮過**：
  - 環境段失敗也回復檔案段。這會讓「排程工作改名失敗」這種不影響資料的問題，把已經成功的搬家退回去，而且退回後新程式又會因 FR-010 拒絕執行，反而比較糟。
  - 用複製代替改名。206 MB 要寫兩次，又要另外決定什麼時候刪舊檔。

## R5 搬家前的備份（使用者選定）

- **決定**：在 `data/pre-016-backup-<YYYYMMDD-HHMMSS>/` 各複製一份：
  - `steamsage.toml`；
  - `steamsage.db`：用 SQLite 備份 API 取一致的副本，再對副本跑 `PRAGMA quick_check`；
  - `steamsage-extension.json`：如果存在。

  檔名保持舊名，說明這是搬家前的狀態。`migration.json` 也寫在這個資料夾。資料夾名稱帶時間，搬家失敗後重跑不會撞到上一次的備份。`.gitignore` 加 `data/pre-016-backup-*/`。驗收後由使用者刪除，和 015 的 `steamsage.toml.before-015` 一樣。
- **理由**：萬一改回的程式本身有錯，還有一份完整副本可以手動還原。206 MB 的複製和 quick_check 都只要幾秒，符合 SC-003（1 分鐘內）。
- **考慮過**：只改名、用雜湊證明內容沒變。這樣省下 206 MB，但只能依賴改回的程式沒寫錯，以及每晚的雲端備份。

## R6 環境段（FR-009a；排程工作的做法由使用者選定）

只處理**指向這個主資料夾**的登記。在副本或測試環境搬家時，永遠不會改到真實的排程工作或 Chrome 登記。

- **本機程式**：用 `host.install.status` 讀登錄機碼。如果登記的清單檔就是這個資料夾的 `data/host/com.sweetspot.edition.json`，而且啟動檔內容含 `-m steamsage.host`，就用新設定重新執行 `install`。這會重寫啟動檔與清單檔，登錄機碼的值不變。Python 路徑是執行 `uv run sweetspot migrate` 的 `.venv` Python。沒登記或登記到別的資料夾 → 略過並說明。
- **排程工作（使用者選定：自動）**：做法如下，以 `powershell.exe -NoProfile -NonInteractive -EncodedCommand` 執行（UTF-16LE base64，中文工作名稱不經過字碼頁）。
  1. 找舊工作「SteamSage2 每日背景更新」，確認動作的工作目錄或 `背景更新.cmd` 路徑在這個資料夾裡。
  2. 用 `Export-ScheduledTask` 取得 XML。
  3. 把 `<URI>` 換成新名稱。
  4. 以 `Register-ScheduledTask -TaskName "SweetSpot 每日背景更新" -Xml` 建立新工作。
  5. 讀回新工作，確認觸發時間、動作、工作目錄、`StartWhenAvailable`、執行身分與舊的相同。
  6. 都相同才 `Unregister-ScheduledTask` 舊工作。

  任一步失敗就保留舊工作；如果新工作已建立但驗證不符，就刪掉新工作，並列出手動指令。新工作已存在、舊的不存在 → 已完成。執行器可以注入，測試只用假的執行器。

  **新舊工作名稱也可以由參數指定**，預設是對照表的兩個名稱。這樣就能在合併前，用一個暫時的測試工作驗證一次真正的工作排程器，不碰真正的每日工作（2026-10-15 analyze C3，使用者同意）。做法：
  1. 建立「SweetSpot 搬家測試（舊）」：
     - 動作是在 worktree 資料夾執行一支只寫一行文字的 .cmd；
     - 觸發時間設在很久以後，不會真的執行；
     - 其餘設定比照真實工作，包括 `conhost.exe --headless`、`StartWhenAvailable`、`Interactive`、`Limited`。
  2. 以測試名稱呼叫排程工作步驟，把它改名為「SweetSpot 搬家測試（新）」。
  3. 確認舊的已刪除、新的設定相同、`<URI>` 為新名稱。
  4. 刪除新的。

  真實的「SteamSage2 每日背景更新」全程不動，前後讀一次確認沒變。
- **Chrome 擴充功能**：一律手動。到 `chrome://extensions` 對 SweetSpot 按「重新載入」，和 015 相同，程式無法代勞。
- **開發環境**：不列步驟。`uv run` 會自動同步（見前提表）。搬家的說明只提一句「第一次執行會花幾秒同步」。
- **擴充功能資料檔裡的 `config_path`**：改名不改內容，所以裡面仍是舊的設定檔路徑，只在「還沒安裝本機程式」的說明文字中出現。下一次 `report` 會自動更新；手動步驟提示「可以現在執行 更新資料.cmd 立即更新，或等 02:30」。
- **考慮過**：搬家結束時自動執行 `report`。這會在使用者沒預期的時候多寫一份正式紀錄並前進比較基準，所以不做。

## R7 舊名稱的保護（FR-010、FR-011）

- **決定**：
  - 新模組 `src/sweetspot/legacy.py`，放名稱對照表（contracts/names.md）與兩個函式。`cli.main`、`migrate`、`scripts/backup_db.py` 共用它。
    - `config_blocker(config_path)`：設定檔不存在，而同資料夾有 `steamsage.toml`。
    - `db_blocker(config)`：`config.db_path` 不存在，而 `data_dir/steamsage.db` 存在。
  - `cli.main` 的順序：
    1. 解析參數（`--help`、`--version` 在這裡就結束）；
    2. `migrate` → 交給搬家；
    3. `config_blocker` → 拒絕；
    4. `load_config`；
    5. `db_blocker` → 拒絕；
    6. 新舊並存的提醒（FR-011：設定檔、資料庫、擴充功能資料檔，各一行警告，不刪不合併）；
    7. 原本的流程。
  - 拒絕時在 stderr 印出：「找到舊名稱的檔案（<檔名>），請先執行搬家：uv run sweetspot migrate」。結束代碼 **4**（`EXIT_NEEDS_MIGRATION`），不建立任何檔案，日誌資料夾也不建。
  - 背景更新的原因由 `背景更新.cmd` 把 stderr 寫進 `data\logs\background-update.log`，結束行顯示 `update 4`。
  - `.cmd` 的整體結束代碼優先順序改為 1 > 4 > 3 > 2 > 0。`更新資料.cmd` 遇到 4 時印出搬家提示。
  - `report --update-exit` 的選項加上 4。report 本身遇到舊名稱也會先以 4 拒絕，所以 4 只是不讓 argparse 以 2 結束。
  - `scripts/backup_db.py` 在只有舊名稱時印出相同提示並以 4 結束，不上傳任何東西。
- **理由**：
  - 使用者選了「拒絕並提示」（spec Clarifications）。
  - 檢查放在「會建立檔案的那一行」之前，是唯一能保證不建立空檔的位置。
  - 4 和現有的 0–3 都不同，`.cmd` 與日誌一看就知道原因。
  - 4 排在 1 之後，因為 1 代表真的失敗；排在 3 之前，因為 3 只是撞到另一個更新，下一次就會好，4 不處理就每晚都失敗。
- **考慮過**：用 1 表示需要搬家。這和「整體失敗」混在一起，背景更新的結束行看不出原因。
- **涵蓋所有指令**：測試從 `build_parser()` 列舉所有子指令（不手挑），每個子指令配一組最小參數，在只有舊名稱的暫存資料夾執行，確認：
  - 結束代碼為 4；
  - 沒有出現新檔；
  - 舊檔雜湊不變。

  另有一個測試確認「最小參數表」涵蓋了 `build_parser()` 列出的每一個子指令（`migrate` 除外）。

## R8 日誌與 logger

- **決定**：
  - 日誌檔改為 `data/logs/sweetspot-YYYYMMDD.log`。
  - logger 名稱 `steamsage` → `sweetspot`。各模組用 `logging.getLogger(__name__)`，套件改名後會自動跟著變；`getLogger("steamsage.host")` 等寫死的名稱由 R1 一併改。
  - handler 的標記屬性 `_steamsage` → `_sweetspot`。
  - 舊日誌檔不改名、不刪（spec Edge Cases）。
- **理由**：日誌是歷史紀錄；保留原名，看得出是哪個時期寫的。

## R9 擴充功能

- **決定**：
  - 全域名稱 `SteamSage` → `SweetSpot`（`lib.js`、`content.js`、`popup.js`、`sw.js`）。
  - 頁面節點的 class 改為 `sweetspot-panel`、`sweetspot-line`、`sweetspot-shortcut`。
  - `self.steamsageRefresh` → `self.sweetspotRefresh`。
  - 資料檔改為 `data/sweetspot-extension.json`（`sw.js` 的 `DATA_URL`、`commands.py` 的輸出路徑）。
  - `INSTALL_COMMAND` 與說明文字改為新指令和新設定檔名。
  - 格式名稱 `steamsage.extension/1` 不變（R2）。
  - `manifest.json` 的 `version` 1.1.0 → **1.2.0**：使用者在 `chrome://extensions` 看得出重新載入是否生效。`key`（固定編號）不變。
- **合併後、重新載入前**：Chrome 仍執行舊程式，讀的是 `data/steamsage-extension.json`，而搬家會把它改名，所以面板暫時不顯示。這是 011 已有的「讀不到資料檔」行為，重新載入後恢復。這在搬家的手動步驟中說明。

## R10 掃描與例外清單（FR-013、FR-014）

- **決定**：
  - `scripts/scan_names.py` 讀 `git ls-files` 的每個文字檔，逐行找 `steamsage`（不分大小寫）。
  - 每一處依 `contracts/scan.md` 的規則表歸到一個例外類別，或者「未允許」。
  - 結果：
    - 有「未允許」就列出 `檔案:行號: 內容`，並以 1 結束；
    - 否則印出各類別的出現次數（當場用程式數），以 0 結束。
  - `--write` 依規則表與掃描結果重新產生 `docs/legacy-names.md`：
    - 每個類別附理由與檔案清單；
    - 整個路徑都是例外的類別（`specs/`、`HANDOFF.md`）不逐檔列出；
    - 不寫次數，避免每次加測試都要重新產生。
  - 測試 `tests/unit/test_scan_names.py`：
    1. repo 中「未允許」為 0；
    2. `docs/legacy-names.md` 與重新產生的內容相同；
    3. 暫存清單中故意放一個 `steamsage`，能找到檔案與行號；
    4. 每條例外規則都有「該命中」與「不該命中」的凍結樣本。
- **理由**：
  - 全域守則要求「共 N 個」當場數，登記表由列舉產生。
  - 只凍結命中句，證明不了誤判那一側，所以每條規則要正反樣本都有。
  - 例如「前身專案」規則必須認得 `〈前身專案資料夾〉\state\cache`，但不能放過殘留的 `globalThis.SteamSage`。
- **考慮過**：手寫例外清單。違反 FR-014，而且之後一定會和實際情況不一致。

## R11 改名前後結果相同（FR-007、SC-002）

- **決定**：在真實資料的暫存副本上驗證。
  1. 用主資料夾（master，舊程式）對副本執行 `steamsage report --config <副本>\steamsage.toml`，產生正式紀錄 A 與擴充功能資料檔 A。
  2. 用新程式對副本執行 `sweetspot migrate`。這個副本不是排程工作或本機程式登記的資料夾，所以環境段會略過（R6）。
  3. 用新程式執行 `sweetspot report --config <副本>\sweetspot.toml`，產生紀錄 B 與資料檔 B。
  4. 用比對腳本比較：
     - 69 款的決策、格式名稱、規則版本逐款相同；
     - 資料檔除了 `generated_at` 與 `config_path` 以外相同；
     - 回測資料集識別碼用 `backtest-rule --cutoff 2026-09-25 --apps-limit` 前後各跑一次比對。

  步驟寫在 quickstart。
- **理由**：自動測試只能證明我寫的樣本相同。真實資料的副本才能證明 69 款都一樣，而且不碰真實的設定檔、資料庫與登錄。

## R12 文件

- **決定**：
  - README：指令改新名稱；新增「舊名稱」一節，說明 `steamsage`、`SteamSage2` 與保留的資料識別碼，連到 `docs/legacy-names.md`；新增「從改名前的雲端備份還原」（FR-012：zip 內是 `data/steamsage.db`、`steamsage.toml`，解開後執行 `sweetspot migrate`）。
  - HANDOFF：操作步驟改新名稱，歷史段落不改。
  - `docs/model/model-definition.md`：活文件，程式路徑改新名稱。
  - `docs/model/comparisons.md`：只附加，不改，列為例外。
  - 憲章：只有「舊名 SteamSage2」與前身專案 SteamSage 兩種寫法，屬於例外類別，不需要修訂。
- **理由**：spec FR-005、FR-012；comparisons.md 的「只附加、不修改」是 003 以來的規則。
