# Implementation Plan: 內部識別碼改名 steamsage → sweetspot

**Branch**: `016-rename-internal-ids` | **Date**: 2026-10-15 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/016-rename-internal-ids/spec.md`

## Summary

**目標**：把程式的指令、套件、設定檔、資料庫、日誌、擴充功能內部名稱、排程工作從 `steamsage`／`SteamSage2` 改成 `sweetspot`／`SweetSpot`。寫進已保存紀錄、或決定回測資料集的三類識別碼保留不改：格式名稱、`steamsage-004-split`、`steamsage_version`。

**做法**：
- `git mv` 套件資料夾，再用一次性的改寫工具改內容。工具先保護保留的識別碼，再取代。
- 新增 `sweetspot migrate`，一次把使用者現有的檔案搬到新名稱：
  - 取寫入鎖、先複製備份、改名、驗證 SHA-256，失敗就改回；
  - 再自動重寫本機程式的啟動檔、重建排程工作；
  - 只剩 Chrome 重新載入需要手動。
- 只有舊名稱檔案時，其他指令一律以新結束代碼 4 拒絕，不建立任何檔案。
- 用一支掃描腳本與測試確認，例外清單以外不再出現 `steamsage`。

**三個難以回頭的選擇（2026-10-15 使用者選定）**：
- 搬家用子指令；
- 搬家前複製一份到 `data/pre-016-backup-<時間>/`；
- 排程工作由搬家自動重建。

## Technical Context

**Language/Version**: Python 3.12+（uv 管理）；擴充功能為 Chrome MV3 JavaScript

**Primary Dependencies**: 不新增。沿用 `httpx`、`tzdata`、`pytest`、標準函式庫 `sqlite3`、`hashlib`、`tomllib`、`subprocess`

**Storage**: SQLite `data/sweetspot.db`（schema v7 不變）；TOML 設定檔；JSON 搬家紀錄（data-model §2）

**Testing**: pytest（目前收集 1597 個）、`node --test tests/extension/`（55 個）、`tests/extension/e2e.py`（真 Chrome）、新的 `scripts/scan_names.py`

**Target Platform**: Windows 11（主資料夾 `〈專案資料夾〉`，工作排程器、HKCU 登錄、Chrome）

**Project Type**: 本機 CLI ＋ Chrome 擴充功能 ＋ Chrome 本機程式（native messaging host）

**Performance Goals**: 真實資料（206 MB 資料庫）上，搬家 1 分鐘內完成（SC-003）

**Constraints**:
- 搬家和 02:30 背景更新、本機程式共用寫入鎖 `data/.lock`；
- 測試不得碰真實的設定檔、資料庫、登錄、排程工作（環境段只處理指向同一資料夾的登記，測試用假的執行器）；
- 金鑰不得出現在輸出與日誌；
- 中文路徑與工作名稱。

**Scale/Scope**: 版控檔案中 `steamsage` 共 45 種寫法：
- `src` 76 檔、測試 137 檔、scripts 3 檔、擴充功能 4 檔、根目錄 5 檔、docs 2 檔、data 1 檔；
- specs 196 檔，是歷史，不改。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原則 | 檢查 | 結果 |
|---|---|---|
| I 未知不是零 | 不碰價格與預測資料；改名前後輸出相同（FR-007） | 通過 |
| II 證據可追溯 | 正式紀錄格式名稱、`steamsage_version` 欄位保留；搬家紀錄 `migration.json` 記下改了什麼、雜湊、備份位置 | 通過 |
| III 逐項隔離失敗 | 搬家的檔案段全有或全無，失敗改回並保留備份；環境段失敗不回復檔案段、不讓每日更新消失（research R4、R6）；只有舊名稱時拒絕而不是開空資料庫（FR-010） | 通過 |
| IV 預測必須可驗證 | 不改模型或規則；分組依據 `steamsage-004-split` 保留，回測資料集識別碼不變，並在真實資料副本上驗證（R11） | 通過 |
| V 規則單一正本 | 規則與版本不變；`model-definition.md` 只更新程式路徑 | 通過 |
| VI 簡單優先 | 不保留 `steamsage` 別名、不升格式版本；搬家指令是一次性的，014 再決定去留 | 通過 |
| VII 核心與呈現分離 | 擴充功能只改名稱與資料檔名，仍只讀核心產生的資料檔 | 通過 |
| VIII 遵守資料來源條款 | 不新增任何網路請求 | 通過 |
| IX 本機與安全 | 搬家不寫金鑰；`migration.json` 不含設定檔內容；日誌照常遮蔽；`.gitignore` 同時忽略新舊名稱與備份資料夾 | 通過 |
| 技術約束 | Python 3.12 + uv；不新增第三方套件；PowerShell 只用於排程工作，以 `-EncodedCommand` 傳中文 | 通過 |
| 品質關卡 | 搬家與舊名稱保護的測試先行；spec 已確認；plan 由使用者確認（2026-10-15，`/speckit-analyze` 後「都按照建議作」） | 通過 |

Phase 1 設計後重新檢查：沒有新的違反，不需要 Complexity Tracking。

## Project Structure

### Documentation (this feature)

```text
specs/016-rename-internal-ids/
├── spec.md
├── plan.md              # 這份
├── research.md          # R1–R12
├── data-model.md        # 名稱對照、migration.json
├── quickstart.md        # 自動測試、真實資料副本、合併後搬家
├── contracts/
│   ├── names.md         # 改名對照、保留的識別碼、檔案狀態
│   ├── migrate.md       # sweetspot migrate、結束代碼 4
│   └── scan.md          # 掃描規則表、docs/legacy-names.md
├── rename_tool.py       # 一次性改寫工具（R1），實作時建立
├── checklists/requirements.md
└── tasks.md             # /speckit-tasks 產生
```

### Source Code (repository root)

```text
src/sweetspot/                 # git mv src/steamsage（全部模組照舊，只改名稱）
├── cli.py                     # EXIT_NEEDS_MIGRATION=4；main：migrate 先處理 → 舊名稱檢查 → load_config → 資料庫檢查 → 並存提醒
├── legacy.py                  # 新：名稱對照、檔案狀態、config_blocker／db_blocker／並存提醒
├── migrate.py                 # 新：搬家（檔案段、環境段、migration.json）；PowerShell 執行器可注入
├── commands.py                # migrate 子指令登記；擴充功能資料檔名；report --update-exit 接受 4
├── config.py                  # db_path → sweetspot.db；說明文字
├── logs.py                    # sweetspot-YYYYMMDD.log、logger 名稱
└── host/install.py, service.py, __main__.py   # -m sweetspot.host、說明文字

extension/
├── manifest.json              # version 1.2.0
├── lib.js, content.js, popup.js, sw.js   # SweetSpot 全域名稱、sweetspot-* class、sweetspot-extension.json、新指令

scripts/
├── backup_db.py               # 新檔名；只有舊名稱時以 4 結束
├── scan_names.py              # 新：掃描與 docs/legacy-names.md 產生（R10）
├── feature_analysis.py, wait_cost_monotonic.py   # 新檔名

docs/
├── legacy-names.md            # 新：由掃描產生
└── model/model-definition.md  # 程式路徑

tests/
├── unit/test_legacy_names.py      # 新：狀態判斷、對照表與 contracts/names.md 一致
├── unit/test_scan_names.py        # 新：repo 未允許為 0、文件最新、規則正反樣本
├── integration/test_migrate.py    # 新：搬家、改回、已搬、衝突、鎖、環境段（假執行器）
├── contract/test_cli_migrate.py   # 新：結束代碼、輸出、所有子指令遇舊名稱以 4 拒絕
└── …（既有 137 個測試檔只改 import 與檔名）

更新資料.cmd, 背景更新.cmd     # uv run sweetspot；結束代碼 4 的優先順序與提示
pyproject.toml, uv.lock        # name/scripts/packages
.gitignore                     # 加新名稱與 data/pre-016-backup-*/，保留舊名稱
README.md, HANDOFF.md          # 新指令；「舊名稱」一節；從舊雲端備份還原
data/steam_sales.toml          # 註解中的指令
```

**Structure Decision**：沿用既有的單一 Python 專案、擴充功能、scripts 結構，只改名稱。新增兩個模組：`legacy.py` 給一般指令、搬家、備份腳本共用，`migrate.py` 只給搬家用。另新增一支腳本 `scan_names.py`。

## 實作順序（交給 /speckit-tasks 細分）

1. **機械式改名**：`git mv`，改寫工具，`uv lock`；全部既有測試通過，數量不變。這一步先做，改寫工具才不會動到之後的測試裡刻意寫出的舊檔名。
2. **測試先行**：寫 `legacy` 與 `migrate` 的測試，確認它們失敗。
3. **舊名稱保護**：`legacy.py`、`cli.main`、`.cmd`、`backup_db.py`、結束代碼 4。
4. **搬家**：`migrate.py`，先做檔案段，再做環境段。
5. **擴充功能**：名稱、版本 1.2.0；node 與 e2e 測試。
6. **掃描**：`scan_names.py`、`docs/legacy-names.md`、測試。
7. **文件**：README、HANDOFF、model-definition。
8. **quickstart B**：在真實資料副本上驗證。
9. **交給使用者**：合併與 quickstart C。

## Complexity Tracking

沒有需要說明理由的違反。
