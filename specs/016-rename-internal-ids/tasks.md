---

description: "Task list for 016 rename internal ids steamsage → sweetspot"
---

# Tasks: 內部識別碼改名 steamsage → sweetspot

**Input**: Design documents from `specs/016-rename-internal-ids/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/（names.md、migrate.md、scan.md）, quickstart.md

**Tests**: 憲章「測試先行」與 spec 的 Independent Test 都要求測試。搬家、舊名稱保護、掃描的測試先寫，並確認失敗後才實作。

**Organization**: 依 user story 分組。機械式改名（git mv、改寫工具）是所有 story 的前提，放在 Phase 2。

**工作位置**：worktree `〈專案資料夾〉-016`（分支 `016-rename-internal-ids`）。主資料夾 `〈專案資料夾〉` 留在 master，給每日背景更新與 Chrome 用，到 Phase 8 之前都不動。

## Format: `[ID] [P?] [Story] Description`

- **[P]**：可平行，因為改的是不同檔案、彼此沒有相依。
- **[Story]**：所屬 user story（US1–US4）。
- 引用時一律帶 spec 號，例如 `016 T012`。

## 共同規則（每個 task 都適用）

- 測試不得碰真實的 `steamsage.toml`、`data/steamsage.db`、HKCU 登錄、工作排程器。
  - 一律用 `tmp_path`、假的登錄（`tests/host_builders.py` 既有的做法）、可注入的 PowerShell 執行器。
- 含 CJK 或反斜線的一次性腳本寫到 scratchpad，以 `PYTHONUTF8=1` 執行；不用 heredoc、`python -`、`python -c`。
- commit 訊息寫成檔案，以 `git commit -F` 提交，結尾加 attribution 兩行。
- 偏離本清單或 plan 時先停下說明。

---

## Phase 1: Setup（改名前的基準）

**Purpose**：記下改名前的狀態，作為 SC-001、SC-005 與改寫工具的比對基準。

- [X] T001 記錄改名前的測試數量與盤點：在 worktree 執行 `uv run pytest --collect-only -q`（各檔數量加總，預期 1597）與 `node --test tests/extension/`（預期 55）。用 scratchpad 的盤點腳本（`inventory_rename.py` 的做法，改成讀 worktree）重跑一次，得到 `specs/` 以外各寫法的次數與檔案數。結果寫進 `specs/016-rename-internal-ids/research.md` 開頭的前提表，作為「改名前」一列。
- [X] T002 寫一次性改寫工具 `specs/016-rename-internal-ids/rename_tool.py`（research R1、contracts/names.md）：
  - **處理範圍**：`git ls-files` 中，排除以下路徑：`specs/`、`HANDOFF.md`、`docs/model/comparisons.md`、`.gitignore`、`.specify/`、`uv.lock`。
  - **保護**：
    - contracts/names.md §2 的三條規則：`steamsage\.[a-z][a-z-]*/\d+`、`steamsage-004-split`、`steamsage_version`；
    - 前身專案：大小寫相同的 `SteamSage`、後面不是 `2`，而且該行含 前身／舊專案／legacy，或後面緊接 `\` 或 `/`；
    - 含「舊名」或「formerly」的整行。
  - **取代**（依序）：
    1. `SteamSage2 每日背景更新` → `SweetSpot 每日背景更新`；
    2. `steamsageRefresh` → `sweetspotRefresh`；
    3. `SteamSage`（JS 全域等）→ `SweetSpot`；
    4. `steamsage` → `sweetspot`。
  - 取代後還原保護的內容。
  - **輸出**：每個檔案的取代次數與保護次數；`--dry-run` 只印不寫。
  - 讀寫一律 UTF-8，保留原本的換行（CRLF／LF）。

  先用 `--dry-run` 看結果，人工抽查至少以下幾處：
  - `config.py` 的 `[legacy] cache_path`（應保護）；
  - `split.py` 的 `SALT`（應保護）；
  - `lib.js` 的 `FORMAT`（應保護）；
  - `README.md` 的 `import-legacy` 那一行（`steamsage` 改、`舊專案 SteamSage` 保護）。

---

## Phase 2: Foundational（機械式改名與共用的名稱對照）

**Purpose**：所有 story 的前提。完成後程式只叫 `sweetspot`，全部既有測試照常通過。

**⚠️ CRITICAL**：這個 phase 完成前不開始任何 story。

- [X] T003 `git mv src/steamsage src/sweetspot`。執行 T002 的工具（非 dry-run），範圍就是 T002 定義的範圍（`git ls-files` 減去排除清單）。主要會改到 `src/`、`tests/`、`scripts/`、`extension/`、`README.md`、`pyproject.toml`、`data/steam_sales.toml`、`docs/model/model-definition.md`、`更新資料.cmd`、`背景更新.cmd`；這份清單只是舉例，不是範圍本身。`pyproject.toml` 確認以下三處改成 `sweetspot`：
  - `name = "sweetspot"`；
  - `[project.scripts] sweetspot = "sweetspot.cli:main"`；
  - `packages = ["src/sweetspot"]`。

  之後執行 `uv lock`，再 `uv sync`。
- [X] T004 人工檢查 T003 的 diff。項目如下：
  - `git diff --stat` 沒有出現 `specs/`、`HANDOFF.md`、`comparisons.md`；
  - `git grep -n "steamsage"` 在處理範圍內只剩保護的三類與前身專案；
  - `extension/lib.js` 的 `FORMAT = 'steamsage.extension/1'` 不變；
  - `forecast/backtest/split.py` 的 `SALT = "steamsage-004-split"` 不變；
  - 各 `steamsage_version` 欄位不變；
  - `logs.py` 寫 `sweetspot-{日期}.log`、logger 名稱為 `sweetspot`、handler 標記為 `_sweetspot`；
  - `config.py` 的 `db_path` 為 `sweetspot.db`；
  - `commands.py` 的擴充功能資料檔為 `data/sweetspot-extension.json`；
  - `host/install.py` 的啟動檔內容為 `-m sweetspot.host`；
  - 資料庫升級備份由 `db_path` 產生，預期為 `sweetspot.db.bak-v<N>`。在既有的升級備份測試確認這個檔名，用 `git grep -n "bak-v" -- tests` 找出測試（FR-002）；
  - 逐一人工看過工具因「含『舊名』或『formerly』」而整行保護的每一行（工具會列出），確認同一行沒有該改的操作指令或檔名。

  有誤就修正工具重跑，不手補。
- [X] T005 執行 `uv run pytest`、`node --test tests/extension/`、`uv run python tests/extension/e2e.py`。全部通過，pytest 不少於 1597、node 不少於 55（SC-001）。失敗時只修改名造成的問題，不改行為。
- [X] T006 更新 `.gitignore`（contracts/names.md、research R5）：
  - 加入 `data/sweetspot.db*`、`sweetspot.toml`、`data/pre-016-backup-*/`；
  - **保留** `data/steamsage.db*`、`steamsage.toml`；
  - 加一行註解說明：舊名稱保留，是為了搬家前後都不會誤加進版控。

  用 `git check-ignore -v` 對新舊名稱、備份資料夾各確認一次。
- [X] T007 commit「rename: package, CLI, files and extension ids steamsage -> sweetspot (016 T003–T006)」。
- [X] T008 [P] 先寫名稱對照與狀態判斷的測試 `tests/unit/test_legacy_names.py`（data-model §1、contracts/names.md §3），確認它們失敗：
  - 對照表三項（`config`、`db`、`extension_data`）的 `old`、`new`、`base`、`companions`、`blocks` 和 data-model §1 一致；
  - 排程工作新舊名稱、舊模組 `steamsage.host` 常數；
  - 在 `tmp_path` 建立四種組合，`state()` 分別回傳 `old-only`、`new-only`、`both`、`absent`；
  - `data_dir` 從舊設定檔以 `tomllib` 讀取（含 `[storage] data_dir` 為絕對路徑與相對路徑兩種），讀取後設定檔內容與修改時間不變，也沒有建立任何新檔。
- [X] T009 實作 `src/sweetspot/legacy.py`，讓 T008 通過：
  - 名稱對照常數；
  - `state(base, old, new)`；
  - `read_data_dir(folder)`：讀新或舊設定檔的 `[storage] data_dir`，都沒有則為 `data`，不呼叫 `load_config`；
  - `items(folder)`：回傳每項的完整新舊路徑與狀態。

  只依賴標準函式庫與 `sweetspot.config` 的常數，不 import `cli`。

**Checkpoint**：程式改名完成、全部測試通過；`legacy.py` 可供 US2、US3 使用。

---

## Phase 3: User Story 1 - 程式與指令都叫 sweetspot（Priority: P1）🎯 MVP

**Goal**：使用者看得到的名稱都是新名稱，行為與數字和改名前相同（FR-001–FR-007）。

**Independent Test**：
- 用新名稱執行每個指令；
- 全部測試通過；
- 同一份資料改名前後的報告、正式紀錄、擴充功能資料檔，除了產生時間與路徑以外相同。

### Tests for User Story 1

- [X] T010 [P] [US1] 在 `tests/contract/test_cli_contract.py` 加測試，確認說明文字都是新名稱（US1 情境 1）：
  - 從 `build_parser()` 列舉所有子指令，逐一取得 `format_help()`；
  - 每一份都不含 `steamsage`，contracts/names.md §2 的格式名稱除外，例如 `forecast --out` 說明中的 `steamsage.forecast/1`；
  - `prog` 為 `sweetspot`；
  - `--version` 印出 `sweetspot 0.2.0`。
- [X] T011 [P] [US1] 在 `tests/extension/manifest.test.js` 確認 `version` 為 `1.2.0`、`key` 不變。在 `tests/extension/static.test.js` 確認：
  - `sw.js` 的資料檔 URL 為 `data/sweetspot-extension.json`；
  - 頁面節點 class 只用 `sweetspot-`；
  - 擴充功能檔案中除了 `steamsage.extension/1` 以外沒有 `steamsage`／`SteamSage`。
- [X] T012 [P] [US1] 在既有的日誌測試加上：檔名為 `sweetspot-YYYYMMDD.log`、logger 名稱為 `sweetspot`。日誌測試用 `git grep -l setup_logging -- tests` 找出。
- [X] T013 [P] [US1] 在既有的報告與擴充功能資料檔測試（`tests/contract/test_extension_contract.py`）確認以下兩點，並確認舊格式名稱的紀錄照常被讀取為比較基準（US1 情境 3）：
  - 輸出路徑為 `extension/data/sweetspot-extension.json`；
  - 格式仍為 `steamsage.extension/1`。

  紀錄讀取若既有測試已涵蓋，就在 task 中註明是哪一個測試。

### Implementation for User Story 1

- [X] T014 [US1] `extension/manifest.json` 的 `version` 改為 `1.2.0`（research R9），讓 T011 通過。T010、T012、T013 若失敗，修正對應的程式（`cli.py`、`logs.py`、`commands.py`）。
- [X] T015 [P] [US1] `README.md`（FR-005）：
  - 確認操作步驟中的指令、檔名、排程工作名稱都是新名稱；
  - 新增「舊名稱」一節：`steamsage`、`SteamSage2` 是什麼；保留的資料識別碼與理由（contracts/names.md §2）；連到 `docs/legacy-names.md`。該節每行都要含「舊名」，掃描規則 8 才會放行（contracts/scan.md）。
- [X] T016 [P] [US1] `docs/model/model-definition.md`：
  - 確認程式路徑為 `src/sweetspot/…`；
  - 指令為 `sweetspot …`；
  - 設定檔為 `sweetspot.toml`。

  `docs/model/comparisons.md` 不改（只附加）。
- [X] T017 [US1] 執行 `uv run pytest`、`node --test tests/extension/`，全部通過後 commit「016 US1: help texts, extension 1.2.0, docs」。

**Checkpoint**：US1 可獨立驗證。全新資料夾（`absent`）中，`uv run sweetspot update` 的行為和改名前相同。

---

## Phase 4: User Story 2 - 一次把現有環境搬到新名稱（Priority: P1）

**Goal**：`sweetspot migrate` 把現有檔案搬到新名稱，並處理本機程式與排程工作（FR-008、FR-009、FR-009a、FR-009b、FR-015）。

**Independent Test**：
- 在副本上搬家後，`update`、`report` 正常；
- 檔案逐位元組相同；
- 任一步模擬失敗，副本回到搬家前的樣子。

### Tests for User Story 2（先寫，確認失敗）

- [X] T018 [P] [US2] 檔案段的整合測試 `tests/integration/test_migrate.py`（research R4、R5，data-model §2）。在 `tmp_path` 建立舊名稱的設定檔（`[storage] data_dir = "data"`）、WAL 模式的資料庫（含一筆資料，開著寫入後關閉，讓 `-wal`／`-shm` 存在）、擴充功能資料檔，然後確認：
  - (a) 搬家後三個檔案改成新名稱，SHA-256 與大小和搬家前相同；舊名稱的檔案不存在；`-wal`／`-shm` 若存在則跟著改名。
  - (b) `data/pre-016-backup-<YYYYMMDD-HHMMSS>/` 有 `steamsage.toml`、`steamsage.db`、`steamsage-extension.json`；資料庫副本 `PRAGMA quick_check` 為 ok，且內容和原資料庫相同（逐表比對列數與資料）。
  - (c) `migration.json` 的欄位與 data-model §2 一致：
    - `format` 為 `sweetspot.migration/1`；
    - `outcome` 為 `migrated`；
    - `files[].result` 為 `moved`；
    - `files[].sha256`、`files[].bytes` 正確；
    - `backup.files[].check` 為 `ok`／`copied`。
  - (d) 再搬一次：輸出「已經是新名稱」，結束代碼 0，不建立新的備份資料夾、不寫 `migration.json`，所有檔案的雜湊與修改時間不變（FR-009b）。
  - (e) 新舊並存（任一項 `both`）：結束代碼 1，沒有建立備份資料夾，所有檔案不變。
  - (f) 寫入鎖被占用（用一個存活的 PID 預先寫 `data/.lock`，比照既有的 lock 測試）：結束代碼 3，什麼都沒改。
  - (g) checkpoint 忙碌：注入一個回報忙碌的 checkpoint，或另開連線持有讀取交易。預期結束代碼 1，什麼都沒改。
  - (h) 模擬改名失敗：分別讓資料庫、設定檔、擴充功能資料檔的改名丟出 `PermissionError`（monkeypatch 搬家模組使用的改名函式，只對指定目標失敗）。每一種都要結束代碼 1，`failed_step` 為 `rename`，所有原檔案的清單與雜湊和搬家前相同（備份資料夾除外）。
  - (i) 模擬驗證失敗：改名後竄改雜湊計算結果。預期 `failed_step` 為 `verify`，並已改回。
  - (j) `--dry-run`：印出計畫，結束代碼 0，所有檔案的清單、雜湊、修改時間不變，沒有建立鎖檔、備份資料夾、日誌檔或日誌資料夾（contracts/migrate.md §1）。
  - (h)、(i) 的「搬家前的樣子」指原有檔案；搬家建立的備份資料夾與當天日誌除外（spec SC-003）。
  - (k) 擴充功能資料檔不存在（`absent`）時照常搬其餘兩項。
- [X] T019 [P] [US2] 環境段的整合測試，加在 `tests/integration/test_migrate.py`（research R6）：
  - **本機程式**（用假的登錄）：
    - 登記到這個資料夾、啟動檔含 `-m steamsage.host` → 重寫為 `-m sweetspot.host --config "<…\sweetspot.toml>"`，結果 `done`；
    - 沒有登記、或登記到別的資料夾 → `skipped`，啟動檔不變；
    - 已是新模組 → `already`。
  - **排程工作**（用假的 PowerShell 執行器，記錄收到的指令；執行器收到的是 `-EncodedCommand` 的 UTF-16LE base64，解碼後確認中文工作名稱正確）：
    - 舊工作的工作目錄是這個資料夾 → 依序匯出、建立新工作、讀回驗證、刪除舊工作，結果 `done`；
    - 建立失敗 → 不刪舊工作，結果 `failed`，手動步驟含三行 PowerShell；
    - 讀回後設定不符 → 刪除新工作、保留舊工作，結果 `failed`；
    - 舊工作指向別的資料夾 → `skipped`，不呼叫任何寫入指令；
    - 只有新工作 → `already`。
  - 任一環境步驟 `failed` 時結束代碼 2，檔案段的結果不受影響。
  - 測試全程不得呼叫真的 `powershell.exe`：在 conftest 加 autouse fixture，讓真執行器一被呼叫就失敗。
- [X] T020 [P] [US2] CLI 契約測試 `tests/contract/test_cli_migrate.py`（contracts/migrate.md §1–§3）：
  - `uv run sweetspot migrate --help` 列出 `--dry-run`、`--json`；
  - 一般輸出依序含以下四段：檔案結果、備份路徑、環境步驟結果、「接下來要你做的事」。
  - 「接下來要你做的事」一律含三項：
    - Chrome 重新載入（1.2.0），並說明重新載入前面板與願望清單那一行會暫時不顯示；
    - 面板路徑在下一次報告後更新；
    - 驗收後可刪除備份資料夾（完整路徑）。
  - `--json` 的欄位與 `migration.json` 相同；
  - 結束代碼 0／1／2／3 各一例；
  - 搬家當天的 `data/logs/sweetspot-YYYYMMDD.log` 有每一步的紀錄。
  - 用假的 `ITAD_API_KEY`、`STEAM_WEB_API_KEY` 環境變數執行，輸出、`migration.json`、日誌都不含其值，只檢查布林結果（FR-015、SC-007）。

### Implementation for User Story 2

- [X] T021 [US2] 實作 `src/sweetspot/migrate.py` 的檔案段（research R4 步驟 1–9、R5，data-model §2），讓 T018 通過：
  - **判斷狀態**：用 `legacy.items`；
  - **鎖**：`WriterLock(data_dir / ".lock")`；
  - **checkpoint**：`PRAGMA wal_checkpoint(TRUNCATE)`，忙碌就拒絕；
  - **備份**：
    - 資料庫用 `sqlite3` 備份 API 複製，再跑 `quick_check`；
    - 設定檔、擴充功能資料檔用 `shutil.copy2`；
  - **雜湊**：SHA-256 分塊讀取；
  - **改名**：`os.rename`，改名前確認目標不存在，失敗時依相反順序改回並重新驗證雜湊；
  - **紀錄**：寫 `migration.json`，每一步寫進日誌；
  - **呼叫介面**：`run(folder, *, dry_run, rename=os.rename, checkpoint=…, now=…)`，改名函式與時間可注入。
- [X] T022 [US2] 實作 `src/sweetspot/migrate.py` 的環境段（research R6），讓 T019 通過：
  - **本機程式**：用 `host.install.status` 判斷，再以新設定重新執行 `host.install.install`。
  - **排程工作**：
    - 腳本以 `powershell.exe -NoProfile -NonInteractive -EncodedCommand` 執行；
    - 步驟為 `Export-ScheduledTask`、替換 `<URI>`、`Register-ScheduledTask -Xml`、讀回比對、`Unregister-ScheduledTask -Confirm:$false`；
    - 讀回比對的項目：觸發時間、動作、工作目錄、`StartWhenAvailable`、`LogonType`、`RunLevel`；
    - 執行器可注入，預設才是真的 PowerShell；
    - 新舊工作名稱可由參數指定，預設是對照表的兩個名稱。016 T045 用測試工作名稱驗證真正的工作排程器（research R6）；
    - 失敗時產生手動指令。
  - 模組說明第一行寫明「改名搬家（016），不是資料庫升級」（research R3 用語）。
  - **手動步驟清單**：依 contracts/migrate.md §3 產生。
  - 環境段在釋放鎖、寫完第一次 `migration.json` 之後執行，結束後覆寫 `migration.json`。
- [X] T023 [US2] 在 `src/sweetspot/cli.py` 加 `migrate` 子指令。它只用 common 參數 `--config`、`--json`，另加 `--dry-run`。`main()` 在解析參數後、任何 `load_config` 之前，就把 `migrate` 交給 `migrate.run`（research R3、R7），並在 `READ_ONLY_COMMANDS`／`WRITE_COMMANDS` 的註解說明它自己處理鎖。輸出格式依 contracts/migrate.md §3，讓 T020 通過。
- [X] T024 [US2] 執行 `uv run pytest`，全部通過後 commit「016 US2: sweetspot migrate (files, host, scheduled task)」。

**Checkpoint**：在 `tmp_path` 的副本上可以完整搬家、改回、重跑；不碰真實環境。

---

## Phase 5: User Story 3 - 只有舊名稱的檔案時不會默默開新檔（Priority: P2）

**Goal**：只有舊名稱時，每個指令都以 4 拒絕，不建立任何檔案；新舊並存時提醒（FR-010、FR-011、FR-012）。

**Independent Test**：在只有舊名稱的暫存資料夾執行每個子指令，結果都要相同：
- 結束代碼 4；
- 沒有新檔案；
- 舊檔雜湊不變。

### Tests for User Story 3（先寫，確認失敗）

- [X] T025 [P] [US3] 契約測試 `tests/contract/test_cli_migrate_guard.py`（contracts/migrate.md §4，research R7）：
  - **最小參數表**：每個子指令一組最小參數，`compare`、`compare-rule` 等需要的位置參數指向 `tmp_path` 中的假檔。另有一個測試確認這張表的鍵剛好等於 `build_parser()` 列舉出的子指令減去 `migrate`，表由列舉檢查，不手挑。
  - **只有 `steamsage.toml`**：每個子指令都是：
    - 結束代碼 4；
    - stderr 含「請先執行搬家：uv run sweetspot migrate」；
    - 沒有 `sweetspot.toml`、`data/sweetspot.db`、`data/logs/`；
    - 舊檔雜湊不變。
  - **有 `sweetspot.toml`、但只有 `data/steamsage.db`**：同上，而且沒有 `data/sweetspot.db`、`data/.lock`。
  - **新舊並存**：照常執行，stderr 每個並存的檔案一行警告（FR-011），舊檔不被刪改。
  - **全新資料夾（`absent`）**：`update` 照原本行為建立預設設定檔，維持改名前的行為。
  - `--help`、`--version` 不受影響。
- [X] T026 [P] [US3] 在 `tests/contract/test_cli_migrate_guard.py` 加入：
  - `report --update-exit 4` 被接受，報告中的更新狀態說明需要先搬家；
  - `scripts/backup_db.py` 在只有 `data/steamsage.db` 時以 4 結束、不建立 zip、不呼叫 `gh`（用 `importlib` 載入，比照 `tests/unit/test_backup_db.py`，`gh` 以 monkeypatch 取代）；
  - 在 `tests/unit/test_backup_db.py` 加測試：對 `tmp_path` 中的新名稱資料庫與設定檔執行 `build_zip`，zip 內的檔名是 `data/sweetspot.db`、`sweetspot.toml`（FR-004）。`build_zip` 目前讀模組常數 `ROOT`，需要時讓它接受資料夾參數，預設仍是 `ROOT`。
- [X] T027 [P] [US3] 靜態測試 `tests/unit/test_cmd_scripts.py`：
  - `更新資料.cmd`、`背景更新.cmd` 都呼叫 `uv run sweetspot`；
  - 整體結束代碼的設定順序符合 1 > 4 > 3 > 2 > 0；
  - `更新資料.cmd` 有 update 為 4 時的搬家提示。

  讀檔一律用 UTF-8。

### Implementation for User Story 3

- [X] T028 [US3] `src/sweetspot/cli.py`（research R7、contracts/migrate.md §4–§5），讓 T025 通過：
  - 新增 `EXIT_NEEDS_MIGRATION = 4`，模組說明的結束代碼清單加上 4；
  - `main()` 的順序：解析參數 → `migrate` 交出 → 設定檔檢查 → `load_config` → 資料庫檢查 → 並存提醒 → 原流程；
  - 檢查用 `legacy.py`，拒絕時不呼叫 `setup_logging`、不取鎖。
- [X] T029 [US3] `report --update-exit` 的選項改為 0–4。報告中 update 為 4 時的狀態文字與 1 同類，另註明需要先搬家。實作在 `src/sweetspot/cli.py` 與報告產生更新狀態的程式（用 `git grep -n update_exit -- src` 找出）。讓 T026 第一項通過。
- [X] T030 [P] [US3] `scripts/backup_db.py`：只有舊名稱的資料庫時印出相同提示並回傳 4；必要時讓 `build_zip` 接受資料夾參數。讓 T026 第二、三項通過。
- [X] T031 [P] [US3] `更新資料.cmd`、`背景更新.cmd`：
  - 整體結束代碼優先順序改為 1 > 4 > 3 > 2 > 0；
  - `更新資料.cmd` 加上 update 為 4 時的提示「找到舊名稱的檔案，請先執行搬家：uv run sweetspot migrate」；
  - 檔案保持 UTF-8，第一行仍是 `chcp 65001`。

  讓 T027 通過。
- [X] T032 [P] [US3] `README.md` 新增「從改名前的雲端備份還原」（FR-012，research R12）：zip 內是 `data/steamsage.db`、`steamsage.toml`，解開到主資料夾後執行 `uv run sweetspot migrate`。另在「舊名稱」一節說明結束代碼 4。
- [X] T033 [US3] 執行 `uv run pytest`，全部通過後 commit「016 US3: refuse with exit 4 when only old-name files exist」。

**Checkpoint**：US3 可獨立驗證。合併後忘了搬家，02:30 會以 4 結束並寫明原因，資料不受影響。

---

## Phase 6: User Story 4 - 確認沒有漏改（Priority: P3）

**Goal**：掃描版控檔案，例外清單以外的 `steamsage` 為 0；例外清單由掃描產生（FR-013、FR-014）。

**Independent Test**：
- 執行掃描，未允許為 0；
- 故意加一處，掃描找得到。

### Tests for User Story 4（先寫，確認失敗）

- [X] T034 [P] [US4] 測試 `tests/unit/test_scan_names.py`（contracts/scan.md，research R10）。用 `importlib` 載入 `scripts/scan_names.py`，確認：
  - (a) **規則正反樣本**：contracts/scan.md §2 的每一條規則，各凍結至少一個「該命中」與一個「不該命中」的樣本。至少包含：
    - `〈前身專案資料夾〉\state\cache` → 前身專案；
    - `globalThis.SteamSage` → 未允許；
    - `uv run steamsage update` → 未允許；
    - `steamsage.decision/2` → 資料識別碼；
    - `steamsage.toml` 出現在一般檔案 → 未允許；
    - 「（舊名 `steamsage`）」→ 舊名稱說明；
    - 同一行一處允許、一處未允許 → 未允許。
  - (b) **找得到故意加的一處**：在給定的假檔案清單中加入一個新的 `steamsage`，掃描回報該檔案與行號，結束代碼 1。
  - (c) **repo 本身**：執行 `git ls-files` 的掃描，未允許為 0。
  - (d) **例外文件是最新的**：`docs/legacy-names.md` 與重新產生的內容逐字相同。
  - (e) **規則表與文件對應**：規則表的每一條在文件中都有一節。

### Implementation for User Story 4

- [X] T035 [US4] 實作 `scripts/scan_names.py`（contracts/scan.md §1–§3）：
  - 規則表、逐行掃描、各類別次數與檔案數（當場計算）、二進位檔計數；
  - `--write` 產生 `docs/legacy-names.md`；
  - 檔案清單可注入，供 T034 (b) 使用。
- [X] T036 [US4] 執行 `uv run python scripts/scan_names.py`。逐一處理每個「未允許」：
  - 該改的改成新名稱，例如 T003 漏掉的寫法；
  - 確實該保留的，回頭修改 contracts/scan.md 的規則表並說明理由。修改規則表屬於偏離 plan，要先停下來告知使用者。

  最後執行 `--write` 產生 `docs/legacy-names.md`。
- [X] T037 [US4] 執行 `uv run pytest tests/unit/test_scan_names.py` 與全部測試，通過後 commit「016 US4: scan for old names, generated exceptions list」。

**Checkpoint**：掃描是自動測試的一部分，之後新加的 `steamsage` 會讓測試失敗。

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T038 `HANDOFF.md`（FR-005）：
  - 操作步驟中的指令、檔名、排程工作名稱改成新名稱，例如每日更新、手動更新、備份、本機程式安裝；
  - 歷史段落不改；
  - 在第 3a 節記下 016 的狀態與「合併後要執行搬家」。

  HANDOFF 整份是掃描例外，改完後人工 `git grep -n -i steamsage -- HANDOFF.md`，確認剩下的都在歷史段落。
- [X] T039 全部自動測試（quickstart A）：
  - `uv run pytest`、`node --test tests/extension/`、`uv run python tests/extension/e2e.py`、`uv run python scripts/scan_names.py`；
  - 記下 pytest 與 node 的數量，和 T001 比較（SC-001）。
- [X] T040 quickstart B 步驟 1–3：用真實資料建立暫存副本 `$T`，用 master 的程式產生基準紀錄 A。用新程式確認只有舊名稱時以 4 拒絕、`$T` 沒有新檔（SC-004）。不碰主資料夾的任何檔案。
- [X] T041 quickstart B 步驟 4–6：
  - 模擬失敗（另開唯讀連線），確認改回後檔案清單與雜湊相同；
  - 用 `--dry-run` 看計畫，再正式搬家，記錄耗時（SC-003：1 分鐘內）與 SHA-256；
  - 確認環境段兩步都是 `skipped`，工作排程器仍只有「SteamSage2 每日背景更新」；
  - 再搬一次，確認顯示「已經是新名稱」。
- [X] T042 quickstart B 步驟 7–8：用新程式產生紀錄 B 與擴充功能資料檔 B。用 scratchpad 的比對腳本確認：
  - 願望清單全部款數的決策逐款相同（SC-002；2026-10-15 為 69 款，以當時的實際款數為準）；
  - 資料檔只差 `generated_at` 與 `config_path`；
  - HTML 報告除了產生時間與路徑以外相同（US1 情境 2；第 2 步之後先複製 `$T\data\reports\latest.html`）；
  - 新舊程式的 `backtest-rule --cutoff 2026-09-25 --apps-limit 200` 資料集識別碼相同。

  結果寫進 `specs/016-rename-internal-ids/quickstart.md` 的「實測紀錄」一節。
- [X] T043 quickstart B 步驟 9–10：用只印布林值的腳本，確認以下輸出與檔案中都不含兩個 API 金鑰的值（SC-007）：
  - T040–T042 的輸出；
  - `$T\data\logs\`；
  - `migration.json`。

  之後刪除 `$T`。
- [X] T044 quickstart D（US3 情境 3、FR-012）：在新的暫存資料夾解開一份改名前的雲端備份 zip（`gh release download` 取最近一份 `sweetspot-<tag>.zip`），照 README 的「從改名前的雲端備份還原」操作：
  1. `uv run sweetspot update --config <暫存>\sweetspot.toml`：結束代碼 4，並提示先搬家；
  2. `uv run sweetspot migrate --config <暫存>\sweetspot.toml`：結束代碼 0，環境段 `skipped`；
  3. `uv run sweetspot report --config <暫存>\sweetspot.toml`：正常結束。

  README 的說明與實際步驟不符時就修正 README。最後刪除暫存資料夾。
- [X] T045 quickstart B 步驟 11（research R6，analyze C3）：用暫時的測試工作驗證真正的工作排程器。
  - 用 scratchpad 腳本建立「SweetSpot 搬家測試（舊）」：
    - 動作是 `conhost.exe --headless cmd.exe /d /c "<worktree>\<只寫一行文字的 .cmd>"`；
    - 觸發時間設在 2030 年；
    - `StartWhenAvailable`、`Interactive`、`Limited` 比照真實工作。
  - 以測試名稱呼叫 `migrate.py` 的排程工作步驟（真的 PowerShell 執行器），確認：
    - 舊的已刪除；
    - 「SweetSpot 搬家測試（新）」的觸發、動作、工作目錄、`StartWhenAvailable`、`LogonType`、`RunLevel` 和舊的相同；
    - `<URI>` 是新名稱。
  - 刪除新的測試工作，和那支 .cmd。
  - 前後各讀一次「SteamSage2 每日背景更新」的設定，兩次完全相同。
  - 這是手動驗證，不放進自動測試。自動測試仍不碰工作排程器。
- [X] T046 [P] 回顧值得重構的點（全域守則「交付」），列在交付說明，不擅自改範圍外的程式。例如：
  - `migrate.py` 的函式長度；
  - 與 `host/install.py` 重複的路徑判斷。
- [X] T047 更新 `specs/016-rename-internal-ids/tasks.md` 的勾選狀態與 `HANDOFF.md`，commit「016: polish, real-data check」。
- [X] T048 交給使用者：說明最該審的地方、測試沒覆蓋的部分（真實工作排程器只用 T045 的測試工作驗證過、Chrome 重新載入、本機程式實機）、3–5 行資料與控制流說明。合併方式（squash merge 到 master）、時機與 push 由使用者決定。

---

## Phase 8: 使用者驗收（合併後，quickstart C）

- [X] T049 使用者在主資料夾合併。避開 02:30，也不要在 `更新資料.cmd` 執行中合併。
- [X] T050 使用者執行 `uv run sweetspot migrate --dry-run`，確認計畫無誤後執行 `uv run sweetspot migrate`。預期結束代碼 0；若為 2，照列出的手動步驟做。
- [X] T051 使用者在 Chrome 重新載入擴充功能，版本顯示 1.2.0。在遊戲頁確認以下都正常：
  - 面板；
  - 版本一節；
  - 指定一次再改回 Steam 預設。
- [X] T052 使用者在工作排程器確認只剩「SweetSpot 每日背景更新」，設定與原本相同。執行一次 `更新資料.cmd`，確認 `data\logs\sweetspot-YYYYMMDD.log` 出現。
- [X] T053 連續 3 晚，`background-update.log` 結束行的整體代碼為 0 或 2（SC-006）。之後由使用者決定刪除 `data\pre-016-backup-…`，並更新 HANDOFF，再開始 014。
  **結果**：10/17 02:30 與 10/18 02:30 結束行都是「update 0，report 0，backup 0，整體 0」。10/16 02:30 的結束行已被下一晚覆寫
  （`background-update.log` 每次整份重寫），以旁證判定正常：`runs` 該次為 completed、`failures` 為空、預測紀錄 `20261015T183223Z` 已寫、
  雲端備份 `db-2026-10-16` 已上傳；排程器上次結果 0。2026-10-18 使用者同意後移除 worktree `〈專案資料夾〉-016`（分支保留）；
  備份資料夾 `data\pre-016-backup-20261015-001119\`（198 MB）使用者同意刪除，自動模式不允許我刪，使用者 2026-10-18 自己刪除（已確認資料夾不存在）。

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup（Phase 1）**：沒有前提。T002 依賴 T001 的盤點。
- **Foundational（Phase 2）**：依賴 Phase 1，阻擋所有 story。T003 → T004 → T005 → T006 → T007 依序；T008 → T009 在 T007 之後。
- **US1（Phase 3）**：依賴 Phase 2，和 US2、US3、US4 沒有相依。
- **US2（Phase 4）**：依賴 Phase 2（`legacy.py`）。
- **US3（Phase 5）**：依賴 Phase 2；T028 和 US2 的 T023 都改 `cli.main`，同一檔案依序做，先 T023 再 T028。
- **US4（Phase 6）**：依賴 US1–US3 完成，因為掃描要看到最終的檔案，例如 `legacy.py`、`migrate.py`、README 的舊名稱一節。
- **Polish（Phase 7）**：依賴全部 story。T040–T043 依序；T044、T045 在 T043 之後，彼此獨立。
- **使用者驗收（Phase 8）**：依賴 T048 與使用者的合併決定。

### Within Each User Story

- 測試先寫並確認失敗，再實作。
- 同一檔案的 task 不平行，例如 `cli.py`、`tests/integration/test_migrate.py`、`README.md`。
- 每個 story 結束時跑全部測試再 commit。

### Parallel Opportunities

- Phase 2：T008 可以在 T007 之後和 US1 的測試同時寫。
- US1：T010、T011、T012、T013 可平行；T015、T016 可平行。
- US2：T018、T019 寫在同一個測試檔，依序寫；T020 是不同檔，可平行。
- US3：T025 與 T026 寫在同一個測試檔，依序寫；T027 可平行。T030、T031、T032 改不同檔，可平行。

## Parallel Example: User Story 1

```text
Task: "016 T010 說明文字不含 steamsage（tests/contract/test_cli_contract.py）"
Task: "016 T011 manifest 1.2.0 與擴充功能靜態檢查（tests/extension/manifest.test.js、static.test.js）"
Task: "016 T012 日誌檔名與 logger 名稱（既有日誌測試）"
Task: "016 T013 擴充功能資料檔路徑與格式名稱（tests/contract/test_extension_contract.py）"
```

## Implementation Strategy

### MVP First（Phase 1–3）

1. Phase 1–2：改名完成、全部測試通過。這一步風險最高（範圍最大），完成後先停下確認 diff。
2. Phase 3（US1）：使用者看得到的名稱與文件。
3. **STOP and VALIDATE**：全新資料夾中的行為和改名前相同。

但 US1 單獨**不能合併**到主資料夾：現有檔案還是舊名稱，新程式會建立空的新設定檔與資料庫。必須連同 US2（搬家）與 US3（拒絕）一起合併。

### Incremental Delivery

1. Phase 1–3：改名（MVP，只在 worktree 中驗證）。
2. Phase 4：搬家。
3. Phase 5：拒絕。到這裡才具備合併條件。
4. Phase 6：掃描，確認沒有漏改。
5. Phase 7：真實資料副本驗證。
6. Phase 8：使用者合併、搬家、觀察 3 晚。

## Notes

- 每個 story 一個 commit 為原則（T007、T017、T024、T033、T037、T047）。
- T036 若需要改掃描規則，視為偏離 plan，要先停下來告知使用者。
- 合併、push、刪除備份都由使用者決定。
