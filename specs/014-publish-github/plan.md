# Implementation Plan: 公開到 GitHub

**Branch**: `014-publish-github` | **Date**: 2026-10-18 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/014-publish-github/spec.md`

這份計畫本身會公開：路徑一律寫代稱（〈專案資料夾〉等），不寫 SteamID、帳號名與 NSFW 遊戲名稱。

## Summary

**目標**：讓 SweetSpot 能被別人安裝使用，然後以「本機 master 是唯一正本、公開 repo 是它的發佈快照」的方式公開。

**做法**：
- **願望清單不寫死**：預設設定拿掉個人值。新增 `sweetspot setup`：檢查 ITAD 金鑰後才詢問網址；自訂網址用 Steam 社群的公開 XML 換成數字形式（不需要金鑰）；確認讀得到才建立設定檔。不能互動時，以新的結束代碼 5 拒絕，不建立檔案。
- **個人資訊**：
  - 新增 `scripts/scan_personal.py`，架構照 016 的 `scan_names.py`。離線類別是 master 的自動測試；發佈時加查金鑰、帳號名、願望清單的排序與日期、NSFW。
  - 一次性改寫工具：程式和測試裡的 SteamID 換成虛構值 `76561197960265728`；specs/docs 的路徑與 SteamID 換成代稱。
  - 精簡完整清單檔，`comparisons.md` 的逐款表改用代號。
  - 4 款 NSFW 遊戲和 Shiravune 搜尋結果，換成虛構的名稱與 app id。
- **安裝與日常**：
  - 新增 `sweetspot schedule install|uninstall|status`，重用 016 的 Scheduler，可以指定名稱，同名但指向別的資料夾時拒絕。
  - 沒有 `private` remote 時，雲端備份略過。
  - 參考資料集不到 2,000 款時，報告和擴充功能顯示同一則提示。
  - README 加上從零安裝的說明，加 MIT LICENSE。
- **發佈**：新增 `scripts/publish.py`。
  - 取 master 已提交的內容，扣掉 `HANDOFF.md`，整份換掉公開資料夾；掃描與測試通過才 commit（作者 noreply）。
  - 在 master 打 `publish/NNN` tag 當發佈紀錄。
  - 不推送；印出指令，等使用者確認。

**五個難以回頭的選擇（2026-10-18 使用者選定，全部照建議）**（外部依賴、CLI 形狀、紀錄方式；公開後別人會照著用）：
1. 自訂網址用 Steam 社群的公開 XML 換算（research R1）；
2. 第一次設定用新指令 `sweetspot setup`，不能互動時用新結束代碼 5（R2）；
3. 排程註冊用新指令 `sweetspot schedule`（R4）；
4. 發佈紀錄用 master 上的 `publish/NNN` tag（R11）；
5. 參考資料集提示的門檻 2,000 款（R6）。

## Technical Context

**Language/Version**: Python 3.12+（uv 管理）；擴充功能 Chrome MV3 JavaScript；`.cmd` 批次檔

**Primary Dependencies**: 不新增第三方套件。沿用 `httpx`、`tzdata`、`pytest`、`tomllib`、`subprocess`；新的來源 `SteamCommunity`（個人檔案 XML，標準函式庫解析）

**Storage**: SQLite `data/sweetspot.db`（schema 不變）；TOML 設定檔（預設值改變，data-model）；決策紀錄與擴充功能資料檔多一個選用欄位 `reference_notice`（不升版）；git tag `publish/NNN`

**Testing**: pytest（目前 1759 個）、`node --test "tests/extension/*.test.js"`（56 個）、`tests/extension/e2e.py`（真 Chrome，124 項）、`scripts/scan_names.py`、新的 `scripts/scan_personal.py`

**Target Platform**: Windows 10/11（使用者是 Windows 11 Home：沒有 Sandbox／Hyper-V）；工作排程器、HKCU 登錄、Chrome

**Project Type**: 本機 CLI ＋ Chrome 擴充功能 ＋ Chrome 本機程式

**Performance Goals**: 第一次設定（不含更新）1 分鐘內；發佈步驟（含 uv sync 與 pytest）10 分鐘內；從零安裝的實測時間寫進 README

**Constraints**:
- 測試不得碰真實的設定檔、資料庫、登錄、排程工作（Scheduler 與網路都用假的）；
- 金鑰不得出現在輸出、日誌、公開檔案；
- 新寫的文件（含本 feature 的 specs）不得含個人值——它們也會公開，離線掃描會擋；
- 使用者本人的 02:30 背景更新與雲端備份不得中斷。

**Scale/Scope**（research「盤點」）：
- SteamID 13 處、9 個檔；Windows 絕對路徑 92 處、60 個檔；
- 使用者願望清單 67 款出現在公開檔案；
- NSFW：4 款在完整清單檔以外，另有 Shiravune 搜尋結果約 35 款。

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原則 | 檢查 | 結果 |
|---|---|---|
| I 未知不是零 | 參考資料集不足時明確提示（FR-014a），不隱藏；願望清單讀不到時不建立設定檔，不用空清單冒充 | 通過 |
| II 證據可追溯 | 正式紀錄多一個選用欄位，記下當時的資料集大小；格式名稱不變。發佈紀錄 `publish/NNN` 可追溯每次公開的來源 | 通過 |
| III 逐項隔離失敗 | 雲端備份略過不影響整體代碼；發佈任一步失敗就把公開資料夾恢復原狀、不打 tag；排程註冊失敗不動既有的工作 | 通過 |
| IV 預測必須可驗證 | 不改模型、規則與信心等級；提示只在呈現層。`comparisons.md` 只把遊戲名稱換成代號，數字、判定與結論不變，並加日期註記（research R10）。測試資料改寫後 golden 頁只差名稱與編號 | 通過 |
| V 規則單一正本 | 規則與版本不變 | 通過 |
| VI 簡單優先 | 不新增第三方套件；掃描沿用 016 的架構；門檻 2,000 款的依據是 001 SC-006（R6），不是新調的參數 | 通過 |
| VII 核心與呈現分離 | `reference_notice` 由核心算出；HTML 與擴充功能只讀它，數字相同 | 通過 |
| VIII 遵守資料來源條款 | 新來源 `steamcommunity.com` 的個人檔案 XML：Valve 自己的公開端點，不在禁止名單；只在第一次設定時用，有速率限制與 Retry-After；遇到 401/403 停止；做成可抽換的介面。NSFW 查詢用既有的公開 GetItems | 通過 |
| IX 本機與安全 | 金鑰只從環境讀，`setup` 不詢問也不寫入金鑰、不碰 Steam 密碼；掃描只報金鑰的位置；市場固定台灣區（README 寫明） | 通過 |
| 技術約束 | Python 3.12 + uv；PowerShell 只用於排程工作（沿用 016 的 `-EncodedCommand`）；中文路徑與工作名稱 | 通過 |
| 品質關卡 | 設定流程、掃描規則、排程判斷、發佈步驟都測試先行；spec 已經使用者確認（clarify 2026-10-18）；plan 的 5 個選擇由使用者確認（2026-10-18「照建議」） | 通過 |

Phase 1 設計後重新檢查：沒有新的違反，不需要 Complexity Tracking。有一點要注意：FR-006 會修改 `specs/` 的歷史文件，這是 016「specs 歷史文件不改」的明確例外，只限於換代稱。

## Project Structure

### Documentation (this feature)

```text
specs/014-publish-github/
├── spec.md
├── plan.md              # 本文件
├── research.md          # R1–R14 與盤點
├── data-model.md        # 設定檔預設值、結束代碼 5、reference_notice、排程、發佈紀錄
├── quickstart.md        # 情境 A–H
├── contracts/
│   ├── cli.md           # setup、沒有設定檔時、schedule、backup_db、.cmd、提示文字
│   ├── scan-personal.md # 掃描類別與規則
│   └── publish.md       # 發佈步驟
├── redact_tool.py       # 一次性改寫工具（代稱、虛構 SteamID、NSFW 與 Shiravune 替換），照 016 rename_tool.py
├── inventory/           # 唯讀盤點腳本（真實值執行時才讀）與 golden 頁比對腳本
└── checklists/requirements.md
```

### Source Code (repository root)

```text
src/sweetspot/
├── config.py            # DEFAULT_TOML 去掉個人值；load_config 不再建立檔案；ConfigMissing
├── cli.py               # setup、schedule 子指令；沒有設定檔時的判斷與結束代碼 5
├── setup.py             # 新：第一次設定流程（金鑰檢查、網址解析、清單檢查、寫檔）
├── schedule.py          # 新：排程工作 XML 與 install/uninstall/status（重用 migrate.Scheduler）
├── migrate.py           # Scheduler 等共用部分抽到 schedule.py 或原地共用（不改行為）
├── sources/steam_community.py  # 新：個人檔案 XML（自訂網址→數字、privacyState）
├── pipeline/reference.py       # dataset_size 供提示使用（不改定義）
├── decision/…、report/html.py、report/extension.py  # reference_notice 欄位與頁首提示
└── commands.py          # import-legacy 沒有設定時的說明
extension/lib.js、popup.js、content.js  # 顯示 reference_notice
scripts/
├── scan_personal.py     # 新
├── publish.py           # 新
├── backup_db.py         # 沒有 private remote 時略過
├── record_fixtures.py   # 錄製時截斷願望清單、改寫排序與日期、排除 NSFW
└── scan_names.py        # 前身專案路徑換代稱後的規則調整
更新資料.cmd、背景更新.cmd   # setup 與 SWEETSPOT_BACKGROUND、代碼 5
README.md、LICENSE（新）、docs/personal-scan.md（新，由掃描產生）、docs/model/comparisons.md（逐款表代號）
tests/                   # 虛構 SteamID、精簡的 wishlist_ok.json、NSFW 替換、golden 頁重新產生；新測試見下
```

**Structure Decision**：沿用現有的單一專案結構；新增模組都是現有模式的同類（`setup` 對 `migrate`、`schedule` 對 `host install`、`scan_personal` 對 `scan_names`）。

## 實作順序（交給 /speckit-tasks 細分）

1. **設定與結束代碼 5**（US1，測試先行）：`config` 不再自動建立；`SteamCommunity` 來源；`setup` 流程；`cli` 的判斷；`.cmd` 的改動。
2. **掃描**（US2）：`scan_personal.py` 與規則樣本測試（先讓它在現況上找到全部 92＋13 處）。
3. **清理**（US2）：`redact_tool.py` 跑一次（虛構 SteamID、代稱、NSFW 替換），精簡 `wishlist_ok.json` 並改測試斷言，`comparisons.md` 代號，`record_fixtures.py`，golden 頁重新產生；掃描歸零、全部測試通過。
4. **安裝與日常**（US3）：`schedule` 指令；`backup_db.py` 略過；`reference_notice`（核心→HTML→擴充功能）；README、LICENSE、`docs/personal-scan.md`。
5. **發佈**（US4）：`publish.py` 與它的測試（用暫存資料夾與假的 gh）；`--dry-run`。
6. **驗收**：情境 A–F；合併前由使用者確認；情境 G（從零安裝）在發佈產生的公開資料夾上做；第一次真正的發佈與推送由使用者確認後執行；情境 H 合併後 3 晚。

## Complexity Tracking

沒有違反憲章的項目。
