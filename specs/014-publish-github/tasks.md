---

description: "Task list for 014 publish to GitHub"
---

# Tasks: 公開到 GitHub

**Input**: Design documents from `specs/014-publish-github/`

**Prerequisites**: plan.md、spec.md、research.md、data-model.md、contracts/（cli.md、scan-personal.md、publish.md）、quickstart.md

**Tests**: 憲章「測試先行」與 spec 的 Independent Test 都要求測試。設定流程、掃描規則、排程判斷、參考資料集提示、發佈步驟的測試先寫，並確認會失敗後才實作。

**Organization**: 依 user story 分組。測試用設定檔的共用輔助（Phase 2）是 US1 改預設值的前提。US2 的清理在 US1 之後做，因為改寫工具也要處理 US1 新寫的檔案。

**工作位置**：worktree〈專案資料夾〉-014（分支 `014-publish-github`）。〈專案資料夾〉留在 master，給每日背景更新與 Chrome 用，到 Phase 7 合併之前都不動。

## Format: `[ID] [P?] [Story] Description`

- **[P]**：可平行，因為改的是不同檔案、彼此沒有相依。
- **[Story]**：所屬 user story（US1–US4）。
- 引用時一律帶 spec 號，例如 `014 T012`。

## 共同規則（每個 task 都適用）

- 測試不得碰真實的 `sweetspot.toml`、`data/sweetspot.db`、HKCU 登錄、工作排程器、網路。
  - 一律用 `tmp_path`、可注入的 PowerShell 執行器（016 `migrate.Scheduler` 的做法）、假的 HTTP 回應。
- 本 feature 新寫或修改的檔案（含 `specs/014-publish-github/`）都會公開：
  - 不寫 SteamID、本機路徑、帳號名、NSFW 遊戲名稱，一律用代稱；
  - NSFW 遊戲的真實名稱與替換對照只記在 HANDOFF.md（不公開）。
- 含 CJK 或反斜線的一次性腳本寫到 scratchpad，以 `PYTHONUTF8=1` 執行；不用 heredoc、`python -`、`python -c`。
- commit 訊息寫成檔案，以 `git commit -F` 提交，結尾加 attribution 兩行。
- 偏離本清單或 plan 時先停下說明。

---

## Phase 1: Setup（清理前的基準）

**Purpose**：記下清理前的狀態，作為 SC-001、SC-002 與改寫工具的比對基準。

- [X] T001 記錄清理前的基準：
  - 在 worktree 執行 `uv run pytest --collect-only -q`（預期 1759）與 `node --test "tests/extension/*.test.js"`（預期 56）；
  - 用 `specs/014-publish-github/inventory/` 的盤點腳本（用法見該資料夾的 README）重跑一次；
  - 數字寫進 `specs/014-publish-github/research.md` 開頭的「盤點」，作為「清理前」一列：SteamID 13 處／9 檔、Windows 絕對路徑 92 處／60 檔、願望清單 67 款、NSFW 9 款。
- [X] T002 把 NSFW 的 9 款遊戲（名稱、app id、出現的檔案）、Shiravune 搜尋結果的 app id 清單，以及之後的替換對照記進 worktree 的 `HANDOFF.md`。它不公開；research 與 spec 只寫數量。

---

## Phase 2: Foundational（測試用設定檔）

**Purpose**：測試目前直接寫 `DEFAULT_TOML`（32 個檔、97 處）。US1 把預設網址改成空字串後，這些測試會因為「還沒設定」而失敗，所以先讓它們改用一份測試專用的設定。

- [X] T003 新增 `tests/config_builders.py`：
  - `FAKE_STEAMID = "76561197960265728"`（帳號 0，research R8）；
  - `FAKE_WISHLIST_URL`；
  - `TEST_TOML`：`DEFAULT_TOML` 的網址換成 `FAKE_WISHLIST_URL`，用字串取代並 assert 只取代一處。
  - 用一次性腳本把 `tests/` 裡 97 處 `DEFAULT_TOML` 改成 `TEST_TOML`（import 一起改）。只檢查「預設內容」本身的測試（例如 `tests/unit/test_config.py` 驗證預設值的那幾個）保留 `DEFAULT_TOML`，逐一列在 commit 訊息。
  - 跑全部測試仍是 1759 通過。

**Checkpoint**：預設值可以安全地改了。

---

## Phase 3: User Story 1 - 新使用者用自己的願望清單（Priority: P1）🎯 MVP

**Goal**：沒有設定檔時，會詢問網址並確認讀得到；背景執行以結束代碼 5 拒絕；使用者本人不受影響。

**Independent Test**：quickstart 情境 B。

### Tests for User Story 1（先寫，確認失敗）

- [X] T004 [P] [US1] `tests/unit/test_steam_community.py`＋`tests/fixtures/community/`（虛構的個人檔案 XML：public、friendsonly、private、找不到）：
  - 自訂網址 → `steamID64`；
  - `privacyState` 三種；
  - `<error>` → 找不到；
  - 429 帶 Retry-After 時等待；401／403 停止且不重試（憲章 VIII）；
  - 名稱含特殊字元時正確編碼。
- [X] T005 [P] [US1] `tests/unit/test_setup.py`：照 contracts/cli.md §1 逐項測，輸入用假的 stdin，網路用假的來源。
  - 設定檔已存在：不改檔，代碼 0；
  - 不能互動（stdin 不是終端機、或 `SWEETSPOT_BACKGROUND=1`）：代碼 5；
  - 沒有 `ITAD_API_KEY`：說明「設定後重開視窗」，代碼 5，沒有建立檔案；
  - 網址格式：四種形式（含結尾斜線有無）都接受，其他形式拒絕並重問；
  - 自訂網址：換成數字形式，印出「已記成這個帳號」；
  - 帳號不存在、不公開：說明後重問；
  - 0 款：問 y/N，N 不建立檔案；
  - 空白或 Enter：代碼 5；
  - 寫出的檔案：開頭有註明，網址是數字形式，其餘等於 `DEFAULT_TOML`；
  - `--change`：只改 `[wishlist] url` 那一行，註解與其他內容不動；
  - 輸出不含金鑰。
- [X] T006 [P] [US1] `tests/contract/test_cli_setup_guard.py`：照 contracts/cli.md §2。
  - 沒有設定檔、不能互動時，`minimal_args` 表裡的每個子指令（表由 parser 列舉，照 016 `test_cli_migrate_guard.py`）都以 5 結束；
  - 資料夾前後的檔案清單相同（沒有建立 `data/`、日誌、設定檔）；
  - `migrate`、`--help`、`--version` 不受影響；
  - 只有舊名稱檔案時仍是 4（016 優先）；
  - 有設定檔時行為不變（FR-004）。
- [X] T007 [P] [US1] 補 `tests/unit/test_config.py`：
  - `DEFAULT_TOML` 沒有 SteamID 形式的數字、沒有 Windows 絕對路徑；
  - `load_config` 遇到不存在的檔案丟 `ConfigMissing`、不建立檔案；
  - `wishlist.url` 為空字串時，錯誤訊息指向 `sweetspot setup`；
  - `[legacy] cache_path` 為空字串時載入成功（`legacy_cache_path` 為 None）。
- [X] T008 [P] [US1] 補 `tests/unit/test_cmd_scripts.py`：
  - `更新資料.cmd`：沒有 `sweetspot.toml` 時先執行 `sweetspot setup`，代碼不是 0 就停止；
  - `背景更新.cmd`：設定 `SWEETSPOT_BACKGROUND=1`；
  - 兩個檔的整體代碼順序都是 1 > 5 > 4 > 3 > 2 > 0（data-model「結束代碼」）。

### Implementation for User Story 1

- [X] T009 [P] [US1] `src/sweetspot/sources/steam_community.py`：個人檔案 XML 的來源。
  - 介面：`resolve_vanity(name) -> steamid`、`privacy(steamid)`；
  - 速率與重試沿用 `RateLimitedClient`；User-Agent 同其他來源；
  - 只用標準函式庫解析（`xml.etree`，關掉外部實體）。
- [X] T010 [US1] `src/sweetspot/config.py`：
  - `DEFAULT_TOML` 的 `wishlist.url` 與 `[legacy] cache_path` 改成空字串，`[purchase_options]` 的範例註解保留；
  - `load_config` 不再建立檔案，不存在時丟 `ConfigMissing`；
  - 空網址時丟 `ConfigError`「還沒設定願望清單：請執行 uv run sweetspot setup」；
  - `legacy_cache_path: Path | None`。
- [X] T011 [US1] `src/sweetspot/setup.py`：照 contracts/cli.md §1 與 research R3 的流程。
  - 可注入 stdin、stdout、環境、來源；
  - 網址解析接受四種形式；
  - 願望清單檢查重用 `SteamWebApi.get_wishlist` 與它的 `private` 判斷；
  - 寫檔用暫存檔再改名，失敗不留下半個檔；
  - `--change` 只改那一行。
- [X] T012 [US1] `src/sweetspot/cli.py`：
  - 新增 `setup` 子指令（不取寫入鎖、不開資料庫）；
  - `EXIT_NOT_SET_UP = 5`，更新開頭說明；
  - `main` 在 016 的舊名稱檢查之後、`load_config` 之前判斷設定檔：不存在時，能互動就呼叫 setup、成功後繼續原指令，不能互動就印出說明並回 5；
  - 「能互動」的判斷集中在一個函式：stdin 是終端機，而且沒有 `SWEETSPOT_BACKGROUND=1`；
  - 兩張由 parser 列舉子指令的 `minimal_args` 表（016 的 `tests/contract/test_cli_migrate_guard.py`、T006 的 `tests/contract/test_cli_setup_guard.py`）都加上 `setup`。
- [X] T013 [US1] `src/sweetspot/commands.py`：`import-legacy` 在沒有 `--path`、設定也是空的時候，說明這個指令是給前身專案的使用者用的，以 1 結束。補 `tests/unit/test_import_legacy*.py` 一個案例。
- [X] T014 [US1] `更新資料.cmd`、`背景更新.cmd`：照 contracts/cli.md §5 修改，保持 CRLF；跑 T008 通過。
- [X] T015 [US1] 跑 T004–T008 與全部測試；在 scratchpad 的暫存資料夾用真實網路走一次 quickstart 情境 B 的 1–4。用使用者本人的帳號；結果只記「成功／失敗」，不記 SteamID。

**Checkpoint**：US1 可單獨驗證。使用者本人的〈專案資料夾〉還沒有合併，不受影響。

---

## Phase 4: User Story 2 - 公開的內容沒有個人資訊（Priority: P1）

**Goal**：離線掃描歸零（只剩列明的例外）；完整清單與 NSFW 遊戲不在公開檔案；以後的錄製與發佈都會擋。

**Independent Test**：`uv run python scripts/scan_personal.py` 為 0；quickstart 情境 C。

### Tests for User Story 2（先寫，確認失敗）

- [X] T016 [P] [US2] `tests/unit/test_scan_personal.py`：
  - 照 contracts/scan-personal.md §2 的離線類別，每條規則各一個該中、一個不該中的樣本；
  - 在 repo 上跑離線掃描，「不允許」為 0（現在會失敗）；
  - 輸出格式與結束代碼依 §3、§4；
  - 掃描本身（`scripts/scan_personal.py`、`contracts/scan-personal.md`）裡的規則樣本照 016 的做法列為例外類別「規則說明」。
- [X] T017 [P] [US2] `tests/unit/test_scan_personal_publish.py`：`--publish` 類別，全部用假的值。
  - 假金鑰放在環境變數：只報位置，輸出裡沒有金鑰；
  - 假的 git remote 擁有者：命中帳號名，但 `LICENSE` 的著作權行允許；
  - 暫存資料庫：放一份假的願望清單（排序與日期），檔案裡出現成對的值時命中；
  - 假的 GetItems 回應：內容描述 3 或 4 命中，1 不命中；查詢失敗時結束代碼 2。
- [X] T018 [P] [US2] `tests/unit/test_record_fixtures.py`：錄 GetWishlist 時用假的 HTTP 回應。
  - 截斷到測試需要的筆數；
  - 排序與加入日期改成虛構值；
  - 內容描述 3／4 的遊戲被排除；
  - 錄發行商搜尋時不再錄 Shiravune（改錄的發行商或虛構標題，依 T025 的決定），錄出的標題裡沒有 HANDOFF 記下的 Shiravune 作品；
  - 錄出的內容通過離線掃描。

### Implementation for User Story 2

- [X] T019 [US2] `scripts/scan_personal.py`：照 contracts/scan-personal.md，架構照 `scripts/scan_names.py`。
  - 先只做離線類別與 `--write`（產生 `docs/personal-scan.md`）；
  - 在現況上跑一次，確認找到 T001 記錄的全部命中（SteamID 13、路徑 92），沒有漏網；
  - 結果附在 research「盤點」。
- [X] T020 [US2] 一次性改寫工具 `specs/014-publish-github/redact_tool.py`（research R8、R9，照 016 `rename_tool.py`）。
  - **處理範圍**：`git ls-files`，排除 `HANDOFF.md`。
  - **替換**：
    - 程式、測試、腳本、測試資料：使用者 SteamID → `FAKE_STEAMID`；
    - `specs/`、`docs/`、README：SteamID → `〈SteamID〉`；
    - 路徑代稱：〈專案資料夾〉與舊名、worktree 字尾、〈前身專案資料夾〉、〈使用者資料夾〉，含 `\\` 跳脫寫法；
    - NSFW：名稱與 app id → 虛構值（app id 個位數不是 0）；
    - Shiravune 搜尋結果（`tests/fixtures/steam/search_shiravune_{0,50,100}.json`，FR-008b）：每一筆的名稱與 app id 換成虛構值（「範例作品 001」……），保留筆數、分頁與欄位結構；用到這些檔的測試（`tests/unit/test_steam_store.py` 等）的斷言跟著改。
  - **真實值的來源**：執行時從本機讀（SteamID 讀 `sweetspot.toml`，路徑由資料夾位置推得，NSFW 對照讀 HANDOFF），不寫進工具本身。
  - **報告**：逐檔列出改了幾處；`--dry-run` 只報告不改。
- [X] T021 [US2] 跑 T020 前先做一次性的線上確認（scratchpad 腳本）：
  - 用 GetItems 確認虛構的 app id 都查無此 app；
  - 虛構名稱與真實遊戲不重名。
  - 結果記在 HANDOFF。
- [X] T022 [US2] 執行 `redact_tool.py`，然後調整受影響的地方：
  - `scripts/scan_names.py` 的前身專案路徑規則改認代稱；`docs/legacy-names.md` 用 `--write` 重新產生；`tests/unit/test_scan_names.py` 的樣本同步；
  - 測試裡斷言真實名稱或編號的地方，改成虛構值；
  - 跑全部測試。
- [X] T023 [US2] `tests/fixtures/steam/wishlist_ok.json`：
  - 只留測試用得到的筆數；排序與加入日期改成虛構值；不含 NSFW 遊戲；
  - `tests/unit/test_steam_store.py::test_wishlist_parse` 的筆數與第一筆的斷言跟著改；
  - 搜尋其他用到這個檔的測試並一起改。
- [X] T024 [US2] `docs/model/comparisons.md`：
  - 逐款表的遊戲名稱換成代號（「遊戲 01」……），同一款在各段用同一代號；數字、判定與結論不變；
  - 代號與遊戲（名稱、app id）的對照表寫進 HANDOFF（不公開），讓使用者本人仍能追溯（憲章 II）；
  - 在檔案開頭加一段 2026-10-18 的註記，說明改寫的理由（014 FR-008），並說明這不算任何比較（憲章 IV）。
- [X] T025 [US2] `scripts/record_fixtures.py`：照 T018 實作；錄製時查 GetItems 內容描述（research R9）。
  - 發行商搜尋的錄製：先查有沒有作品數足夠分頁（> 100 款）、而且沒有內容描述 1、3、4 作品的發行商可以改錄；找不到就錄完一律換成虛構標題。選了哪一種、理由，寫進 research R9。
- [X] T026 [US2] 重新產生 golden 頁：`uv run python -m tests.unit.report.test_html_golden`。
  - 新寫 `specs/014-publish-github/inventory/check_golden_redaction.py`（唯讀）：把改寫前（`git show <T022 前的 commit>:…`）的 golden 頁套上 redact_tool 的同一份替換，確認和重新產生的結果逐字相同；
  - 沒有改到的 golden 頁，用 `git checkout` 還原行尾雜訊。
- [X] T027 [US2] `scripts/scan_personal.py` 的 `--publish` 類別：照 contracts/scan-personal.md「發佈時的類別」實作。
  - 資料庫以唯讀 URI 開啟；
  - GetItems 每批 100 個 app id、間隔 1.5 秒；
  - 跑 T017。
- [X] T028 [US2] 收尾：
  - `scan_personal.py` 離線為 0、`scan_names.py` 為 0；
  - `--write` 產生 `docs/personal-scan.md`；
  - 全部測試、node 測試通過，數量不少於 T001；
  - 用 `specs/014-publish-github/inventory/` 的 `remaining_wishlist.py`、`collect_apps.py`、`nsfw_check.py` 對 worktree 重跑：內容描述 3／4 的遊戲 0 款，Shiravune 作品 0 款，完整清單檔不再有 66 款。
  - 數字記進 research「盤點」的「清理後」一列。

**Checkpoint**：公開內容在離線檢查下乾淨；發佈時的檢查已就緒。

---

## Phase 5: User Story 3 - 照 README 從零安裝（Priority: P1）

**Goal**：排程可以一步註冊與移除；沒有私人 repo 時備份會略過；參考資料集小時有提示；README 能讓新使用者從零走完。

**Independent Test**：quickstart 情境 D、E；情境 G 在 Phase 7。

### Tests for User Story 3（先寫，確認失敗）

- [X] T029 [P] [US3] `tests/unit/test_schedule.py`：假的 Scheduler。
  - 產生的工作 XML 符合 data-model「排程工作」表的每一列（觸發 02:30、headless 的動作與引號、工作目錄、補跑、1 小時、IgnoreNew、電池、說明文字）；
  - contracts/cli.md §3 的表逐格測：沒有、同資料夾、別的資料夾 × install、uninstall、status，以及 `--replace`、`--name`、`--dry-run`；
  - PowerShell 失敗時給出手動步驟；
  - 中文名稱與路徑。
- [X] T030 [P] [US3] 補 `tests/unit/test_backup_db.py`：
  - 沒有 `private` remote 時印出「略過雲端備份」、代碼 0；日誌結果行附「略過」；
  - 有 remote 但 gh 失敗時仍是 1。
- [X] T031 [P] [US3] `tests/unit/test_reference_notice.py`＋補 `tests/unit/report/test_html.py`、`tests/extension/lib.test.js`：
  - 參考資料集 1,999 款時，決策紀錄有 `reference_notice`（`dataset_size`、`threshold` 2000、`broad_sample`）；
  - 2,000 款時沒有這個欄位；
  - 沒有 `STEAM_WEB_API_KEY` 時 `broad_sample` 是 `disabled`，提示多一句；
  - HTML 頁首、擴充功能資料檔、彈出視窗與面板的款數相同，文字照 contracts/cli.md §6；
  - 舊的資料檔沒有這個欄位時，擴充功能照常顯示（011 版本規則）；
  - 加提示前後，決策逐款相同。

### Implementation for User Story 3

- [X] T032 [US3] `src/sweetspot/schedule.py`＋`cli.py` 的 `schedule` 子指令：照 research R4、data-model「排程工作」。
  - 把 `migrate.py` 的 `Scheduler`、`_runs_here` 等共用部分移到 `schedule.py`（`migrate.py` 改成匯入，行為不變）；
  - 兩張 `minimal_args` 表（見 T012）都加上 `schedule`；
  - 016 的 migrate 測試照樣通過；跑 T029。
- [X] T033 [US3] `scripts/backup_db.py`：照 contracts/cli.md §4；跑 T030。
- [X] T034 [US3] 參考資料集提示的核心部分：
  - `src/sweetspot/decision/contract.py` 加選用欄位 `reference_notice`；
  - `src/sweetspot/commands.py` 的 report 讀 `dataset_size`（`pipeline/reference.py` 同一個定義）與廣泛樣本狀態，決定是否帶這個欄位；
  - 門檻常數 `REFERENCE_TARGET = 2000`，註解寫明依據 001 SC-006。
- [X] T035 [US3] 參考資料集提示的呈現部分：
  - `src/sweetspot/report/html.py` 頁首（放在 `calendar_notices` 之後）；
  - `src/sweetspot/report/extension.py` 資料檔；
  - `extension/lib.js`、`popup.js`、`content.js` 顯示；
  - 跑 T031、node 測試、e2e；
  - golden 頁不應改變：golden 頁由測試資料直接產生，輸入裡沒有 `reference_notice`，不經過資料庫的 `dataset_size`；若有改變，停下說明；
  - 先列出會在小型測試資料庫上執行 report 的整合測試（它們的資料集 < 2,000，輸出會多出提示），逐一確認斷言要不要跟著改，結果寫進 commit 訊息。
- [X] T036 [US3] README 重寫「從零安裝」，照 research R12 的清單：
  - 開頭的英文說明；只支援 Windows 與台灣區；
  - 前置需求與版本；兩把金鑰（必要或選用、少了會怎樣、怎麼申請、使用者層級環境變數、重開視窗）；
  - `更新資料.cmd` 第一次設定；參考資料集；`schedule install`；擴充功能；`host install`；
  - 公開 repo 是發佈快照（PR 怎麼處理）；ITAD 條款；結束代碼 5；
  - 舊的「指令」表加上 `setup`、`schedule`。
  - 實測時間先留「待 Phase 7 量」。
- [X] T037 [P] [US3] `LICENSE`：MIT，著作權行「Copyright (c) 2026 <帳號名>」（帳號名從 git remote 取，寫檔用一次性腳本）。這是 contracts/scan-personal.md 帳號名類別唯一允許的地方。
- [X] T038 [P] [US3] 既有契約的日期註記：
  - `specs/001-price-data-foundation/contracts/cli.md` 的結束代碼表加 5；
  - `specs/011-chrome-extension/contracts/extension-data.md` 加 `reference_notice` 選用欄位；
  - `specs/016-rename-internal-ids/contracts/names.md` 註明代稱改寫（014 FR-006）。

**Checkpoint**：US3 的程式與說明就緒；從零安裝的實測在 Phase 7。

---

## Phase 6: User Story 4 - 發佈與更新公開 repo（Priority: P2）

**Goal**：一個可重複的發佈步驟，產生只有 1 個 commit 的公開資料夾，之後每次多 1 個 commit，並在 master 留下 `publish/NNN`。

**Independent Test**：quickstart 情境 F（在暫存資料夾）。

### Tests for User Story 4（先寫，確認失敗）

- [X] T039 [US4] `tests/integration/test_publish.py`：用 `tmp_path` 建一個假的 master repo（含 `HANDOFF.md`）；gh、測試執行器、掃描都可注入。
  - 第一次發佈：公開資料夾只有 1 個 commit，作者與提交者都是假的 noreply 地址，沒有 `HANDOFF.md`，訊息不含 `claude.ai/code`；master 有 `publish/001`，tag 訊息含公開 commit 雜湊。
  - 第二次發佈：master 改一個檔、刪一個檔、加一個檔後，公開資料夾多 1 個 commit，三種改變都反映；有 `publish/002`。
  - 只發佈已提交的內容：工作目錄沒 commit 的修改不會出現。
  - 前提不成立時代碼 1、什麼都沒改：不在 master、工作目錄不乾淨、公開資料夾被手動改過。
  - 掃描或測試失敗時：沒有 commit、沒有 tag，公開資料夾回到原狀；第一次發佈則資料夾被刪除。
  - `--dry-run`：沒有任何改變，印出檔案清單與訊息草稿。
  - 不推送：沒有呼叫 push；印出的下一步指令符合 contracts/publish.md §2-8。
  - master 的檔案與 HEAD 不變（只多 tag）。

### Implementation for User Story 4

- [X] T040 [US4] `scripts/publish.py`：照 contracts/publish.md 實作；
  - noreply 地址以 `gh api user` 取得 `id` 與 `login`；
  - 跑 T039。
- [X] T041 [US4] README「維護者：發佈到公開 repo」一小節：指令、會做什麼、不會做什麼（不推送）。HANDOFF 加「第一次發佈的步驟」（使用者確認點）。

**Checkpoint**：發佈步驟可在暫存資料夾完整驗證。

---

## Phase 7: Polish、驗收與合併

- [X] T042 全部驗證：
  - `uv run pytest`、`node --test "tests/extension/*.test.js"`、`uv run python tests/extension/e2e.py`、`scan_names.py`、`scan_personal.py`；
  - 測試數量不少於 T001（SC-001）；
  - quickstart 情境 A–F 逐一執行，結果補在 quickstart.md 各情境下方；
  - 記錄 plan「Performance Goals」的兩個時間：第一次設定（不含更新，目標 1 分鐘內）、發佈步驟（含 uv sync 與 pytest，目標 10 分鐘內）。
- [X] T043 列出值得重構的點（重複、過長函式、命名不一致），寫在交付訊息，不擅自重構範圍外的部分。
- [X] T044 更新 HANDOFF（開頭、§0.5、§3a）與記憶的指標；向使用者報告並請使用者確認合併（squash 合併到 master，照 016）。合併後在〈專案資料夾〉執行 `uv sync`。
  - 2026-10-18 收工時：HANDOFF（開頭、§0.5、§3a、「下一個 session 注意」）與記憶已更新；**還沒做**：使用者確認後 squash 合併到 master、主資料夾 `uv sync`、Chrome 重新載入 1.2.2。
  - 2026-10-18 使用者同意後 squash 合併到 master `cb1ed65`（樹和分支 `6af4761` 相同），〈專案資料夾〉`uv sync` 完成；
    合併後在〈專案資料夾〉：pytest 1950 passed、`scan_personal.py` 不允許 0（689 檔）、`scan_names.py` 未允許 0（685 檔）；
    `SWEETSPOT_BACKGROUND=1` 跑唯讀的 `coverage` 以 0 結束（使用者本人的設定檔照常讀到，不會走第一次設定）；`schedule status` 與合併前相同。
    Chrome 重新載入 1.2.2 由使用者做；還沒推送到 private。
- [ ] T045 合併後，與使用者一起在白天做 quickstart 情境 G（從零安裝）：
  - 先執行 `uv run python scripts/publish.py --dry-run`，再實際執行，產生公開資料夾；把公開資料夾複製到新資料夾；
  - 另一個 Chrome 設定檔；排程用 `--name "SweetSpot 驗收"`；
  - 記錄每一步的時間，補進 README（把 T036 的「待量」換成實測值）；`sweetspot reference` 的實測時間同時填進參考資料集提示的文字（contracts/cli.md §6 的「約 N 分鐘」、`report/html.py` 與擴充功能）與 research R6；
  - 還原使用者的排程與本機程式登錄，並確認和驗收前相同。
  - README 有修改時，在 master commit 後重新發佈（公開資料夾仍未推送）。
  - 2026-10-21～22 驗收已做（結果在 quickstart 情境 G）：從零安裝、擴充功能、本機程式、排程都可用，排程與本機程式登錄已還原並和基準相同。
    **還沒做**：把實測時間補進 README、contracts/cli.md §6、research R6；刪除 `publish/001` 與公開資料夾後重新發佈；刪除〈驗收資料夾〉（使用者確認）。
  - **待使用者決定**（驗收發現）：新安裝把 `reference` 做完（整份清單看過）只有 1,659 款，低於 R6 的門檻 2,000，提示仍叫使用者執行 `reference`，但再執行不會增加。
    A（建議）看完整份清單（`population_exhausted`）時改成「已補完、少於原作者驗證時的規模」，不再叫使用者執行；B 改門檻（要重寫 R6 的理由）；C 只在 README 寫明。
  - 其他驗收發現（不在 014 範圍內修改，供使用者決定是否另外處理）：Steam 商店整站故障時 `reference` 以 1 結束、訊息只有 HTTP 502（README 可以寫「稍後再執行會接著做」）；
    `schedule status` 對還沒執行過的工作印出 Windows 的原始值；`setup` 不在日誌留結果行。
- [ ] T046 第一次正式公開（**使用者確認後才做**）：
  - 讓使用者看 `publish.py` 印出的檔案清單、訊息與掃描結果；
  - 使用者確認後，由使用者執行或同意執行印出的指令：`gh repo create <帳號>/SweetSpot --public`（空的 repo）、`git -C <公開資料夾> push -u origin main`，以及 `git push private --tags`；
    （2026-10-22 稽核補記：原本寫的 `gh repo create … --source … --push` 不是 `publish.py` 印出的指令，已被 contracts/publish.md §2 第 8 步取代。
    使用者的 `gh` 用 ssh 推送，推送前先把公開資料夾的 `origin` 改成 ssh 網址，同一步驟的註記。）
  - 確認公開 repo 只有 1 個 commit、作者是 noreply 地址（SC-005）。
- [X] T047 合併後連續 3 晚（quickstart 情境 H）：
  - 當天日誌有 update、report、backup 三行結果，整體代碼 0 或 2，雲端備份照常；
  - 使用者確認後勾選，SC-006。
  - 2026-10-18 白天先試（不算三晚之一）：使用者同意後在工作排程器手動啟動「SweetSpot 每日背景更新」（同一個工作、同一支 `背景更新.cmd`），
    15:57:50–16:00:35，`background-update.log` 結束行「update 0，report 0，backup 0，整體 0」，工作結果 0；
    當天日誌有 update（140.5 秒）、report（7.8 秒）、backup（14.9 秒）三行，代碼都是 0；雲端備份當天那份已更新。
    update 的 alerts 1 項是 010 組合包推算不符（今天不給組合包建議），和 014 無關。
  - 第 1 晚 2026-10-19：02:30:01–02:32:56，整體 0；`sweetspot-20261019.log`（本機日期）有 update（145.6 秒）、report（9.5 秒）、
    backup（18.2 秒）三行，代碼都是 0；雲端備份新增當天那份並刪除最舊一份。alerts 同上 1 項。
  - 第 2 晚 2026-10-20：update（212.9 秒）、report（7.6 秒）、backup（19.9 秒）都是 0。第 3 晚 2026-10-21：update（141.9 秒）、report（7.6 秒）、backup（19.0 秒）都是 0，
    `background-update.log` 結束行整體 0。三晚都達標；使用者 2026-10-22 確認，勾選。

---

## Phase 8: 驗收後修補（014 T045 的發現；使用者 2026-10-22 同意提案）

- [X] T048 參考資料集「已補完」（使用者選 A）：spec FR-014a 修訂、data-model `sampling`、contracts/cli.md §6 兩種文字、research R6 實測；
  `pipeline/reference.py` 新增 `sampling_complete`（唯讀），`commands.reference_notice` 帶 `sampling`，`report/html.py` 依它組文字（擴充功能顯示同一段文字，不用改）；
  測試：兩種文字、判斷的邊界（公司目錄沒翻完、候選 pending／accepted、分層都滿、清單看完、清單有新的一款、沒有 Steam 金鑰、清單是空的）、達到門檻的紀錄不變。
  - 2026-10-22：提示文字的測試直接比對 contracts/cli.md §6 引號裡的兩段文字。以〈專案資料夾〉的資料庫（唯讀）試算：第一版是 False——每家公司的目錄都列出願望清單上的那款遊戲，
    樣本從不收它，所以永遠是 `pending`（81 筆，全部是願望清單的遊戲）；改成排除願望清單後為 True，並補上這個情況的測試。
    第一版逐公司查詢要 3.5 秒（主鍵以 app_id 開頭，依公司查是整表掃描），改成一次查出後 1.45 秒；只有低於門檻時才算。
- [X] T049 `reference` 因來源錯誤整次失敗時加一句「已完成的部分都已保存；來源恢復後再執行 … 會接著做」（001 contracts/cli.md 加日期註記）；README §5 同一句。
- [X] T050 `setup` 建立或改寫設定檔時在當天日誌留結果行（contracts/cli.md §1 第 8 點）；沒有建立檔案的結束不寫。
- [X] T051 `schedule status`：267011 寫「還沒執行過」、267009 寫「執行中」（contracts/cli.md §3）。
- [X] T052 README 補實測時間（第一次更新、`reference`、第一次設定），取代「待實測」；跑情境 A 全部（pytest、node、e2e、兩個掃描）。
  - 2026-10-22：pytest 1969、node 57、e2e 124/124（輸出導到檔案時要 `PYTHONUTF8=1`，否則 cp950 印不出「−」而中斷）、`scan_personal.py` 不允許 0、`scan_names.py` 未允許 0。
- [X] T053 刪除 `publish/001` 與公開資料夾後重新發佈（`--dry-run` 再正式；不推送），接 T046。
  - 2026-10-22：確認公開 repo 不存在、私人 repo 沒有 `publish` tag 後刪除舊的；`--dry-run` 159 秒，正式 150 秒：688 檔、掃描不允許 0，公開 commit 1 個（作者與提交者 noreply），`publish/001` 打在 `015a2a4`；沒有推送。
- [X] T054 （2026-10-22，重構時跑完整測試發現）`test_publish.py` 的「檢查沒通過時還原公開資料夾」偶爾失敗：`export` 用 `shutil.copy2` 保留 `git archive` 給每個檔案的 commit 時間，
  同一秒內 commit、大小相同的修改，git 的 stat 比對看不出來，所以既沒有發佈也沒有還原。改成 `shutil.copy`，並補一個固定兩次 commit 時間的回歸測試（改回 `copy2` 時 3 次失敗 2 次）。
  第一次發佈沒有舊的索引，`publish/001` 的內容不受影響；但它收錄的 `scripts/publish.py` 是修正前的版本。

---

## Phase 9: 公開前的 spec drift 稽核（使用者 2026-10-22 同意照建議做）

稽核紀錄：[audit-2026-10-22.md](./audit-2026-10-22.md)。程式的修正一個發現一個 commit，都先寫一個在舊程式上會失敗的測試。

- [X] T055 `scan_personal.py --publish` 只掃 clone 看得到的檔案（公開資料夾的 `git ls-files --cached --others --exclude-standard`），
  不再掃到測試步驟留下的 `.venv`（第二次發佈起一定不通過）；`--publish` 也掃 DIR 裡的 `HANDOFF.md`（萬一它被帶進來）。
- [X] T056 `schedule`：`uninstall`／`status` 收到 `--dry-run` 或 `--replace` 時拒絕（以前 `uninstall --dry-run` 會真的移除）；`status` 的觸發時間讀工作本身的設定，不寫死 02:30。
- [X] T057 失敗行附加的 `__notes__` 也遮蔽金鑰（014 T049 重構後，任何例外的 notes 都會印出）。
- [X] T058 `publish.py`：gh、uv、node 在前提檢查時確認；第一次發佈時 gh 失敗不印 traceback；打 tag 失敗時撤回公開 commit；
  匯出後沒有變動時當作「沒有新的內容」；commit 訊息含對話連結時拒絕（FR-016）。
- [X] T059 `背景更新.cmd`：update 回 5（還沒設定）時略過雲端備份，Python 端不留當天的日誌（contracts/cli.md §2）。
  - 2026-10-22 實際執行 .cmd 時另外發現：cmd.exe 在 `chcp 65001` 之後，有時會從含中文的 `rem` 的下一行中間開始讀，第一版的 `set "bcode=略過…"` 因此失去值；
    舊的 `背景更新.cmd` 開頭第三行也被當成指令執行。哪一行出錯取決於資料夾路徑的長度：第一版在 120 種長度裡只有 1 種出錯。
    兩支 .cmd 的 `rem` 改成 ASCII（contracts/cli.md §5）。新增 `tests/integration/test_cmd_run.py`，用假的 uv.exe 實際執行 .cmd；新增靜態測試，檢查 `rem` 都是 ASCII。
- [X] T060 `setup`：詢問時按 Ctrl+C 當作沒有輸入（5）；17 位數字但不是 SteamID64 的個人檔案網址說明格式不對，不說「自訂名稱只能有…」。
- [X] T061 個資掃描：產生的例外清單寫「加入日期」（不是「排序」）；補「不在本機專案上層或使用者資料夾」這個排除條款的測試。
  - 2026-10-22：拿掉排除條款時兩個新測試都失敗。規則的說明與 contracts/scan-personal.md §2–§3 改成程式實際的規則（任何磁碟、磁碟根目錄、`tests/` 底下任何路徑、`example.net`、規則說明的檔案、輸出的代號）。
    寫測試時發現：路徑在空白處截斷，所以 `X:\Program Files\<名稱>` 這種真實資料夾，排除條款看不到後半段（contract 已註明）。
- [X] T062 文件補記（「2026-10-22 稽核補記」）：014 的 contracts、data-model、research、quickstart、T046 的指令；001 `config.md`、001 `cli.md` 的 import-legacy、016 `migrate.md` 的 `--update-exit`。
- [X] T063 比對測試：從 parser 列舉 `setup`、`schedule`、`publish.py`、`scan_personal.py` 的旗標與結束代碼，逐項確認 contract 有寫。
  - 2026-10-22：`tests/contract/test_contract_lists_014.py`（接用 `test_cli_contract.py` 既有的 `_subcommands`）：
    - 兩個子指令的旗標與動作；兩支腳本的旗標（從 `--help` 列舉）；
    - `cli`、`setup` 的每個 `EXIT_*` 在 001 的結束代碼表都有一列；
    - `reference_notice` 的鍵與值；`SWEETSPOT_BACKGROUND`。
    - 例外：`--config`、`--json` 是每個子指令共用的，寫在 001。
    - 證明：拿掉 `--replace`、`--message-file`、代碼 5 那一列、`incomplete` 時，四個測試各自失敗。
  - 沒有列舉的：日誌摘要的 `settings=created|changed`（只有實際寫檔才出現）、掃描輸出的類別代號、兩支腳本的結束代碼（寫在函式裡的常數，不是具名常數）。
- [X] T064 稽核紀錄寫進 repo，HANDOFF 留指標；跑情境 A 全部（pytest、node、e2e、兩個掃描）。
  - 2026-10-22：[audit-2026-10-22.md](./audit-2026-10-22.md)；pytest 2015、node 57、e2e 124/124、`scan_names.py` 未允許 0、`scan_personal.py` 不允許 0。
- [X] T065 刪除 `publish/001` 與公開資料夾後重新發佈（同 T053），把 `publish/001` 推到私人 repo；接 T046。
  - 2026-10-22：確認公開 repo 不存在、私人 repo 沒有 `publish` tag、舊的公開資料夾乾淨後刪除舊的；`--dry-run` 156 秒，正式 152 秒：    691 檔、發佈檢查不允許 0，公開 commit 1 個（作者與提交者 noreply），`publish/001` 打在 `1ad1ebd`；公開 repo 沒有推送，master 與 tag 推到私人 repo。
- [X] T066 （使用者 2026-10-22 要求一起處理，稽核紀錄「沒有處理的」第 1 項）`setup --change` 遇到 `url = "…"` 以外的寫法不再印 traceback（contracts/cli.md §1 第 9 點）：
  接受任何單行 TOML 寫法，只在 `[wishlist]` 段找；沒有就補上；寫入前讀回確認，不是有效的 TOML 時不改檔、以 1 結束。
  寫測試時另外發現：`[wishlist]` 沒有 url 時，舊程式會改到後面別段的 url 那一行。用使用者的設定檔在記憶體試算（不寫檔）：只改 1 行、讀回正確。
  這一項在 `publish/001` 之後，下一次發佈才收錄。

---

## Phase 10: 往前稽核 001–013、015、016（使用者 2026-10-22 同意全部照建議做）

稽核紀錄：[audit-2026-10-22-earlier.md](./audit-2026-10-22-earlier.md)。這是公開前的檢查，所以記在 014；改到哪一份 spec 的 contract，就在那一份加「（2026-10-22，014 Txxx）」註記。

- [X] T067 015 本機程式：設定檔讀不到時照樣讀訊息並回覆（`config_ok: false`／`config-invalid`，015 FR-017）；允許的來源從資料夾裡的登記檔讀，設定檔連 TOML 都不是時用預設資料夾。新增走子程序的測試。
- [X] T068 015 擴充功能：`config_ok` 是 false 時不說「設定檔已改回 Steam 預設」；擴充功能 1.2.3（使用者要重新載入）。
- [X] T069 參數錯誤以 1 結束（不是 argparse 的 2）；`report --update-exit` 收到 0–5 以外的代碼時當作更新失敗。
  - 兩支 .cmd 也一樣：update 的代碼不認得時，以前整體算 0，現在算 1。改完後重新掃描路徑長度（34–47、45–164 字元），兩支都沒有讀錯。
- [X] T070 001 `coverage` 唯讀：不開寫入連線，不建立、不升級資料庫。
- [X] T071 001 `reference` 抓不到 Steam 遊戲清單時加提醒（結束代碼 2）。同時更正 014 T062 寫錯的註記（001 contracts/cli.md `reference`：只有判斷候選時查商店資料的錯誤以 1 結束）。
- [X] T072 001 `update` 所有來源都不可用時以 1 結束。
- [X] T073 009 報告的版本行：`source = user` 就顯示「（使用者指定）」，指定的是 Steam 預設時也一樣。
- [X] T074 009 `[purchase_options]` 的追蹤範圍統一成願望清單上的遊戲（`update` 摘要與 `report` 一致）。
  - **2026-10-22 使用者改裁定**：照 009 spec，追蹤範圍是「願望清單＋移除後仍在追蹤期間」；改的是 `report` 的警告與本機程式的 `not-tracked`，`update` 不動（`choices.TRACKED_STATES`）。
  - **2026-10-22 停下，等使用者裁定**：照建議改了之後，既有測試失敗；009 spec 的 Edge Case 明寫「從願望清單移除後仍在追蹤期間的遊戲：指定設定照常生效，和每日更新的追蹤範圍相同」。
    `update` 的做法才符合 spec，不一致的是 `report`（與本機程式）對這類遊戲警告「不在追蹤範圍，已忽略」。提案時沒看到這一條，修改已還原。
- [X] T075 010 組合包卡片與彈出視窗：已有原因句時不再重複 `check_text`。
- [X] T076 012 429 沒有 Retry-After 時也記為「被限速」。
- [X] T077 003 報告頁首「價格指標準版本」改成符合 006／009 的說法。
- [X] T078 006／007 以現行季節模型重跑 `ns-backtest`，確認報告引用的「可能提早到價」命中率（憲章 IV）。
  - 2026-10-22：`ns-backtest --split all --cutoff 2026-09-25`（唯讀，54.6 秒）：74.9%（5,168／6,903），原本 73.6% 是 seasonal-record 1.0.0 的決策。
    資料集也不同（2,583 → 2,636 款，`96fe5584…` → `663fa7c5…`：參考資料集增加、schema v7 重抓），兩者的影響沒有分開。
    `NS_BACKTESTS`、docs/model/model-definition.md 的整節數字、README「約 75%」改成這次的結果；決策紀錄的 `backtest` 多 `seasonal_model`。報告的句子從「74%」變成「75%」。
- [X] T079 文件補記：各 spec 的 contract、data-model、quickstart；schema v7；維運行為（雲端備份、`背景更新.cmd`、日誌結果行、輸出編碼）；README；014 T062 寫錯的 `reference` 註記。
- [X] T081 （稽核後發現，使用者 2026-10-22 同意）015 擴充功能：本機程式「無法使用」的說明只包一次（`lib.js` 的 `hostState`，content.js 改用它）；擴充功能 1.2.4。
- [ ] T082 重做 `publish/001`（使用者 2026-10-22 同意刪除私人 repo 上的舊 tag）：刪除本機與私人 repo 的 `publish/001`、公開資料夾，重新發佈，master 與 tag 推到私人 repo。
- [X] T080 稽核紀錄寫進 repo；跑情境 A 全部。
  - 2026-10-22：[audit-2026-10-22-earlier.md](./audit-2026-10-22-earlier.md)；pytest 2055、node 58、e2e 124/124、`scan_names.py` 未允許 0、`scan_personal.py` 不允許 0（每一項都看結束代碼，不接管線）。

---

## Dependencies & Execution Order

- **Phase 1 → Phase 2 → US1（Phase 3）→ US2（Phase 4）**：US2 的改寫工具要處理 US1 新寫的檔案與測試，所以在 US1 之後。
- **US3（Phase 5）**：依賴 Phase 2；`schedule`、`backup_db`、提示可以和 US2 平行。README（T036）在 US1 之後寫，才知道 setup 的實際文字；它要通過 US2 的掃描。
- **US4（Phase 6）**：依賴 US2 的 `--publish` 掃描（T027）；可以和 US3 平行。
- **Phase 7**：全部完成後。T045 在合併後，T046 在 T045 之後並要使用者確認，T047 和 T045／T046 同時進行。

### 平行機會

- US1：T004、T005、T006、T007、T008（不同檔案）；T009 可與 T010 平行。
- US2：T016、T017、T018。
- US3：T029、T030、T031；T037、T038 與其他 US3 task 平行。
- US3 與 US4 可以平行（不同檔案）。

## Implementation Strategy

- **MVP = US1**：別人能用自己的願望清單跑起來，使用者本人不受影響。
- 接著 US2（公開前一定要乾淨），再 US3（安裝說明與日常）、US4（發佈）。
- 每個 Phase 結束都跑全部測試與兩個掃描；每個 Checkpoint commit 一次，只在 worktree，不推送。
- 合併與公開都由使用者確認。
