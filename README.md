# SweetSpot（甜蜜點）

*A local tool for Steam players in Taiwan: it syncs your public Steam wishlist, forecasts each game's discounts in the
coming Steam seasonal sales, and tells you the price worth buying at and when (TWD only, Windows only). The interface
and the documents are in Traditional Chinese.*

舊名 SteamSage2（2026-09-28 改名）。程式指令、設定檔與資料檔原本沿用的舊名 `steamsage`，feature 016 起也都改成 `sweetspot`，見「舊名稱」一節。

本機工具：同步你的公開 Steam 願望清單，蒐集**台灣區 Steam（新台幣）**的價格資料，預測每款遊戲在未來各場 Steam 季節特賣
出現各種折扣的機率，找出「甜蜜價：值得買的價格與時間」，並用回測驗證預測和建議準不準。

- **只支援台灣區 Steam 商店與新台幣**（[憲章](.specify/memory/constitution.md) IX）：不換匯，也不能改成其他區域。
- **只支援 Windows 10／11**：背景更新用工作排程器，本機程式用目前使用者的登錄。
- 所有資料都在你自己的電腦上；不需要、也不會要求 Steam 密碼。

| Feature | 內容 | 狀態 |
|---|---|---|
| [001 價格資料基礎](specs/001-price-data-foundation/) | 取得、核對並保存價格資料 | ✅ |
| [002 回測框架與基準模型](specs/002-backtest-baseline/) | 折扣機率曲線、回測、模型比較、基準模型 | ✅ |
| [003 甜蜜價決策與 HTML 報告](specs/003-sweet-price-report/) | 甜蜜價、分組報告、變動標示、預測紀錄、規則回測 | ✅ |
| [004 能預測更深折扣的模型](specs/004-deeper-discount-model/) | 新模型 `seasonal-record`、調參組與驗證組、規則 2.0.0（只看 12 個月）、照建議買的回測 | ✅ |
| [005 等待成本](specs/005-waiting-cost/) | 規則 3.0.0（每多等一個月要多省 NT$c）、每月重新評估的回測、淨效益並列；驗證組未通過，**未換版**，可預覽 | ✅ |
| [006 版本追蹤](specs/006-version-tracking/) | 價格歷史跟著 Steam 預設購買選項；偵測版本更換與 ITAD 停止追蹤；資料庫 v3；規則 2.1.0 | ✅ |
| [007 季節特賣以外的折扣](specs/007-non-seasonal-discounts/) | 非季節預測 `non-seasonal` 1.0.0：30／60／90 天內季節特賣以外到價的機率與「可能提早」，只在報告顯示 | ✅ |
| [008 新遊戲與低信心的預測](specs/008-new-game-forecast/) | `seasonal-record` 1.1.0：低信心改用新遊戲前幾場的實際比例、紀錄少時見過的折扣向整體比例靠攏；只計已結束的校準指標；更正 005 的計分錯誤；已換版 | ✅ |
| [009 使用者指定版本](specs/009-purchase-options/) | 記錄所有購買選項、列出其他版本與設定行；`[purchase_options]` 指定版本後改用它自己的價格歷史；資料庫 v4 | ✅ |
| [010 同時含多款願望清單遊戲的組合包](specs/010-wishlist-bundles/) | `bundle-advice` 1.0.0：組合包價由 Steam 組合包折扣推算，純粹組合包給「現在／下一場／分開買」的建議，混合組合包列出多付多少；只在報告顯示；資料庫 v5 | ✅ |
| [011 Chrome 擴充功能](specs/011-chrome-extension/) | 在 Steam 遊戲頁、願望清單頁與工具列直接看甜蜜價 | ✅ |
| [012 特賣日期自動更新](specs/012-sale-calendar-sync/) | 讀 Valve 官方季節特賣頁面，新場次立即用在預測 | ✅ |
| [013 特賣後的事後對照](specs/013-post-sale-comparison/) | 特賣結束後拿預測和實際比 | ✅ |
| [014 公開到 GitHub](specs/014-publish-github/) | 第一次設定、從零安裝、排程註冊、個人資訊掃描、發佈步驟 | 進行中 |
| [015 在 Steam 頁面指定版本](specs/015-choose-edition-on-steam/) | 本機程式讓擴充功能直接指定追蹤版本 | ✅ |
| [016 內部識別碼改名](specs/016-rename-internal-ids/) | 內部識別碼從舊名 `steamsage` 改為 `sweetspot`，與一次性搬家 | ✅ |

設計原則見 [專案憲章](.specify/memory/constitution.md)。

## 從零安裝

### 1. 前置需求

| 工具 | 版本 | 用途 |
|---|---|---|
| Windows | 10 或 11 | 必要 |
| [uv](https://docs.astral.sh/uv/) | 最新版 | 必要：安裝 Python（3.12 以上，uv 會自己下載）與套件、執行指令 |
| [git](https://git-scm.com/) | 任何版本 | 下載這個 repo；也可以在 GitHub 頁面用「Code → Download ZIP」代替 |
| Google Chrome | 目前版本 | 選用：Chrome 擴充功能 |
| [Node.js](https://nodejs.org/) | 24 | 只有開發（跑擴充功能的 JS 測試）需要 |
| [GitHub CLI](https://cli.github.com/)（`gh`） | 任何版本 | 只有原作者的雲端備份與發佈需要；一般使用不用裝 |

### 2. 下載與安裝套件

```powershell
git clone <這個 repo 的網址>
cd SweetSpot
uv sync
```

### 3. API 金鑰（只從環境變數讀取，不寫入任何檔案）

| 環境變數 | 必要？ | 用途 | 沒有設定時 |
|---|---|---|---|
| `ITAD_API_KEY` | **必要** | [IsThereAnyDeal](https://isthereanydeal.com/) 的歷史價格，預測的主要依據 | 第一次設定會停下來說明；之後每款遊戲都只有現價、沒有預測 |
| `STEAM_WEB_API_KEY` | 選用，建議設定 | Steam 全部遊戲清單，用於參考資料集的廣泛樣本 | 廣泛樣本停用，參考資料集只有你願望清單上各遊戲的發行商與開發商的作品，可能到不了 2,000 款（下面第 5 步） |

- **ITAD**：到 <https://isthereanydeal.com/apps/my/> 登入，建立一個應用程式，複製它的 API key。帳號建議完成 email 驗證，驗證後額度較高，為每 5 分鐘 1000 次。
- **Steam Web API**：在 <https://steamcommunity.com/dev/apikey> 申請；它不能購買遊戲，也不能登入你的帳號。
- 每個使用者用**自己的**金鑰；ITAD 的價格資料另受 ITAD 條款限制（見「資料來源與限制」）。

在 PowerShell 設成使用者層級的環境變數，**設定後把視窗關掉再重開**，新的視窗才讀得到：

```powershell
[Environment]::SetEnvironmentVariable('ITAD_API_KEY', '你的金鑰', 'User')
[Environment]::SetEnvironmentVariable('STEAM_WEB_API_KEY', '你的金鑰', 'User')
```

金鑰不要寫進任何檔案（設定檔、批次檔、筆記）；SweetSpot 的輸出、日誌與報告都不會出現金鑰。

### 4. 第一次設定與第一次更新

雙擊 **`更新資料.cmd`**。還沒有設定檔時，它會先執行 `uv run sweetspot setup`：

1. 確認 `ITAD_API_KEY` 已設定（沒有就說明怎麼申請，然後結束，不建立任何檔案）。
2. 請你貼上自己的 Steam 願望清單網址，或個人檔案網址。接受這四種：
   - `https://store.steampowered.com/wishlist/profiles/<17 位數字>/`
   - `https://store.steampowered.com/wishlist/id/<自訂名稱>/`
   - `https://steamcommunity.com/profiles/<17 位數字>`
   - `https://steamcommunity.com/id/<自訂名稱>`
3. 自訂網址會換算成數字形式再存進設定檔（你之後改了自訂網址也不受影響），並顯示「已記成這個帳號」。
4. 確認讀得到願望清單才建立 `sweetspot.toml`。**願望清單要公開**：Steam「編輯個人檔案 → 隱私設定」，把「遊戲詳細資料」設為「公開」。

設定完成後，`更新資料.cmd` 接著更新資料、產生甜蜜價報告，並用瀏覽器開啟 `data/reports/latest.html`。
第一次設定只要幾秒（不含你貼網址的時間）；第一次更新約 7 分鐘（實測：願望清單 69 款，含每日 2 分鐘的參考資料集小批次），之後每天約 2～4 分鐘。

要換成另一份願望清單：`uv run sweetspot setup --change`（只改設定檔裡網址那一行）。其他設定見 [設定說明](specs/001-price-data-foundation/contracts/config.md)。

### 5. 參考資料集

預測除了你自己願望清單上的遊戲，還參考約 2,000 款以上其他遊戲的特賣紀錄（[001 SC-006](specs/001-price-data-foundation/spec.md)）。
新安裝時這個資料集是空的：每日更新會花 120 秒慢慢累積；想一次補完，執行一次

```powershell
uv run sweetspot reference
```

實測約 2～3 小時（願望清單 69 款、有 `STEAM_WEB_API_KEY`），可以中斷，下次接著做。
執行中如果 Steam 商店暫時故障（例如回應 HTTP 502，可在 <https://steamstat.us/> 查看），它會以代碼 1 結束並說明「已完成的部分都已保存」：等商店恢復後再執行一次，會從中斷的地方接著做。

參考資料集不到 2,000 款時，報告頁首與擴充功能會顯示目前的款數與這個補完方法；預測照常產生，只是依據還不完整。
做完之後通常會停在 2,000 款以下（實測 1,659 款：Steam 上售價 NT$1,000 以上的獨立遊戲不夠多，有幾個分層填不滿），這時提示改說「已補完」，不用再執行。

### 6. 每天自動更新

```powershell
uv run sweetspot schedule install     # 每天 02:30 在背景更新（錯過時在電腦可用時補跑）
uv run sweetspot schedule status      # 上次與下次執行
uv run sweetspot schedule uninstall   # 移除
```

- 不需要系統管理員；需要已登入 Windows。電腦一直開著最好，關機錯過的話會在下次可用時補跑。
- 已經有同名的工作、而且指向別的資料夾時會拒絕；加 `--replace` 取代，或用 `--name` 另取一個名稱。`--dry-run` 只列出會建立的設定。

### 7. Chrome 擴充功能與本機程式（選用）

見下方「Chrome 擴充功能」與「在 Steam 頁面指定追蹤版本」：擴充功能用「載入未封裝項目」安裝；本機程式用 `uv run sweetspot host install`。

## 日常使用

雙擊 **`更新資料.cmd`**：先更新資料，再產生甜蜜價報告，最後用瀏覽器開啟 `data/reports/latest.html`。更新約 1–3 分鐘（實測 20 秒左右），報告約 5 秒。
資料更新失敗或另一個更新正在執行時，仍然會用既有的資料產生報告，並在報告頁首說明。

**背景自動更新**：`背景更新.cmd` 做同樣的更新與報告，但不開啟瀏覽器、不暫停，輸出寫到 `data/logs/background-update.log`（每次覆寫）。
要查前幾晚有沒有跑成功，看當天的日誌 `data/logs/sweetspot-YYYYMMDD.log`（本機日期，不覆寫）：每個指令和雲端備份結束時各寫一行
「`update 結束：代碼 0，…`」，代碼不是 0 時記成 WARNING，並附上失敗與警示的內容。
用 `uv run sweetspot schedule install` 註冊後，工作排程器的「SweetSpot 每日背景更新」每天 02:30 用 `conhost.exe --headless` 在背景執行它（Steam 特賣在台北 01:00 或 02:00 開始或換日，02:30 更新才會抓到開賣後的價格），
不會出現視窗。想看報告時直接開 `data/reports/latest.html`。沒有私人備份 repo 的環境（一般使用者）會略過雲端備份，不算失敗。

### Chrome 擴充功能（在 Steam 網站上直接看甜蜜價）

`extension/` 是一個只給自己用的 Chrome 擴充功能（feature 011）。它顯示報告算好的內容，不自己計算、也不判斷「已到價」。

**安裝（一次）**：Chrome 網址列輸入 `chrome://extensions` → 打開右上角「開發人員模式」→「載入未封裝項目」→ 選 `extension` 資料夾 →
用工具列的拼圖圖示把 SweetSpot 釘選到工具列。Chrome 啟動時如果提醒「停用開發人員模式擴充功能」，選擇保留即可。

| 位置 | 內容 |
|---|---|
| 工具列圖示 | 綠底數字＝「現在買」的款數（0 款不顯示）；資料過舊時變橘底，讀不到資料時是紅底「!」 |
| 點圖示（彈出視窗） | 資料時間、五個分組（和報告相同）、組合包；點名稱開啟 Steam 頁面；追蹤 `[purchase_options]` 指定版本的遊戲有「指定版本」小標 |
| 遊戲頁面 | 購買區正上方的面板：頁面現價（取追蹤的那個購買選項，只在顯示新台幣時並列）、甜蜜價、甜蜜時點與機率、12 個月內最低價、版本、組合包建議、原因。已經擁有的遊戲縮成一行。有兩個以上購買選項的遊戲，面板最下面有收合的「版本（N）」一節（見下方「在 Steam 頁面指定追蹤版本」） |
| 願望清單頁 | 每一列遊戲名稱下方一行：分組、甜蜜價、甜蜜時點、機率，在組合包中的遊戲有「組合包」標記；滑鼠移上顯示前三個原因。追蹤指定版本的遊戲有「指定版本」小標，滑鼠移上第一行是版本名稱：Steam 那一列顯示的是預設版本的價格，這一行的數字是指定版本的 |

- **資料怎麼更新**：每次正式執行 `report`（`更新資料.cmd`、背景更新）都會另外寫 `extension/data/sweetspot-extension.json`，
  下次打開彈出視窗或重新整理頁面就是新資料，**不必重新載入擴充功能**。圖示在 Chrome 啟動、打開彈出視窗、載入 Steam 頁面時與每 30 分鐘更新。
  買完遊戲後可以執行 `更新資料.cmd`，已擁有的遊戲就會離開清單。
- **資料過舊**：價格最後確認時間（中位數）超過 26 小時，三個位置都會顯示「資料超過 26 小時，請先執行更新」；每日更新失敗時也會顯示報告的說明。
- **隱私**：擴充功能只讀自己資料夾中的資料檔，不連任何網站，不讀 Cookie 或 Steam 登入資料；權限只有 `alarms`（每 30 分鐘更新圖示）
  與 `nativeMessaging`（和下面的本機程式說話，沒有安裝本機程式時用不到）。
- **Steam 改版**：願望清單頁由 Steam 的前端程式產生，改版後那一行可能消失（找不到位置時不猜，也不影響頁面）；彈出視窗不受影響。
- `--as-of`、`--rule` 預覽不會改寫擴充功能的資料。

### 在 Steam 頁面指定追蹤版本（feature 015，選用）

裝了**本機程式**之後，可以直接在遊戲頁指定要追蹤哪個版本（例如本體或終極版），不用打開報告複製設定行。按下後本機程式改 `sweetspot.toml`
`[purchase_options]` 中那一款遊戲的那一行，然後重新產生正式報告（和手動執行 `report` 完全相同，約 8 秒），面板直接換成新版本的數字。

```powershell
uv run sweetspot host install     # 安裝：只影響目前的 Windows 使用者，不需要系統管理員
uv run sweetspot host status      # 是否已安裝、允許的擴充功能編號
uv run sweetspot host uninstall   # 移除：清掉登錄與 data\host\ 的啟動檔、登記檔（還原失敗留下的檔案會保留）
```

- **第一次安裝後**：在 `chrome://extensions` 對 SweetSpot 按「重新載入」（擴充功能從這一版起有固定的編號），確認編號和 `host status` 顯示的相同。
- **用法**：遊戲頁面板最下面展開「版本（N）」：每個版本一列（名稱、現價），目前追蹤的標「追蹤中」，其他可指定的版本有「追蹤這個版本」，
  指定過的遊戲另有「改回 Steam 預設」。不能指定的版本（例如 ITAD 核對未通過）寫出原因。Steam 自己的購買框也有小捷徑「SweetSpot：追蹤這個版本」。
  **按兩下才會送出**：第一次按變成「確定…？再按一次」，5 秒內再按一次。進度和結果顯示在「版本」一節；60 秒還沒好時會說報告仍在產生，重新整理頁面即可看到。
- **本機程式能做的事**：只有三種指令——查詢狀態、指定版本、改回 Steam 預設；只接受願望清單中的遊戲和購買選項紀錄中可指定的版本，
  每次都用當下的設定檔和資料庫重新檢查；只改那一行，其他內容（含註解）逐位元組不變。指定時那一行後面會加上「（日期 從 Steam 頁面指定）」的註解。
- **不能做的事**：不接受任意路徑、指令或參數；不連網、不開連接埠；不改其他設定、不讀寫其他檔案；只回應 SweetSpot 這個擴充功能（安裝時登記的編號）；
  背景更新正在執行時直接拒絕（「背景更新進行中，請稍後再試」），不會同時寫資料庫。每個請求都記到 `data/logs/`，金鑰不會出現在回覆或日誌中。
- **失敗時**：設定檔、HTML 報告和擴充功能資料檔都改回原樣（已存的正式紀錄保留，紀錄只新增不修改）。萬一設定檔還原失敗，原本的內容會留在
  `data\host\restore-<時間>.toml`，訊息會告訴你。
- **沒有安裝時**：其他功能完全照常；「版本」一節最上面說明怎麼安裝，每個版本寫出手動的步驟（打開 `sweetspot.toml`、加上可以選取複製的那一行或刪掉那款遊戲的那一行、
  存檔後執行 `更新資料.cmd`），做法和下方「指定要追蹤的版本」相同。
- **專案資料夾搬家後**：本機程式記的是安裝時的路徑，面板會顯示「本機程式無法使用」；在新位置重新執行 `uv run sweetspot host install`。
- 願望清單頁與彈出視窗沒有任何指定按鈕。

### 報告怎麼讀

每款遊戲分到其中一組：

| 分組 | 意思 |
|---|---|
| 現在買 | 現價已經不高於甜蜜價 |
| 即將到價 | 甜蜜時點是下一場季節特賣 |
| 繼續等 | 甜蜜時點在更後面，展開可看「等待對照表」：每多等一場大概能買到多少錢 |
| 低信心 | 資料不足、原價對不上，或價格歷史停止更新，數字僅供參考 |
| 無法預測 | 尚未發行、沒有價格歷史、價格歷史混了其他商品等，附原因 |

- **甜蜜價**：未來 12 個月內預測的最低價，加上容許差距以內的價格。
- **甜蜜時點**：到價機率第一次達到 50% 的季節特賣，最遠看到 12 個月後。規則見[模型定義](docs/model/model-definition.md)的「決策規則」。
- **變動**：和前一天或更早的最後一次報告比較，分組、甜蜜時點或甜蜜價改變的遊戲會標出「上次：…」。
- **準確度**：各組標題的百分比來自規則回測（台灣區、12 個月內）。
  - 例如「即將到價」92% 在甜蜜時點前真的到價，「繼續等」62%。
  - 「繼續等」常落在「再創新低的機率剛過一半」的時點，所以本來就只有大約一半會到價。
  - 照回測，照建議買比立刻買平均多省 NT$210、多等 52 天。
- 報告中的價格與價格歷史預設是 Steam **預設購買選項**（通常是一般版，feature 006）；豪華版等其他版本見下方「其他版本與指定版本」。
  - Steam 換了預設購買選項（例如 Dying Light 改賣 Essentials Edition）時，每日更新會自動改用新版本的價格歷史，
    遊戲名稱下方顯示「追蹤 … · 歷史從 … 起 · … 偵測到版本更換」，第一份報告的變動欄註明「版本更換」。
  - ITAD 已經不追蹤這個商品時，顯示「價格歷史停止更新（最後確認 …）」，之後的特賣視為未知，決策為低信心。
  - ITAD 把購買選項和組合包算成同一個商品時（例如 範例分季作品），價格歷史混了不同商品，改列「無法預測」並說明。
- **其他版本與指定版本**（feature 009）：
  - 有其他版本（本體加上它自己的 DLC 的套件或組合包，例如豪華版、終極版）的遊戲，名稱旁顯示「另有 N 個版本」；
    展開後的「其他版本」表格列出現價、原價、台灣區歷史最低價、歷史起點，以及一行設定（附「複製」按鈕）。
  - 想改追蹤某個版本：把那行設定貼到 `sweetspot.toml` 的 `[purchase_options]`（見下方「指定要追蹤的版本」），下一次產生報告就生效；
    那款遊戲的現價、甜蜜價、甜蜜時點與分組都改用那個版本自己的價格歷史，名稱下方顯示「追蹤 …（使用者指定）」。其他遊戲不受影響。
  - 指定的版本不能用時（下架、不是這款遊戲的版本、ITAD 沒有對應或核對未通過），改用 Steam 預設版本並寫出原因。
  - 指定、取消指定或指定的版本不能用之後的第一份報告，變動欄註明「版本更換（使用者指定／取消指定／指定的版本不能用）」。
  - 含其他遊戲的組合包不列出、不能指定（同時含多款願望清單遊戲的見下一項）。驗證未通過的版本仍列出價格與原因，但沒有設定行。
- **組合包**（feature 010）：報告最上面的「組合包」一節列出同時含 2 款以上願望清單遊戲的 Steam 組合包，每個一張卡片。
  - Steam 組合包的價格 = (1 − 組合包折扣) × 各內容當下的價格，所以同一場特賣兩款都買時，組合包一定便宜組合包折扣的比例。
  - **只含願望清單遊戲**（和它們的 DLC）的組合包：列出現在買組合包、分開買、各自在甜蜜時點買的價格，
    「任何一場季節特賣（最早〈下一場〉）」的組合包推算價與兩款同時到價的機率，以及建議（現在買組合包／下一場買組合包／分開買）。
    建議不會比各款最晚的甜蜜時點更晚；引用的「過去這類說法 N% 成真」來自模型定義的回測（調參組的虛構配對）。
  - **含其他內容**的組合包（預設收合）：只列出比只買願望清單遊戲多付多少、多得哪些遊戲與幾個其他內容，不給建議。
  - 價格以全部內容都未擁有計算；已擁有其中的內容時，Steam 的實際價格會更低。
  - 每款相關遊戲的展開內容有一行「可和 … 一起買：組合包 −N%」，點了跳到那張卡片。
  - 組合包建議不改變任何一款遊戲的分組、甜蜜價與甜蜜時點。
- 12 個月內最低價仍可能更低：回測中判為「現在買」之後，有 43% 在 12 個月內出現更深的折扣。
- **季節特賣以外**（feature 007）：展開遊戲，原因清單下面有一段「季節特賣以外」：
  - 過去一年季節特賣以外有幾次促銷、大約多久一次、常見幾折、上一次是什麼時候。
  - 未來 30／60／90 天內，在季節特賣以外降到甜蜜價以下的機率（模型 `non-seasonal`）。
    正在促銷的遊戲，機率指的是「這次結束之後再次到價」。
  - **可能提早**：「即將到價」、「繼續等」或「低信心」的遊戲，如果在甜蜜時點那場特賣開始以前就結束的最長期間內，
    機率達到 50%，標籤會寫「可能提早」，並附上回測中這類說法的實際到價率（約 75%）。
    特賣在 30 天內就開始時不會出現。
  - 這一段只是資訊：分組、甜蜜價與甜蜜時點仍然只看季節特賣。照建議買的人本來就會在非季節促銷到價時買。

只更新資料、不產生報告時：

```powershell
uv run sweetspot update
```

`update` 一次完成以下 6 件事：

1. 同步願望清單
2. 取得台灣區現價，每次執行都會多存一筆
3. 更新商品資料
4. 核對商品；判定每款遊戲的 Steam 預設購買選項與它在 ITAD 的商品（版本），並抓取該商品的台灣區與美國區歷史；
   記錄每款遊戲的所有購買選項，核對其他版本並抓取它們的台灣區歷史（指定的版本另抓美國區，feature 009）
5. 更新特賣行事曆的預估，並計算兩區折扣一致性
6. 花 2 分鐘擴充參考資料集；資料集已滿時，改為更新過期的參考遊戲價格歷史（從最舊的開始）

摘要的 `versions` 列出本次的版本更換、驗證失敗與停止追蹤（約 5 秒）；`purchase_options` 列出購買選項、其他版本的核對結果、
指定的版本是否生效與版本歷史的抓取（平常多約 18 秒）；其中的 `bundles` 列出同時含多款願望清單遊戲的組合包數量、
內容現價未知的數量與公式檢查不一致的組合包（feature 010，多一次 Steam 請求，約 0.3 秒）。`--no-history` 或沒有 ITAD 金鑰時兩者都略過，沿用上一次的紀錄。

資料庫格式升級（例如 feature 010 的 v5）只會在 `update` 等寫入指令時自動進行，升級前會備份成 `data/sweetspot.db.bak-v<舊版本>`。
`report` 等唯讀指令遇到舊格式時會停下，請先執行一次 `update`。

第一次執行約 5–10 分鐘，之後約 1–3 分鐘。

結束代碼：

| 代碼 | 意義 |
|---|---|
| 0 | 完成 |
| 2 | 完成，但有部分項目需要注意，詳見摘要的 `failures` 與 `alerts` |
| 1 | 失敗 |
| 3 | 已有另一個更新正在執行 |
| 4 | 只有改名前（feature 016 之前）的檔案，請先執行 `uv run sweetspot migrate` |
| 5 | 還沒設定願望清單（沒有設定檔，而且是背景執行），請先在視窗中執行 `uv run sweetspot setup`（feature 014） |

## 其他指令

| 指令 | 用途 |
|---|---|
| `uv run sweetspot setup [--change]` | 第一次設定願望清單；`--change` 換成另一份 |
| `uv run sweetspot schedule install\|uninstall\|status [--name 名稱] [--replace] [--dry-run]` | 每日背景更新的排程 |
| `uv run sweetspot reference [--budget 秒數] [--limit N] [--pool related\|broad\|refresh\|all]` | 建立或擴充參考資料集，再用剩下的額度更新過期的參考遊戲價格歷史（`refresh` 只做更新）；可以中斷後續接 |
| `uv run sweetspot import-legacy [路徑]` | 只給前身專案 SteamSage 的使用者：匯入它的快取，只讀取不修改，可重複執行 |
| `uv run sweetspot coverage [--app APPID] [--scope wishlist\|reference\|all] [--csv 檔案]` | 資料覆蓋摘要，以及兩區折扣一致率 |
| `uv run sweetspot calendar [--check] [--fetch]` | Steam 特賣行事曆、預估日期、漏收特賣檢查，以及和官方季節特賣頁面的比對（`--fetch` 先讀取一次官方頁面） |
| `uv run sweetspot calendar --sync [--write]` | 列出官方季節特賣頁面和 `data/steam_sales.toml` 的差異；加 `--write` 寫入檔案（之後自己 commit） |

每個指令都支援 `--json`，會把摘要以 JSON 輸出。詳細說明見 [CLI 契約](specs/001-price-data-foundation/contracts/cli.md)。

## 預測與回測（feature 002）

這 3 個指令都只讀取資料，可以和 `update` 同時執行。

| 指令 | 用途 |
|---|---|
| `uv run sweetspot forecast [--as-of 日期] [--app APPID]… [--scope wishlist\|all] [--out 檔案]` | 預測願望清單每款遊戲的折扣機率曲線 |
| `uv run sweetspot backtest [--region TW\|US\|all] [--model 名稱[@版本]] [--param k=v]… [--split all\|tuning\|validation] [--cutoff 日期] [--apps-limit N]` | 在過去每個月 1 日重跑預測，和實際結果比較並評分；摘要另列「只計特賣已結束」的 Brier 與高機率段的偏差；結果寫到 `data/backtests/` |
| `uv run sweetspot grid --model 名稱[@版本] --grid k=v1,v2 … [--split tuning] [--record]` | 在調參組上跑參數網格，依固定規則選參數：排除美國區顯著變差、本身 2／3–5／6 場以上任一組顯著變差（feature 008）的設定 |
| `uv run sweetspot compare 現行結果.json 候選結果.json [--record] [--attempt N] [--change 說明] [--target-groups 0,1]` | 比較兩份回測結果，判定候選模型是否「優於」現行模型；`--target-groups` 另外要求指定的本身場數組 Brier 較低；每個模型版本的驗證組最多比 3 次 |

**預測是什麼**：對每個折扣等級（-5% 到 -95%）和未來每一場季節特賣（例如「2027 春特」），給出
「在這場特賣結束以前，至少出現一次這麼深的折扣」的機率。已公告的特賣用官方日期，其餘依去年同一季推估，並標示「預估」。
輸出格式見 [預測 JSON 契約](specs/002-backtest-baseline/contracts/forecast-output.md)。

**現行模型** `seasonal-record` 1.1.0（feature 004，008 改進）：
- 見過的折扣用本身的頻率，近期的特賣權重較高；紀錄很少時向所有遊戲的比例靠攏（只有 1 場時不再是 100%）。
- 比過去更深的折扣，用「創新低機率」逐場推算。這個機率來自參考資料集中同類遊戲的紀錄，看的是目前最深折扣是多少、距上次創新低過了幾場。
- 本身沒有任何紀錄的遊戲（多半是新遊戲）用參考資料集中新遊戲前幾場的實際比例。
- 前一版 1.0.0 保留，可以用 `--model seasonal-record@1.0.0` 回測或比較。

**切分**：選參數只在「調參組」上做，換版只看「驗證組」。兩組依 AppID 的固定雜湊各分一半。

**信心等級**：`normal` 表示用這款遊戲本身的季節特賣紀錄，至少 1 場；`low` 表示本身沒有任何紀錄，改用新遊戲前幾場的實際比例。
每個等級在回測中的實際分數，以及模型的規則、參數依據與已知限制，都寫在 [模型定義](docs/model/model-definition.md)。

**準確度**：只以回測分數為準（Brier 分數，越低越好），見模型定義與 [比較紀錄](docs/model/comparisons.md)。
回測以外，本工具不宣稱任何準確率；測試全部通過也只代表功能正確。

**非季節預測**（feature 007）：這 3 個指令只讀資料，結果寫到 `data/backtests/`。

| 指令 | 用途 |
|---|---|
| `uv run sweetspot ns-backtest [--param k=v]… [--split all\|tuning\|validation] [--cutoff 日期] [--no-earlier]` | 回測非季節預測：30／60／90 天內季節特賣以外到價的機率，只計資料涵蓋整個期間的單位；另外統計「可能提早」在各門檻的命中率（`--no-earlier` 略過） |
| `uv run sweetspot ns-grid --grid k=v1,v2 … [--split tuning] [--record]` | 在調參組上跑非季節模型的參數網格 |
| `uv run sweetspot ns-compare 結果.json [--against 另一份.json] [--record] [--attempt N] [--change 說明]` | 和整體比例（或另一份結果）比較；驗證組判定「優於」，最多比 3 次 |

回測別忘了用和比較對象相同的 `--cutoff`：預設是最新資料的日期，隔天更新後就會不同。

## 甜蜜價報告與規則回測（feature 003）

| 指令 | 用途 |
|---|---|
| `uv run sweetspot report [--open] [--as-of 日期] [--out 檔案] [--rule 版本]` | 預測、決策、保存紀錄、產生 HTML 報告。只讀資料庫，可以和 `update` 同時執行。`--rule 3.0.0` 產生**預覽**：不保存紀錄、不和前一天比較，另存成 `data/reports/preview-3.0.0.html` |
| `uv run sweetspot backtest-rule [--model 名稱] [--param k=v]… [--rule 1.0.0\|2.0.0\|2.1.0\|3.0.0\|3.1.0] [--wait-cost 20[,30…]] [--split …] [--cutoff 日期] [--apps-limit N]` | 在過去每個月 1 日做出決策，對照之後的實際價格，評估甜蜜價規則：「照建議買」多省多少、多等多久，以及扣掉等待成本的淨效益（固定決策與每月重新評估兩種）。規則 3.0.0 可一次跑多個 c，預測只做一次；結果寫到 `data/backtests/` |
| `uv run sweetspot compare-rule 基準.json 候選.json [候選2.json …] [--record] [--attempt N] [--change 說明] [--decision 文字]` | 並列一份基準與多份候選：各項指標、淨效益差距與 95% 區間（依遊戲成對重抽樣）、願望清單差異。驗證組的紀錄要加 `--attempt`（最多 3 次）；已記錄的那一次再加 `--decision` 時，只附加使用者的決定 |

- 沒有 `--as-of` 的 `report` 是**正式執行**：每次都把完整的預測與決策保存到 `data/forecasts/`（每份約 33 KB），供日後對照。
  `--as-of` 只供檢查，不保存紀錄，報告另存成 `data/reports/asof-日期.html`。
- 輸出格式見 [決策 JSON 契約](specs/003-sweet-price-report/contracts/decision-output.md)；feature 005 起為 `steamsage.decision/2`
  （[新增欄位](specs/005-waiting-cost/contracts/decision-output-v2.md)），舊的 `/1` 紀錄仍可讀取與比較。

### 甜蜜價的偏好設定

在 `sweetspot.toml` 加上 `[preferences]` 區段可以調整。這些是**使用者偏好**，不是模型事實；沒有寫的項目用預設值：

```toml
[preferences]
wait_cost_twd = 20        # 等待成本：每多等一個月要多省的台幣（規則 3.0.0；目前只用於預覽與回測）
soon_sales = 1            # 甜蜜時點在前幾場季節特賣算「即將到價」
gap_pp_shallow = 10       # 規則 2.x：12 個月內最低價淺於分界時，容許差距是原價的幾個百分點
gap_pp_deep = 5           # 規則 2.x：12 個月內最低價達到分界或更深時
gap_boundary_pct = 75     # 規則 2.x：分界 -75%
tolerance_min_twd = 30    # 規則 2.x：容許差距下限（元）
tolerance_max_twd = 100   # 規則 2.x：容許差距上限（元）
```

現行規則是 `sweet-price` 2.1.0，用容許差距；它和 2.0.0 只差「價格歷史停止更新 → 低信心」，規則回測逐案相同（feature 006）。
規則 3.0.0（feature 005）改用等待成本：比較「現在買」與「以某個目標折扣、最晚等到
12 個月內某一場」的期望多省，扣掉 c × 期望多等的月數，選淨效益最高的。它在驗證組沒有通過換版門檻，所以目前只供
`report --rule 3.0.0` 預覽與回測；決策輸出與報告只記錄、顯示該規則用到的偏好。

預設值的依據見[模型定義](docs/model/model-definition.md)的決策規則。改了偏好之後，報告會註明「偏好改變」，部分變動可能來自這個改變。

### 指定要追蹤的版本

在 `sweetspot.toml` 加上 `[purchase_options]` 區段（feature 009）。這是**使用者偏好**：每一行把一款遊戲改成追蹤指定的購買選項。
裝了本機程式時可以直接在 Steam 遊戲頁指定（見上方「在 Steam 頁面指定追蹤版本」）；手動的做法是從報告「其他版本」表格按「複製」，貼到這裡：

```toml
[purchase_options]
1091500 = "bundle/32470"   # Cyberpunk 2077 → 《電馭叛客 2077：終極版》
```

- 值是 `"sub/<套件編號>"` 或 `"bundle/<組合包編號>"`；格式錯誤、不在願望清單的 App 會被忽略並在摘要中警告。
- 刪掉那一行就回到 Steam 預設版本。指定的剛好是 Steam 預設時，之後 Steam 換預設也不會跟著換。
- 指定版本的美國區歷史在下一次 `update` 才會抓；在那之前的報告只用台灣區的紀錄，原因會寫明。
- 回測與其他遊戲的預測都不受指定影響。

## 事後對照（feature 013）

| 指令 | 用途 |
|---|---|
| `uv run sweetspot review [--sale autumn-2026] [--record 檔名] [--today 日期] [--force] [--no-recompute] [--doc] [--out 檔案]` | 拿季節特賣開賣前最後一份正式紀錄，對照特賣的實際價格：季節機率（特賣最深折扣與回測的定義並列）、各組決策、提早到價有沒有在特賣中改成現在買、組合包建議、已到期的非季節預測，並在同一時點重算現行與基準模型。**唯讀**；特賣結束 3 天後才執行（`--force` 例外）；結果寫到 `data/reviews/`，`--doc` 印出 `docs/model/comparisons.md` 一節的草稿 |

- 這是事後對照，不是新的準確率，不取代回測，也不改模型或規則（憲章 IV）。定義與計分規則見 [contracts/review.md](specs/013-post-sale-comparison/contracts/review.md)。
- 非季節預測的期間（30／60／90 天）還沒結束、或價格歷史還沒涵蓋到期日時列為「尚未到期」，之後重跑同一個指令就會計入。

## 資料放在哪裡

| 位置 | 內容 |
|---|---|
| `data/sweetspot.db` | 價格、商品資料、執行紀錄（SQLite），不進版本控制。schema v6 起另外記錄每次讀取官方季節特賣頁面的結果（`calendar_fetches`）與每次看到的場次（`sale_sightings`），只新增不修改。schema v7 的唯一鍵區分被隔離與有效的列：某個價格事件曾被隔離，之後抓到有效的同一事件時仍會新增 |
| `data/steam_sales.toml` | Steam 特賣行事曆正本，每一場都附官方來源，**要隨專案維護**。季節特賣從 2012 年開始。官方季節特賣頁面公告的新場次會自動用在預測，但只有 `sweetspot calendar --sync --write` 會修改這個檔案 |
| `data/backtests/` | 回測結果 JSON（預測與甜蜜價規則），不進版本控制 |
| `data/forecasts/` | 每次正式執行的預測與決策紀錄（`.json.gz`），只新增不修改，不進版本控制 |
| `data/reports/` | HTML 報告：`latest.html` 每次覆蓋，不進版本控制 |
| `data/reviews/` | 事後對照的結果（`steamsage.review/1`），不進版本控制；摘要寫在 `docs/model/comparisons.md` |
| `docs/model/` | 模型定義與比較紀錄（進版本控制） |
| `data/logs/` | 執行日誌，金鑰已遮蔽：`sweetspot-YYYYMMDD.log` 每個本機日期一個（2026-10-18 之前的檔名是 UTC 日期），每個指令結束時寫一行結束代碼；`background-update.log` 只有最近一次背景更新 |
| `extension/` | Chrome 擴充功能（進版本控制）；`extension/data/` 是報告寫的資料檔，含願望清單，不進版本控制 |
| `data/host/` | `sweetspot host install` 寫的本機程式啟動檔與登記檔（feature 015），不進版本控制；`data/.host.lock` 是指定版本時的處理鎖 |
| `data/pre-016-backup-<時間>/` | `sweetspot migrate` 搬家前的備份與 `migration.json`（feature 016），不進版本控制；確認背景更新正常後可以刪除 |

資料只新增不修改；未知的值存為空值，已知的零元存為 0。分析程式透過唯讀介面 `sweetspot.store.query.PriceStore` 讀取資料，查詢過去任一時間點時，不會拿到該時間點之後才出現的資料，詳見 [store-api](specs/001-price-data-foundation/contracts/store-api.md)。

## 資料來源與限制

- **價格歷史資料來自 [IsThereAnyDeal](https://isthereanydeal.com/)**。依 ITAD 條款，資料只供個人使用，保存的價格不做修改；每個使用者用自己的 ITAD 金鑰，在自己的電腦上建立資料，價格資料不隨這個 repo 散布。程式碼的授權（MIT，見 [LICENSE](LICENSE)）不涵蓋 ITAD 的資料。
- 台灣區歷史從 **2024-12-11** 開始，這是 ITAD 開始追蹤台灣區的時間。美國區的歷史只保存折扣百分比與時間，**不換算成台幣**。美國區資料要經一致性驗證才會被當作輔助證據。
- 不使用 SteamDB（該站禁止爬取）。對 Steam 與 ITAD 的請求都有間隔限制；遇到限流時依對方指示等待，遇到 401/403 時直接停止，不繞過。
- 特賣行事曆只收錄官方公告過的特賣。尚未公告的季節特賣會依去年同一季的日期推估，並標示為「預估」。
- **季節特賣的日期會自動更新**（feature 012）：每次 `update` 讀取一次 Valve 的[官方季節特賣頁面](https://partner.steamgames.com/doc/marketing/discounts/seasonalsales)（1 個請求，不用登入）。檔案沒有的場次立即用在預測（標示為「官方」）；日期和檔案不同時**沿用檔案**，每天提醒，執行 `sweetspot calendar --sync --write` 確認後才改。抓不到或看不懂頁面時沿用既有紀錄並提醒，不會把任何一場當成取消。只有季節特賣：Next Fest 與主題特賣的日期仍要人工維護。回測仍然只看得到已經結束的特賣。

## 舊名稱（feature 016）

專案的舊名是 SteamSage2（2026-09-28 改名為 SweetSpot）；當時程式內部仍用舊名 `steamsage`：指令、套件、設定檔 `steamsage.toml`、資料庫 `data/steamsage.db`、日誌、擴充功能的資料檔與頁面節點，以及工作排程器的「SteamSage2 每日背景更新」（舊名）。
feature 016 把這些舊名全部改成新名稱 `sweetspot`／SweetSpot，不保留舊名當別名；完整的新舊對照見 [contracts/names.md](specs/016-rename-internal-ids/contracts/names.md)，掃描允許留下舊名的地方見 [docs/legacy-names.md](docs/legacy-names.md)。

下列寫在已保存紀錄裡的識別碼**保留舊名不改**：輸出與紀錄的格式名稱（例如 `steamsage.decision/2`、`steamsage.extension/1`）、feature 004 調參組與驗證組的分組依據 `steamsage-004-split`、紀錄欄位 `steamsage_version`。
改了它們，舊紀錄就讀不懂、回測資料集識別碼也會改變（憲章 IV）。

舊的日誌檔（`data/logs/` 中舊名開頭的檔案）與舊的資料庫升級備份保持原名，不搬也不刪。

**搬家（一次）**：合併 016 之後，在專案資料夾執行一次：

```powershell
uv run sweetspot migrate --dry-run   # 先看會做什麼，不改任何檔案
uv run sweetspot migrate
```

它會：
- 先取得和背景更新相同的寫入鎖；
- 把設定檔、資料庫、擴充功能資料檔各複製一份到 `data/pre-016-backup-<時間>/`；
- 改成新名稱，並用 SHA-256 確認內容沒變，任何一步失敗都會全部改回；
- 重寫本機程式的啟動檔、用新名稱重建排程工作（只處理登記到這個資料夾的）；
- 最後列出要你自己做的事，例如在 Chrome 重新載入擴充功能。

細節見 [contracts/migrate.md](specs/016-rename-internal-ids/contracts/migrate.md)。

還沒搬家時，主資料夾只有舊名的設定檔或資料庫，這時 `migrate` 以外的每個指令都會拒絕執行，並提示先搬家。拒絕時：
- 不建立任何檔案；
- 結束代碼是 **4**；
- `更新資料.cmd`、`背景更新.cmd` 的整體結束代碼依嚴重程度取 1 > 5 > 4 > 3 > 2 > 0（5 是還沒設定）；update 的代碼不在 0–5 時（例如被中止）算 1。

### 從改名前的雲端備份還原

`scripts/backup_db.py` 在 016 之前上傳的 zip（`sweetspot-db-YYYY-MM-DD.zip`）裡，是舊名的 `data/steamsage.db` 與 `steamsage.toml`，016 之後的 zip 才是新名稱。還原舊名的備份：

1. 把 zip 解開到專案資料夾。先把現有的 `sweetspot.toml`、`data/sweetspot.db` 移開，否則新舊並存時搬家會拒絕。
2. 執行 `uv run sweetspot migrate`，把解開的舊名檔案搬成新名稱。
3. 執行 `uv run sweetspot report` 確認正常。

## 開發

```powershell
uv run pytest                              # 單元、契約、整合測試（不連網）
node --test "tests/extension/*.test.js"    # 擴充功能的 JS 單元測試（Node 24 內建，不裝套件）
uv run --with playwright python tests/extension/e2e.py [--live]   # 擴充功能端對端；--live 另外檢查真實 Steam 頁面
uv run python scripts/record_fixtures.py steam|itad|reference   # 重新錄製 API 測試資料（會連網）
```

本專案用 [spec-kit](https://github.com/github/spec-kit) 開發：每個 feature 依序經過 specify → clarify → plan → tasks → analyze → implement。

`uv run python scripts/scan_personal.py` 檢查要公開的檔案裡沒有任何人的 SteamID、本機資料夾、信箱等個人資訊（也是自動測試的一部分；允許的例外見 [docs/personal-scan.md](docs/personal-scan.md)）。新寫的文件裡，本機路徑一律寫成〈專案資料夾〉這樣的代稱。

## 這個 repo

- 公開的 repo 是作者本機開發版本的**發佈快照**：每次發佈一個 commit，不在這裡直接開發。
- Issue 與 Pull Request 歡迎，但 PR 不會直接合併：作者會把修改搬回本機的開發版本，隨下一次發佈出現（作者欄會是作者本人）。
- 授權：MIT（[LICENSE](LICENSE)）。ITAD 的價格資料不在授權範圍內，見「資料來源與限制」。

### 維護者：發佈到公開 repo

在作者的開發資料夾（master）執行：

```powershell
uv run python scripts/publish.py --dry-run    # 先看：會公開哪些檔案、訊息草稿；什麼都不改
uv run python scripts/publish.py              # 產生一個發佈 commit（不推送）
```

它會：取 master **已提交**的內容（扣掉 `HANDOFF.md`）整份換掉公開資料夾（預設是旁邊的 `SweetSpot-public`）→
執行發佈時的個人資訊掃描（金鑰、帳號、願望清單的加入日期、Steam 標為成人內容的遊戲；需要網路）→ 在公開資料夾跑 `uv sync`、pytest、node 測試 →
全部通過才 commit（作者是 GitHub 的 noreply 地址），並在 master 打上 `publish/NNN` 記下對應的 master commit。
任何一步沒通過就把公開資料夾恢復原樣，不打 tag。它**不推送**：最後印出 `gh repo create …`（第一次）或 `git push` 的指令，確認後自己執行。
細節見 [contracts/publish.md](specs/014-publish-github/contracts/publish.md)。
