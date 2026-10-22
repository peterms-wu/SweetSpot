# Research: Chrome 擴充功能（feature 011）

原型都在 [prototype/](prototype/)。資料檔 `prototype/ext/data/` 與輸出 `prototype/out/` 不進版控（含願望清單）。
Steam 頁面都是**未登入**、唯讀地讀取（2026-09-27）。瀏覽器用 Playwright 1.63 的 Chromium，因為品牌版 Chrome 137 以後忽略 `--load-extension`。
使用者的 Chrome 154 以「載入未封裝項目」手動載入，讀檔的程式路徑相同；SC-004 仍要在使用者的 Chrome 上實測一次（quickstart §4）。

## R0 原型（真實資料）

### R0.1 改寫資料檔後不重新載入就讀到新檔（P1，spec FR-006、FR-011、SC-004、SC-005）

`p1_reload.py`：最小 MV3 擴充功能（`prototype/ext/`）。Service Worker 用 `fetch(chrome.runtime.getURL('data/…json'), {cache: 'no-store'})` 讀自己的檔案；
彈出視窗和頁面內容腳本都用 `chrome.runtime.sendMessage` 向 Service Worker 要資料（資料檔不必列為 `web_accessible_resources`，網頁讀不到）。

| # | 情境 | 結果 |
|---|---|---|
| 1 | 第一次讀：彈出視窗、圖示數字、遊戲頁、30 分鐘的 alarm 已建立 | ✅ 彈出視窗 49–60 ms 顯示 |
| 2 | 先寫暫存檔再改名（報告的寫法），**不重新載入**，重開彈出視窗、重新載入頁面 | ✅ 都讀到新檔；圖示在打開彈出視窗時更新 |
| 3 | 直接覆寫檔案，只執行 alarm 的處理（沒有任何頁面） | ✅ 圖示更新 |
| 4 | Service Worker 被停止後（閒置約 30 秒就會被 Chrome 停止）再打開彈出視窗 | ✅ 讀到新檔；「現在買」0 款時圖示不顯示數字 |
| 5 | 寫到一半的檔案 | ✅ 當成「損壞」，圖示顯示「!」 |
| 6 | 檔案不存在 | ✅ 說明「沒有資料」 |

13/13 通過，約 4 秒。請求紀錄：2 個 Steam 文件（測試用的靜態頁）＋ 6 個擴充功能自己的檔案，**其他 0 個**。

- **Decision**：採用原本的做法（spec Clarifications：擴充功能讀自己資料夾中的檔案）。不需要替代做法。
- **Rationale**：Chrome 對未封裝的擴充功能每次都從磁碟讀；`cache: 'no-store'` 讓瀏覽器快取也不會介入。
- **Alternatives**（不需要）：本機伺服器、native messaging、使用者手動匯入檔案。

### R0.2 頁面的插入方式（P2–P4，spec FR-012–FR-016、SC-002、SC-003、SC-006）

**遊戲頁**（`p2_probe.py` 不載入擴充功能；`p3_live.py` 載入原型擴充功能）。抽 16 款：11 款一般遊戲（含 5 款有多個版本、
Cyberpunk 2077 使用者指定的組合包 `bundle/32470`、成人遊戲 NUKITASHI），以及 2 款無法預測的遊戲。

| 檢查 | 結果 |
|---|---|
| 追蹤的購買選項（`version.option` 的 `sub`／`bundle` 編號）在頁面上找得到 | **15/15**（`#game_area_purchase form input[name=subid|bundleid]`） |
| 頁面價格（該選項的 `data-price-final`，單位是分）＝紀錄的 `current.price_cents` | **14/14** 有現價的遊戲；範例分季作品（無法預測）頁面有價、紀錄沒有，不並列 |
| 面板位置：`#game_area_purchase` 正前方 | 16/16 |
| 面板出現時間 | DOMContentLoaded 後 **200–246 ms**；從開始導覽算起 0.96–2.1 秒（含 Steam 本身的載入） |
| 不在資料中的遊戲（CS2） | 沒有面板 |
| 已擁有（`.game_area_already_owned`，用測試頁模擬；未登入看不到） | 面板縮成一行並註明 ✅ |
| 範例未發行遊戲（尚未發行） | 頁面有 `#game_area_purchase` 但沒有購買選項；面板只顯示原因 ✅ |
| 年齡確認 | 帶年齡 cookie 時不出現；年齡確認頁網址是 `/agecheck/app/<id>/`，不符合內容腳本的網址規則，本來就不會執行 |

**願望清單頁**（`p4_wishlist.py`，同一份清單，裝與不裝擴充功能各跑一次）：

| 檢查 | 結果 |
|---|---|
| 捲動的元素 | 列表在內層的 `div` 捲動（`document` 不捲），要用滑鼠滾輪；每次 350 px、每步等 1 秒 |
| 列的結構 | 列 = `[data-index]`；每列有 3 個 `a[href*="/app/<id>"]`：圖片（含 `img`）、**名稱（只有文字、沒有子元素）**、價格（含 `div`） |
| 插入點 | 列本身是 CSS grid，區域為 `title`（名稱）／`mid`／`lower`／`purchase`；**`mid` 就在名稱正下方而且原本是空的**。把一行放在 `mid` 區元素的最前面 |
| 第一版的錯誤 | 先試著把那一行插在名稱後面：在 1280 px 被擠到名稱右邊、名稱被截斷；改成讓名稱容器換行後，**名稱被擠出可視範圍**（容器高度固定）。截圖才發現，所以改用 `mid` 區 |
| 版面 | 1280 px 與 700 px 下，列高都維持 174 px（裝與不裝相同）；截圖中名稱、日期、標籤、價格都在 |
| 從頭捲到尾 | 產生的 **59 列都恰好一行**；0 重複；0 列在 1 秒後仍缺少（FR-015） |
| 9 款沒出現 | 裝與不裝擴充功能都缺同樣 9 款（多半是成人內容，例如範例遊戲戊、範例遊戲己）：Steam 對未登入的訪客不列出。登入後的情形在使用者的 Chrome 上確認（quickstart §4） |
| 滑鼠移上 | 原生的 `title` 提示顯示前三個原因 ✅ |
| 改版的測試頁（名稱連結裡有 `span`） | 0 行，頁面不變（FR-016） |
| React 錯誤 #418 | 裝與不裝擴充功能**都會出現**，是 Steam 自己的 hydration 錯誤，和擴充功能無關 |

- **Decision**：
  - 遊戲頁：面板以 shadow DOM 插在 `#game_area_purchase` 前面；頁面現價用追蹤選項的 `data-price-final`，只在該區塊的價格文字含 `NT$` 時並列（憲章 IX）。
  - 願望清單頁：`MutationObserver`（每個畫面更新最多處理一次）掃描 `[data-index]` 列；名稱 = 沒有子元素且有文字的 App 連結；
    插在同一個 grid 中 `grid-row-start` 為 `mid` 的元素最前面；列被重複使用時，依那一行的 `data-app` 判斷要保留、替換或移除。
    找不到名稱或 `mid` 區就跳過那一列（不猜位置）。
- **Rationale**：不改 Steam 任何元素的樣式；不依賴會變的 class 名稱，只依賴連結網址、`data-index` 與 grid 區域名稱。
  Steam 改版時最可能的結果是「不顯示」，而不是「顯示在錯的地方」。
- **Alternatives**：用 class 名稱定位（每次改版都會變）；在名稱後面插入（擠壓或遮住名稱，已實測否決）；浮在列上方的絕對定位（會遮住 Steam 的內容）。

### R0.3 資料檔的大小與時間（P0，spec FR-001、FR-007、SC-007）

`p0_export.py` 用最新的正式紀錄（`20260927T050639Z`，68 款、6 個組合包）：

| 項目 | 結果 |
|---|---|
| 檔案大小 | **134 KB**（spec 上限 500 KB） |
| 產生並寫檔 | **9 ms**（報告中決策輸出已經在記憶體中，不必重讀紀錄；spec 上限 0.5 秒） |
| 資料時間 | 65 款有現價；`current.confirmed_at` 的中位數 = 2026-09-27 05:06:12Z（全部相同） |

- **資料時間用 `confirmed_at`，不是 `observed_at`**（clarify 時 spec 寫了 `observed_at`，plan 已改）：`confirmed_at` 是「現價最後確認時間」
  （每日快照或 ITAD 的已知至取較新的一個，報告上的「最後確認」），`observed_at` 是那一筆價格觀測的時間。目前兩者在所有紀錄中都相同，
  但價格沒變、只被再次確認時語意不同；「資料是否過舊」要看的是有沒有再確認。

### R0.4 對外網路請求 0 次（P1、P3，spec FR-004、SC-005）

| 檢查 | 結果 |
|---|---|
| 所有由擴充功能程式發出的請求（CDP `Network.requestWillBeSent` 的 initiator 含 `chrome-extension://`），16 個遊戲頁＋測試頁 | **0** |
| Service Worker 發出的請求 | 0（只讀自己的檔案） |
| Service Worker 嘗試連 `https://example.com/` | **被 CSP 擋下**（`connect-src 'self'`） |

- **Decision**：三道保護。(1) manifest 的 `extension_pages` CSP：`default-src 'self'; connect-src 'self'`，彈出視窗與 Service Worker 連不了外部；
  (2) 內容腳本不含任何網路 API（靜態測試檢查 `fetch`、`XMLHttpRequest`、`WebSocket`、`EventSource`、`sendBeacon`、`importScripts`、`http` 字串）；
  (3) 端對端測試記錄擴充功能發出的請求 = 0。權限只有 `alarms`；沒有 `host_permissions`、`cookies`、`storage`、`tabs`。

## R1 資料檔：誰產生、產生什麼

- **Decision**：新模組 `src/steamsage/report/extension.py`，屬於呈現層：輸入是報告用的同一個決策字典（`decision_to_dict`），輸出是 `steamsage.extension/1`
  的 JSON（[contracts/extension-data.md](contracts/extension-data.md)）。**會出現在 HTML 報告的句子由同一段 Python 產生**：
  把 `report/html.py` 中組句子的部分（版本說明、組合包指引、組合包卡片的各行）拆成回傳純文字的函式，HTML 和擴充功能資料都呼叫它們。
  擴充功能只做 spec FR-005 允許的格式化（千分位、百分比、台北時間），以及比較「現在 − 資料時間 > 26 小時」。
- **Rationale**：憲章 VII「同一份核心結果在不同呈現層顯示一致的數值與結論」：句子只有一個來源，就不會出現兩種說法；JS 端很薄，測試量小。
  拆函式時 HTML 的輸出必須逐位元組不變（SC-009，validation 用同一份紀錄比對）。
- **Alternatives**：JS 重寫組句子的邏輯（兩份實作會漂移）；直接把正式紀錄（約 1 MB，含曲線）給擴充功能（大、而且 JS 要懂整個契約）。

## R2 何時寫、寫到哪裡

- **Decision**：
  - 只在 `report` 的**正式**執行（`official`：沒有 `--as-of`、不是規則預覽）寫；寫在 HTML 報告之後、正式紀錄保存之後。
  - 位置：設定檔所在資料夾下的 `extension/data/steamsage-extension.json`（專案根目錄的 `extension/` 就是要載入的擴充功能資料夾）。
    只有 `extension/manifest.json` 存在時才寫，所以測試與沒有擴充功能的環境不會多出資料夾。
  - 寫法：暫存檔再改名（沿用 `write_text_atomic`）。
  - 寫檔失敗：報告照常完成；`report` 的摘要多 `extension` 欄位（路徑或錯誤），印出提醒，結束代碼為部分成功（2）。
  - `.gitignore` 加 `extension/data/`。
- **Rationale**：FR-001–FR-003；非正式執行不能蓋掉正式結果；失敗隔離（憲章 III），但要讓使用者看得到（背景執行的日誌會記錄結束代碼 2）。
- **Alternatives**：另外一個 `steamsage export` 指令（排程與 `更新資料.cmd` 都要改，多一個會忘記執行的步驟）；寫到 `data/`（擴充功能讀不到資料夾外的檔案）。

## R3 擴充功能的結構

- **Decision**：
  - `extension/`：`manifest.json`（MV3）、`lib.js`（純函式：格式化、資料檢查、是否過舊、頁面價格的對應、選擇名稱連結與 `mid` 區）、
    `sw.js`（讀檔、圖示、alarm、回覆訊息）、`popup.html`／`popup.js`／`popup.css`、`content.js`（遊戲頁面板與願望清單的行）、`icons/`（16／32／48／128 px PNG）。
  - `lib.js` 以一般 script 載入（內容腳本的 `js` 陣列、彈出視窗的 `<script>`、Service Worker 的 `importScripts`），同時支援 `module.exports`，給 `node --test` 用。
  - 不用任何框架與建置步驟，不裝 npm 套件（spec 範圍：只給使用者本人用）。
  - 所有面板與行都放在 shadow root 中，`:host { all: initial }`，Steam 的 CSS 不影響它們，它們也不影響 Steam。
  - 外部字串（遊戲名稱、原因）一律用 `textContent`，或先跳脫再組 HTML（憲章 IX）。
- **圖示**：數字 = `now` 的款數，0 款不顯示；資料過舊時底色改為橘色；讀不到時顯示紅底「!」（FR-011）。
- **Rationale**：最少的東西；Steam 改版時只有 `content.js` 的兩個定位函式要改。

## R4 彈出視窗與面板的內容

- **彈出視窗**（寬 400 px，Chrome 限制最大 800 × 600）：
  頂端為資料時間（台北）與報告產生時間、過舊提示、更新失敗的說明、「買完遊戲後可執行 `更新資料.cmd` 立即更新」。
  接著是五個分組（`<details>`，「現在買」與「即將到價」預設展開），每款一列：名稱（連到 Steam）、現價、甜蜜價與折扣、甜蜜時點、機率；
  「無法預測」顯示原因。最後是組合包一節（名稱連到 Steam 組合包頁、分級、建議句或多付金額）。組內排序與報告相同（`_sorted` 的規則由匯出時決定，JS 不排序）。
- **遊戲頁面板**：分組標籤、資料時間；頁面現價｜甜蜜價｜甜蜜時點與機率｜12 個月內最低；版本說明；其他版本數量；組合包指引；
  非季節預測的一句話；可展開的全部原因。無法預測只顯示原因。已擁有時縮成一行（FR-013a），可展開。
- **願望清單的行**：分組標籤（顏色）＋「甜蜜價 NT$X -Y% · 時點 · 機率」＋「組合包」標記；`title` 為前三個原因。無法預測為分組＋第一個原因（FR-014）。
- 分組顏色沿用 HTML 報告的意義（綠：現在買；藍：即將到價；灰：繼續等；橘：低信心；紅：無法預測），配合 Steam 的深色背景調整。

## R5 測試

- **Python（pytest，測試先行）**：
  - `tests/unit/report/test_extension_data.py`：欄位、句子與 HTML 報告相同、資料時間（中位數、全部未知時為 null）、無法預測、組合包、低信心、使用者指定版本、不含金鑰。
  - `tests/contract/test_extension_contract.py`：格式名稱與版本、必要欄位、大小上限、組內排序與報告相同。
  - `tests/contract/test_cli_report.py`（延伸）：正式執行寫檔、`--as-of` 與 `--rule` 預覽不寫、沒有 `extension/manifest.json` 時不寫、寫檔失敗時報告仍完成且結束代碼 2、先寫暫存檔再改名。
  - HTML 不變：`report/html.py` 拆函式前後，同一份紀錄 render 的結果逐位元組相同（單元測試用建構器的資料；validation 用真實紀錄）。
- **JS（`node --test "tests/extension/*.test.js"`，不裝套件）**：格式化、過舊判斷（26 小時邊界）、資料檔檢查（格式不認得、欄位缺少）、頁面價格對應（用 HTML 字串建出的簡易 DOM 替身）、
  名稱連結與 `mid` 區的選擇、靜態的「沒有網路 API」檢查、manifest 權限與 CSP 檢查。
- **端對端（`uv run --with playwright python tests/extension/e2e.py`）**：不進 pytest（需要瀏覽器，而且 `--live` 要連 Steam）。
  預設只用測試頁（改寫資料檔不重新載入、面板與行、改版頁 0 行、已擁有、擴充功能發出的請求 = 0）；`--live` 另跑原型 P3、P4 的真實頁面檢查並截圖。
- 功能測試通過不代表預測準確（憲章），本 feature 不改任何預測。

## R6 排程改到 02:30（FR-017）

- **Decision**：10/1 以 PowerShell `Set-ScheduledTask` 只改觸發時間（`New-ScheduledTaskTrigger -Daily -At 02:30`），先讀出原設定、改完再讀一次比對
  （動作、`conhost.exe --headless`、錯過時補跑、使用者帳戶都不變）。README 的排程說明同步改。
- **Rationale**：使用者要求 10/1 改（離秋特最近，前幾天的 00:00 更新照常）。這是使用者電腦上的設定，改之前會再跟使用者確認一次。

## R7 時程與風險

| 日期 | 工作 |
|---|---|
| 9/28 | tasks → analyze；Python 匯出（測試先行）＋ HTML 拆函式（逐位元組相同） |
| 9/29 | 擴充功能（lib／sw／popup／content）＋ JS 單元測試＋端對端 |
| 9/30 | 真實資料驗證、截圖、README／HANDOFF；`SendUserFile` 給使用者試用說明與截圖 |
| 10/1 | 依試用結果修正；排程改 02:30；合併到 master（排程在工作目錄執行，目前的分支要有匯出程式） |
| 10/2 01:00 前 | 使用者確認可用（SC-008） |

| 風險 | 處理 |
|---|---|
| Steam 在秋特改版願望清單頁 | 找不到就不顯示（FR-016）；彈出視窗與遊戲頁不受影響。改版後只要改 `lib.js` 的兩個定位函式 |
| 排程執行時工作目錄在別的分支 | 10/1 合併到 master，並在 HANDOFF 註明 |
| Chrome 提醒「停用開發人員模式擴充功能」 | 預期中；選擇保留即可（README 說明） |
| 登入後看到的清單比未登入多 9 款 | 使用者試用時確認這 9 款也有那一行 |
