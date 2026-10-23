# Quickstart: 驗證公開到 GitHub（014）

每個情境寫明前提、步驟與預期結果；量到的時間與結果在實作時補在各情境下方。路徑一律用代稱。

## 情境 A：自動測試（每次修改後）

```
uv run pytest
node --test "tests/extension/*.test.js"
uv run python tests/extension/e2e.py
uv run python scripts/scan_names.py
uv run python scripts/scan_personal.py
```

預期：全部通過；測試數量不少於清理前（SC-001）；兩個掃描都是 0 個不允許。

**結果（2026-10-18，014 T042，worktree 最後狀態）**：pytest 1950 通過（清理前 1759）、node 57、e2e 124/124；`scan_personal.py` 不允許 0（76 處依規則允許）、`scan_names.py` 未允許 0。

## 情境 B：第一次設定（US1；測試資料夾，不碰〈專案資料夾〉的設定檔）

在一個暫存資料夾（只有程式，沒有 `sweetspot.toml`）：

1. 暫時移除 `ITAD_API_KEY` 後執行 `uv run sweetspot setup` → 說明怎麼申請與設定，結束代碼 5，沒有建立任何檔案。
2. 設回金鑰，依序輸入：格式錯誤的網址、不存在的自訂網址、不公開的帳號 → 每次說明原因並重新詢問。
3. 輸入一個公開帳號的自訂網址 → 「已記成這個帳號：…」，設定檔裡是數字形式的願望清單網址。
4. `SWEETSPOT_BACKGROUND=1` 下在沒有設定檔的資料夾執行 `uv run sweetspot update` → 結束代碼 5，資料夾裡沒有新檔案。
5. 在〈專案資料夾〉執行 `uv run sweetspot update --skip-reference` → 不會被詢問，行為不變（FR-004）。

**結果（2026-10-18，014 T015，真實 Steam，暫存資料夾）**：
- 1 沒有金鑰：結束代碼 5，資料夾是空的，說明含申請網址、PowerShell 設定指令、「關掉視窗重開」。
- 2 依序輸入商店頁網址（格式錯誤）、不存在的自訂網址（「找不到這個帳號」）、一個個人檔案不公開的帳號（隱私設定的說明），最後輸入使用者本人的數字網址 → 讀到 69 款，設定檔是數字形式的網址，結束代碼 0。
- 3 自訂網址的成功路徑：使用者本人的帳號沒有自訂網址，只由單元測試涵蓋。
- 4 `SWEETSPOT_BACKGROUND=1` 在空資料夾執行 `update` → 結束代碼 5，資料夾仍是空的；worktree 沒有設定檔時，以 cmd 執行 `更新資料.cmd --no-pause`（標準輸入不是終端機）→ 結束代碼 5，沒有建立設定檔。
- 5 合併前〈專案資料夾〉還是 master，由 `tests/contract/test_cli_setup_guard.py::test_existing_settings_are_used_as_before` 涵蓋，合併後在情境 H 實測。

## 情境 C：掃描抓得到（US2、SC-002）

在測試裡（`tests/unit/test_scan_personal.py`）放入一個 SteamID、一個本機路徑、一個 email、一個對話連結 → 各自被找到並指出檔案與行號；`--publish` 的金鑰類別以假金鑰驗證只印位置。

**結果**：`test_scan_personal.py`、`test_scan_personal_publish.py` 全部通過。另以使用者真實的金鑰、設定檔與資料庫（唯讀）對 014 分支的 `git archive`（扣掉 HANDOFF.md）跑一次發佈時的掃描：682 個檔案、不允許 0、32 秒；第一次試跑時資料庫裡名為「Mirror」「Put in」的遊戲撞到一般英文，改成英數名稱至少 8 個字元且有字界、中日韓至少 3 個字後為 0（commit a29fa36）。

## 情境 D：參考資料集提示（FR-014a）

在測試資料庫（參考資料集 < 2,000 款）產生報告 → HTML 頁首與擴充功能資料檔都有同樣的款數提示；在〈專案資料夾〉的真實資料副本產生報告 → 沒有提示（2,632 款）。決策逐款與加提示前相同。

**結果**：`test_reference_notice.py`、`test_report_flow.py::test_a_small_reference_dataset_is_noted_in_the_record_and_the_page`、lib.test.js 通過；使用者真實資料庫以 014 的定義唯讀計算 `dataset_size` = 2,632 ≥ 2,000，不會看到提示。golden 頁不變。

## 情境 E：沒有私人 repo 的雲端備份（FR-013）

在沒有 `private` remote 的資料夾執行 `uv run python scripts/backup_db.py` → 「略過雲端備份」，結束代碼 0；日誌結果行附「略過」。在〈專案資料夾〉執行 → 照常上傳。

**結果**：`test_backup_db.py::test_without_a_private_remote_the_backup_is_skipped` 通過；〈專案資料夾〉的照常上傳在合併後的情境 H 確認。

## 情境 F：發佈（US4）

1. `uv run python scripts/publish.py --dry-run` → 列出要公開的檔案（沒有 `HANDOFF.md`）、訊息草稿；公開資料夾不留下任何改變。
2. `uv run python scripts/publish.py` → 公開資料夾只有 1 個 commit、作者與提交者是 noreply 地址；master 多一個 `publish/001` tag；什麼都沒推送。
3. 在 master 做一個測試用的小 commit，再發佈 → 公開資料夾多 1 個 commit，`git diff` 只有那個修改；master 多 `publish/002`。（驗證完把兩個 tag 與公開資料夾恢復成只有初次公開的狀態，再交給使用者決定推送。）
4. 在要發佈的內容裡故意留一個 SteamID → 發佈停止，沒有 commit、沒有 tag。

**結果**：`tests/integration/test_publish.py` 13 項通過（暫存 repo、假的 gh／掃描／測試）。另在 014 分支的暫存 clone（分支改名為 master）以真實的掃描與測試跑 `publish.py --dry-run`：688 個檔案、掃描不允許 0、公開資料夾的 pytest 與 node 57 通過、94 秒（plan 目標 10 分鐘內），公開資料夾回到原樣。試跑時找到兩個問題並修正：第一次發佈時檔案還沒暫存，掃描的測試（`git ls-files`）在公開資料夾失敗（90f1b58）；公開資料夾沒有 remote，掃描找不到 LICENSE 那一行的帳號名（a77ab2f：第一次發佈時加上 `origin`）。這個 clone 沒有使用者的設定檔與資料庫，帳號以外的「本人的值」由上面情境 C 的真實資料試跑涵蓋。

**第 3 步的真實執行**（2026-10-23，014 T046 推送前）：在暫存的 master clone 與公開資料夾 clone 上做（不動真的 master 與公開資料夾，所以不用還原）；
改、刪、加各一個檔，正式發佈以 0 結束（166 秒）：公開資料夾多 1 個 commit、三種改變都反映、和 master 的追蹤檔案逐檔相同、有 `publish/002`，掃描與測試都是真的。細節在 tasks.md 的 014 T046。

**第一次設定的時間**（plan Performance Goals）：情境 B 的真實執行，從輸入網址到建立設定檔約數秒（3 個請求，間隔 1–1.5 秒），在 1 分鐘的目標內。

## 情境 G：從零安裝（US3、SC-003；clarify 2026-10-18 的做法，白天做）

1. 把公開資料夾複製到〈專案資料夾〉以外的新資料夾（只有程式；金鑰在使用者環境變數裡）。
2. 照 README 一步一步做：安裝前置工具（已裝的記錄版本）、`更新資料.cmd`（第一次設定 → 更新 → 報告）、`uv run sweetspot reference`、在**另一個 Chrome 設定檔**載入擴充功能、`uv run sweetspot schedule install --name "SweetSpot 驗收"`、`uv run sweetspot host install`。
3. 記錄每一步的時間；遇到 README 沒寫的事，補進 README。
4. 確認：報告是測試帳號的願望清單；擴充功能在 Steam 頁顯示面板；「SweetSpot 驗收」工作存在並指向新資料夾。
5. 還原：`schedule uninstall --name "SweetSpot 驗收"`；在〈專案資料夾〉執行 `uv run sweetspot host install`；確認使用者的「SweetSpot 每日背景更新」XML 與驗收前匯出的一樣、本機程式登錄指回〈專案資料夾〉，當晚 02:30 成功。

**結果（2026-10-21 21:13～10-22 00:30，014 T045；晚上做，排程在 02:30 前移除）**：
- 0 驗收前把使用者的排程工作 XML、本機程式登錄值、登記檔與啟動檔存成基準（放在 repo 以外：`data/` 底下多一個資料夾會讓 `publish.py` 因為工作目錄不乾淨而拒絕）。
- 1 `publish.py --dry-run` 130 秒（688 檔、掃描不允許 0、公開資料夾的 pytest 與 node 57 通過、留下的改變 0）；正式執行 133 秒，公開資料夾 1 個 commit、作者與提交者都是 noreply 地址、master 打 `publish/001`、沒有推送。
  公開資料夾 `git clone` 到〈驗收資料夾〉，`uv sync` 2 秒（套件已在 uv 快取；沒有快取的電腦會更久）。前置工具：uv 0.11.26、git 2.55.0、Python 3.12.13（uv 管理）、Windows 11 10.0.26200。
- 2 雙擊 `更新資料.cmd`：使用者在視窗實際貼上自己的願望清單網址（第一次真正的互動輸入），設定檔是數字形式的網址；
  第一次更新 69 款 431 秒（含每日 120 秒的參考資料集小批次，累積到 58 款）、報告 0.5 秒，都是 0；頁首提示「參考資料集目前 58 款……」與 contracts/cli.md §6 相同。
  `setup` 不在日誌留結果行（它在設定檔與日誌設定之前執行），時間只能由設定檔的建立時間推。（已由 014 T050 修正：建立或改寫設定檔時留一行。）
- 3 `uv run sweetspot reference`：合計約 2 小時 18 分，分四次——41 分後因 Steam 商店整站 502（steamstat.us 也顯示 Bad Gateway）以 1 結束；
  商店還沒恢復時再跑 22 秒以 1 結束；恢復後約 59 分時被 Claude Code 因記憶體不足停掉（留下的寫入鎖在下次執行時因程序已不在而被接手，中斷的執行標記為 interrupted）；
  最後 38 分以 0 結束（`stopped: complete`、`population_exhausted: true`，看過 195,054 款）。每次都接著上次的進度，「可以中斷，下次接著做」成立。
  **結果 1,659 款，低於 2,000**：48 個分層有 7 個填不滿（都是售價 NT$1,000 以上的獨立遊戲，2015 年以前那一層是 0），〈專案資料夾〉的參考資料集也是這 7 層沒滿（使用者的 2,632 款多出來的是前身專案的匯入）。
  所以新安裝做完 `reference` 之後，報告與擴充功能仍顯示「參考資料集目前 1,659 款（建議至少 2,000 款）……補完：執行 uv run sweetspot reference」，而再執行也不會增加——**待使用者決定**（014 T045 註記的選項 A／B／C）。（使用者選 A，已由 014 T048 修正：補完後改說「已補完：共 N 款，少於…」。）
- 4 `schedule install --name "SweetSpot 驗收"` 2 秒、0；匯出的 XML 和使用者的工作只差名稱、路徑、說明文字、兩個沒有啟用的閒置設定與開始時間是否帶時區；隨即 `uninstall`、0。
  還沒執行過的工作，`schedule status` 直接印出 Windows 的原始值「上次 11/30/1999 00:00:00，結果 267011」（267011 = 還沒執行過）。（已由 014 T051 修正：改寫「上次：還沒執行過」。）
- 5 〈驗收資料夾〉重新產生報告 6 秒；`host install` 1 秒、`host status` 全部 True。使用者在另一個 Chrome 設定檔載入〈驗收資料夾〉的 `extension/`：編號相同、彈出視窗顯示 1,659 款的提示、遊戲頁面板正常；
  指定 Cyberpunk 2077 的版本 4.6 秒、ok，改到的是〈驗收資料夾〉的設定檔。
- 6 還原：在〈專案資料夾〉`host install`；登錄指回〈專案資料夾〉，登記檔、啟動檔、排程工作 XML 都和基準的雜湊相同，`Chromium` 與 `.test` 的登錄不存在，排程只剩「SweetSpot 每日背景更新」。

## 情境 H：合併後的使用者環境（SC-006）

合併到 master 後連續 3 晚，`data\logs\sweetspot-YYYYMMDD.log` 有 update、report、backup 三行結果，整體代碼 0 或 2，雲端備份照常上傳（使用者確認）。
