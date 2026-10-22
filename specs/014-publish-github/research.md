# Research: 公開到 GitHub（014）

這份文件本身會公開：本機路徑一律寫成代稱（〈專案資料夾〉、〈使用者資料夾〉、〈前身專案資料夾〉），不寫 SteamID 與帳號名。

## 盤點時確認的前提（2026-10-18，程式掃描與實際查詢）

- git 追蹤 650 個檔案。程式掃描（HANDOFF.md 除外）：
  - 使用者本人的 SteamID 13 處、9 個檔；其他 SteamID 0 處。
  - Windows 絕對路徑 92 處、60 個檔：〈專案資料夾〉與它的舊名、worktree（`-012`、`-013`、`-015`、`-016`）、〈前身專案資料夾〉，以及測試裡的虛構路徑（例如 D 槽的工具資料夾）與系統路徑。
  - email 形式 2 處，都是 ssh remote 的 `git@github.com`；對話連結 0 處；帳號名 0 處；私鑰標頭 0 處。
- 使用者目前的願望清單 69 款，有 67 款出現在測試或公開檔案裡。`tests/fixtures/steam/wishlist_ok.json` 含 68 筆（排序、加入日期），`tests/unit/test_steam_store.py::test_wishlist_parse` 斷言筆數 68 與第一筆的值。
- Steam 內容描述（2026-10-18 以公開的 `IStoreBrowseService/GetItems` 查 261 款）：「成人性內容」8 款、「頻繁裸露或性內容」1 款，全部是使用者願望清單上的遊戲；其中 4 款出現在完整清單檔以外（最多的一款在 20 個檔，含 golden 頁；名稱只記在私人的 HANDOFF，這份文件公開，不寫出）。`tests/fixtures/steam/search_shiravune_{0,50,100}.json` 是發行商搜尋分頁的錄製結果，約 35 款「部分裸露或性內容」的視覺小說，不是使用者的清單。
- 自訂網址：`https://steamcommunity.com/id/<名稱>/?xml=1` 不需要金鑰，回 `<steamID64>`；不存在時回 `<error>The specified profile could not be found.</error>`。官方的 `ISteamUser/ResolveVanityURL` 沒有金鑰時回 HTTP 400「Required parameter 'key' is missing」。
- 願望清單：`IWishlistService/GetWishlist` 對公開的清單回 `items`；對不公開（friendsonly）的帳號回 `{"response":{}}`，現有程式已把它判為 `private`；帳號 0（不存在的帳號）回 HTTP 400。個人檔案 XML 的 `<privacyState>` 分得出 public／friendsonly／private。
- 參考資料集：001 SC-006 的目標是「至少 2,000 款含歷史」，當時實測 2,582 款、完整建立 35 分鐘。廣泛樣本（48 層、每層 25 款）需要 `STEAM_WEB_API_KEY`，沒有時停用；相關樣本來自願望清單遊戲的發行商與開發商目錄。`dataset_size` 的定義是「願望清單以外、有台灣區價格歷史的參考遊戲數」，使用者目前 2,632 款。
- 排程工作（執行身分 2026-10-18 analyze 後補查：LogonType Interactive、RunLevel Limited）：使用者現在的工作是 `conhost.exe --headless cmd.exe /d /c "〈專案資料夾〉\背景更新.cmd"`、工作目錄〈專案資料夾〉、每天 02:30、`StartWhenAvailable`、`ExecutionTimeLimit` 1 小時、`MultipleInstancesPolicy` IgnoreNew、電池時也執行。它的說明文字還是舊的（「每天 00:00……SteamSage2」）。
- 本機程式登錄是 `HKCU\Software\Google\Chrome\NativeMessagingHosts\com.sweetspot.edition`：每個 Windows 使用者只有一個。擴充功能的 manifest `key` 是公鑰，任何人載入未封裝項目都得到同一個擴充功能編號，本機程式的 `allowed_origins` 因此對每個人都成立。
- 這台電腦是 Windows 11 Home：沒有 Windows Sandbox、Hyper-V。

### 清理前後的數字（014 T001、T028；`inventory/` 的腳本對 worktree 執行）

| 時間 | pytest | node | 本人 SteamID | 其他 SteamID 形式 | Windows 絕對路徑 | email 形式 | 願望清單遊戲（名稱／只有 app id） | 內容描述 3／4 | Shiravune 作品 |
|---|---|---|---|---|---|---|---|---|---|
| 清理前（2026-10-18，T001） | 1759 | 56 | 13 處／9 檔 | 4（014 文件裡的虛構值） | 96 處／60 檔（含 014 契約的規則說明 4 處） | 6 處／3 檔（`git@github.com` 5、`noreply@anthropic.com` 1） | 33／10 款（處理完整清單檔與逐款表後仍會留下的） | 9 款 | 約 35 款 |
| 清理後（2026-10-18，T028） | 1903 | 56 | 0 | 19（全部是帳號 0 以下的虛構值） | 36 處／16 檔（測試的虛構路徑、系統路徑、規則說明；`scan_personal.py` 不允許 0） | 15 處／6 檔（全部是公開地址） | 29／10 款（選項 C 預期留下的零星例子） | 0 款 | 0 款（換成 144 個虛構作品，Steam 上查無此 app） |

- 清理後公開檔案裡的 app id 238 款：66 款沒有內容描述、20 款「部分裸露或性內容」（主流遊戲）、152 款查無此 app（虛構 id）；內容描述 3／4 為 0。
- `scripts/scan_personal.py`：不允許 0（50 處以上依規則允許，見 `docs/personal-scan.md`）；`scripts/scan_names.py`：未允許 0。

- 公開檔案裡出現的 app id：261 款（`tests/` 裡 258 款，其中 67 款在使用者的願望清單）。
- node 測試的指令是 `node --test "tests/extension/*.test.js"`（Node 24 的 `--test` 不接受資料夾）。

## R1 自訂網址怎麼換算（FR-002；外部依賴；使用者選定 2026-10-18）

- **決定**：用 Steam 社群個人檔案的公開 XML（`/id/<名稱>/?xml=1`），換算一次、存數字形式。新增一個可抽換的來源 `SteamCommunity`（憲章 VIII），只在第一次設定時使用，有速率限制與 Retry-After。
- 理由：不需要金鑰（Steam Web API 金鑰對新使用者是選用的）；同一份 XML 也給 `privacyState`，能把「不公開」說清楚。
- 替代：`ResolveVanityURL`（需要金鑰，等於把選用的金鑰變成必要）；從個人檔案 HTML 抓（格式更不穩定）。

## R2 第一次設定的入口（FR-001、FR-003、FR-014；CLI 形狀；使用者選定 2026-10-18）

- **決定**：
  - 新增 `sweetspot setup`：互動詢問願望清單網址，依序檢查 ITAD 金鑰 → 網址格式 → 帳號存在 → 清單讀得到，全部通過才寫 `sweetspot.toml`（預設值＋數字形式網址）。
  - `更新資料.cmd`：沒有 `sweetspot.toml` 時先執行 `sweetspot setup`，成功才繼續。
  - 其餘指令：沒有設定檔時，若是可以互動的終端機，就直接進入同一段設定流程；否則拒絕並以新的結束代碼 **5（還沒設定）** 結束，不建立任何檔案。
  - 「可以互動」= 標準輸入是終端機，而且沒有設定 `SWEETSPOT_BACKGROUND=1`。`背景更新.cmd` 設定這個變數，不依賴 headless 主控台的 `isatty()`（NUL 的教訓：裝置判斷不可靠，見 2026-10-18 的 UTF-8 修正）。
  - `load_config` 不再自動建立設定檔；`DEFAULT_TOML` 的 `wishlist.url` 改成空字串，`[legacy] cache_path` 改成空字串。
- 理由：設定是一次性的互動步驟，和 `update` 分開最好測試；背景執行用明確的旗標判斷。結束代碼 5 和 016 的 4（要先搬家）是同一種「不是失敗、要使用者先做一步」。
- 替代：把詢問寫在 `update` 裡（`update` 的測試都要處理互動）；設定檔不存在時寫一份範本讓使用者自己改（違反 FR-001「詢問」）。

## R3 願望清單的檢查與錯誤說明（FR-003）

| 情況 | 判斷 | 說明 |
|---|---|---|
| 格式錯誤 | 不符合四種網址形式 | 列出接受的形式 |
| 帳號不存在 | XML `<error>` 或 GetWishlist HTTP 400 | 「找不到這個帳號」 |
| 不公開 | XML `privacyState` 不是 public，或 GetWishlist 回 `{"response":{}}` | 到 Steam「隱私設定 → 遊戲詳細資料」設為公開 |
| 讀到 0 款、個人檔案公開 | `items` 為空 | 可能是清單空的，或遊戲詳細資料不公開；請使用者確認後才建立（Edge Case「願望清單是空的」） |
| （2026-10-22 稽核補記）暫時連不上 | 個人檔案或 GetWishlist 的其他來源錯誤 | 「請稍後再試；什麼都沒建立」，結束代碼 1（不重新詢問：換網址也一樣連不上）；實作從 2026-10-18 起就是這樣，見 contracts/cli.md §1 |

## R4 每日排程的註冊（FR-012、FR-012a；CLI 形狀；使用者選定 2026-10-18）

- **決定**：新增 `sweetspot schedule install|uninstall|status [--name 名稱] [--replace]`。重用 016 `migrate.py` 的 `Scheduler`（PowerShell 執行、查詢、匯出、註冊），由程式依上面「排程工作」的設定產生工作 XML（02:30、headless、補跑、1 小時上限、IgnoreNew、電池時也執行），說明文字改成正確的現況。
  - 同名工作已存在且指向這個資料夾 → 說明已註冊，不改（`--replace` 才重建）；指向別的資料夾 → 拒絕並說明（FR-012a），`--replace` 才取代。
  - `uninstall` 只移除指向這個資料夾的同名工作。
- 理由：和 015 的 `sweetspot host install` 同一種形狀；用假的 Scheduler 就能測試；驗收時可用測試名稱。
- 替代：README 列 PowerShell 指令讓使用者自己貼（手動、容易打錯、不好測）；放在 `scripts/` 的 .ps1（又多一種語言、不好測）。

## R5 沒有私人 repo 時的雲端備份（FR-013）

- **決定**：`scripts/backup_db.py` 找不到名為 `private` 的 git remote 時，印出「略過雲端備份：沒有名為 private 的 git remote」並以 0 結束；日誌結果行寫「backup 結束：代碼 0……略過」。`背景更新.cmd` 不改。`private` remote 存在但 `gh` 失敗時照舊算失敗（那是使用者本人的設定出錯）。

## R6 參考資料集還小的提示（FR-014a；門檻；使用者選定 2026-10-18）

- **門檻**：`dataset_size` < **2,000** 款。理由：001 SC-006 把「參考資料集至少 2,000 款含歷史」定為建立參考資料集的完成條件，之後所有模型驗證都是在這個規模之上做的（例如 2,583 款的驗證資料集）。使用者本人目前 2,632 款，不會看到提示。
- 提示由核心算出（`update`／`report` 的決策紀錄多一個選用欄位），HTML 報告頁首與擴充功能都讀這個欄位（憲章 VII）；不改預測、甜蜜價與信心等級（不觸及原則 IV）。
- 提示內容：目前幾款、門檻、怎麼補完（`uv run sweetspot reference` 一次，時間由 014 T045 實測後填入；或每晚 120 秒累積），以及沒有 `STEAM_WEB_API_KEY` 時廣泛樣本停用、可能到不了門檻。
- 替代：用驗證資料集的 2,583 款（數字更精確，但它是某一天的結果，不是設計目標）；用比例（沒有依據）。
- **實測（2026-10-21～22，014 T045）**：從零安裝執行 `uv run sweetspot reference`，合計約 2 小時 18 分（願望清單 69 款、有 `STEAM_WEB_API_KEY`；中途因 Steam 商店故障與程序被停掉中斷兩次，每次都接著做），
  看完整份 Steam 遊戲清單（195,054 款）後停在 **1,659 款**：48 個分層有 7 個填不滿（都是售價 NT$1,000 以上的獨立遊戲），原作者的資料集也是這 7 層沒滿，超過 2,000 是因為多了前身專案的匯入。
  所以門檻 2,000 維持（它是模型驗證時的規模），但「做完還不到門檻」要和「還沒做完」分開說（使用者 2026-10-22 選 A；014 T048，data-model `sampling`）。
  提示裡的時間寫「約 2～3 小時」。

## R7 個人資訊掃描（FR-005、FR-016b）

- **決定**：新增 `scripts/scan_personal.py`，架構照 016 的 `scripts/scan_names.py`（規則表、第一條符合的規則決定類別、沒有規則允許就算違規、每條規則有該中與不該中的樣本測試）。
- 兩層：
  1. **離線、通用的類別**（master 的自動測試，公開版的 repo 裡也照樣有效）：SteamID64 形式（`7656119` 開頭 17 位數，虛構值除外）、Windows 絕對路徑（系統路徑與測試用虛構路徑除外）、email 形式（`git@github.com`、noreply 地址除外）、對話連結、私鑰標頭。
  2. **發佈時才做的類別**（需要本機的值或網路）：使用者兩把 API 金鑰的值（從環境讀，只報位置）、帳號名（從 git remote 取得；LICENSE 是例外）、`sweetspot.toml` 裡的 SteamID、使用者願望清單的排序與加入日期（以本機資料庫比對）、Steam 內容描述的線上查詢（R9）。
  - （2026-10-22 稽核補記）實作時改了兩點，以 contracts/scan-personal.md 為準：帳號名只讀 git 設定，所以移到離線類別（master 的自動測試就會查）；願望清單只查加入日期，不查排序（014 T017：排序是 1、2、3 這種小整數，判斷不了）。
- 例外清單由掃描產生，寫在 `docs/personal-scan.md`（照 016 的 `docs/legacy-names.md` 做法）。

## R8 代稱（FR-006、FR-007）

| 值 | 換成 | 適用 |
|---|---|---|
| 使用者的 SteamID | `76561197960265728`（帳號 0：Steam 規定不會分給任何人） | 程式、測試、腳本、測試資料 |
| 使用者的 SteamID | `〈SteamID〉` | `specs/`、`docs/` |
| 〈專案資料夾〉與它的舊名、worktree 路徑 | `〈專案資料夾〉`、`〈專案資料夾〉-016` 等 | `specs/`、`docs/`、README |
| 〈前身專案資料夾〉 | `〈前身專案資料夾〉` | 同上；`scripts/scan_names.py` 的規則同步調整 |
| 〈使用者資料夾〉 | `〈使用者資料夾〉` | 同上 |

- 換代稱用一支一次性的改寫腳本（放在本 feature 目錄，照 016 的 `rename_tool.py`），逐檔列出改了什麼；改完重跑掃描與全部測試。`specs/` 的原型腳本換成代稱後不能直接執行，是預期的（spec Edge Cases）。

## R9 NSFW 遊戲（FR-008b）

- **判斷**：Steam 內容描述編號 3（成人性內容）或 4（頻繁裸露或性內容）。
- **公開檔案裡現有的**：上述 4 款，以及 Shiravune 搜尋結果。換成**虛構的名稱與 app id**：
  - app id 用個位數不是 0 的數字（Steam 的 app id 通常是 10 的倍數，不保證），發佈前以 GetItems 確認查無此 app；
  - 出現最多的那一款在測試裡扮演「版本追蹤遇到組合包而拒絕」的例子：改寫時保留它在測試資料中的結構與關係，只換名稱與編號；
  - golden 頁由測試資料重新產生，逐字比對只差這些名稱與編號。
- **以後不再帶回來**：不做離線清單——任何寫進 repo 的 NSFW 清單（即使只有 app id 或雜湊）本身就透露了使用者清單上有哪些 NSFW 遊戲。改成兩個線上檢查點：`record_fixtures.py` 錄製時查內容描述並排除；發佈步驟查全部出現的 app id 與名稱（名稱以本機資料庫的商品名稱對照成 app id）。
- 替代：重新錄製另一款真實遊戲（要另找情況相同、沒有性內容的遊戲，而且以後錄製可能又變）。

## R10 完整清單與逐款表（FR-008、FR-008a）

- `wishlist_ok.json`：只留測試用得到的筆數（測試斷言要跟著改），排序與加入日期改成虛構值；錄製腳本 `record_fixtures.py` 在錄 GetWishlist 時就截斷筆數、改寫排序與日期，並排除 R9 的遊戲。
- `docs/model/comparisons.md` 的逐款表：遊戲名稱換成代號（「遊戲 01」……），數字、判定與結論不變；文件開頭加一段日期註記說明這次改寫（憲章 IV 要求的比較紀錄仍然完整）。

## R11 發佈步驟（FR-016、FR-016a、FR-017、FR-018；紀錄方式由使用者選定 2026-10-18）

- **決定**：`scripts/publish.py`（維護者工具，留在公開 repo 裡也無妨，沒有個人值）：
  1. 內容來源是 master 已提交的版本（`git archive`），不是工作目錄。
  2. 公開資料夾預設是〈專案資料夾〉旁邊的 `SweetSpot-public`（參數可改）；第一次發佈時 `git init`，在那個 repo 的本機設定寫入 noreply 作者（`<編號>+<帳號>@users.noreply.github.com`，以 `gh api user` 取得）。
  3. 整份換掉工作資料夾的檔案（排除清單除外；master 刪掉的檔案也刪掉）。
  4. 掃描（R7 兩層）、在工作資料夾跑 `uv sync`、pytest、node --test；e2e 需要 Chrome，只在 master 跑。
  5. 全部通過才 commit；訊息：「SweetSpot 發佈 YYYY-MM-DD」＋這次包含的 master commit 標題（以標題為準，標題本來就不含對話連結；發佈前會顯示讓使用者確認）。
  6. 不推送；印出 `gh repo create`（第一次）或 `git push` 的指令，由使用者確認後執行。
- **發佈紀錄（使用者選定）**：在 master 的對應 commit 打 annotated tag `publish/NNN`（訊息含公開 commit 的雜湊與時間），隨 `git push private --tags` 進私人 repo。下一次發佈從最新的 `publish/*` 算範圍。
  - 替代：一個排除在公開版以外的追蹤檔（每次發佈都要多一個 commit）；只寫在 HANDOFF（不好用程式讀）。
- **排除清單**：`HANDOFF.md`。盤點沒有發現其他只屬於使用者本人的追蹤檔（`sweetspot.toml`、`data/`、`extension/data/` 本來就不進 git）。

## R12 安裝說明（FR-011、FR-015、FR-018a）

- README 重排：開頭一兩句英文說明；「只支援 Windows、台灣區」；「從零安裝」一節（前置需求：Windows 10/11、Python 3.12 以上、uv、git、Chrome；gh 只有雲端備份需要；node 只有開發需要）；兩把金鑰（ITAD 必要、Steam Web API 選用但參考資料集要它才到得了門檻；怎麼申請、`setx`／系統設定寫成使用者層級環境變數、設定後重開視窗、不要寫進檔案）；第一次設定與更新；參考資料集；排程註冊；擴充功能（載入未封裝項目）；本機程式（`sweetspot host install`）；「公開 repo 是發佈快照，PR 的處理方式」；ITAD 條款與每人自己的金鑰。
- 實測時間（第一次更新、參考資料集）在驗收時量，寫進 README。
- LICENSE：MIT，著作權人是使用者的 GitHub 帳號名（使用者 2026-10-18 選定）。

## R13 從零安裝的驗收（SC-003；clarify 2026-10-18）

- 同一個 Windows 帳號、〈專案資料夾〉以外的全新資料夾（從發佈產生的公開資料夾複製）；另一個 Chrome 設定檔載入擴充功能；`sweetspot schedule install --name "SweetSpot 驗收"`，確認後 `uninstall`；`sweetspot host install` 從測試資料夾執行，確認後在〈專案資料夾〉重新執行改回；白天做。
- 結束後確認：使用者的排程工作 XML 與驗收前相同、本機程式登錄指回〈專案資料夾〉、當晚 02:30 成功。

## R14 使用者本人的環境（FR-004、SC-006）

- 使用者的 `sweetspot.toml` 已有網址與前身專案路徑，`DEFAULT_TOML` 改成空字串不影響（合併時以檔案裡的值為準）。
- `背景更新.cmd` 只多設一個環境變數；`更新資料.cmd` 多一段「沒有設定檔就先 setup」。
- 合併後不需要搬家或重新安裝；可以選擇用 `sweetspot schedule install --replace` 把排程的說明文字更新成現況（不是必要）。
