# Research: 價格資料基礎

**Feature**: 001-price-data-foundation | **Date**: 2026-09-24

所有結論都有出處：官方文件、2026-09-24 的實際 API 測試，或舊專案 SteamSage 的程式碼與快取。
沒有驗證過的項目會標示「未驗證」，實作時要處理。

---

## R1. 歷史價格來源：ITAD API

**Decision**：用 ITAD API 取得台灣區 (TW) 與美國區 (US) 的 Steam（shop 61）歷史價格。

- 對應：`POST /lookup/id/shop/61/v1`，body 為 `["app/620", ...]`，一次查多款，回傳 ITAD UUID 或 null。
  批次上限文件沒寫，實作時每批最多 200 款。
- 反向對應（核對用）：`POST /lookup/shop/61/id/v1`，body 為 `[itadId]`，回傳 `app/N`、`sub/M` 清單。
- 歷史：`GET /games/history/v2?id=&country=&shops=61&since=`，一次只能查一款。
  - 不帶 `since` 只回傳最近 3 個月，所以一律帶上。
  - `since` 只能精確到秒，格式為 UTC `YYYY-MM-DDTHH:MM:SSZ`，帶小數秒會回 400。
  - 回傳的是「價格變動事件」，不是每日取樣。每筆的意思是「從這個時間開始，價格變成這樣」。
- 現價：`POST /games/prices/v3?country=TW&shops=61`，一次最多 200 款，只用來和 Steam 官方現價交叉核對。
- 遊戲資訊：`GET /games/info/v2?id=`，一次一款。可取得標籤、發行商、評論數，作為 Steam 資料的補充。
- 驗證：使用 `ITAD-API-Key` header，金鑰從環境變數 `ITAD_API_KEY` 讀取。
- **一定要帶自訂 User-Agent**。預設的 urllib UA 會被 Cloudflare 以 403（error 1010）擋下（實測）。
- 速率限制：5 分鐘 1000 次。成功的回應裡沒有剩餘額度的 header（實測），只能靠 429 + Retry-After 處理。
  - 實作採保守節流：每次請求之間至少間隔 0.4 秒，並維持 5 分鐘滾動視窗上限 750 次。這沿用舊專案的做法。
- 條款：個人私用允許；不得修改提供的資料（價格、連結）；應標示資料來源為 ITAD。
  本機保存沒有被禁止，文件也鼓勵快取。

**實測（2026-09-24，Portal 2 / Stardew Valley / Hades）**：

| App | TW 最早 | TW 筆數 | US 最早 | US 筆數 |
|---|---|---|---|---|
| 620 | 2024-12-11 | 19 | 2012-11-22 | 148 |
| 413150 | 2024-12-11 | 19 | 2016-02-27 | 119 |
| 1145360 | 2024-12-11 | 29 | 2019-12-10 | 110 |

- 台灣區的第一筆紀錄一律是 cut=0 的原價，而且三款都在 2024-12-11。這是 ITAD **開始追蹤台灣區的時間點**，
  不是真的價格變動，必須標記為「追蹤起點」，不能當作一次漲價或恢復原價。
- 重疊期間，兩區每一天的折扣百分比都相同（19/19、19/19、29/29）。唯一的差異是有一次特賣開始日相差約一天，
  屬於時區或爬取時間的差異。這是 FR-007b 一致性驗證的初步證據，正式數字以實作後的全量計算為準。

**Alternatives considered**：
- SteamDB：禁止爬取，也沒有 API（憲章 VIII）。
- 用第三方服務包裝 SteamDB 資料：等於間接違反條款，排除。

**風險**：歷史查詢沒有文件記載的上限或分頁。很長的美國區歷史若被截斷，可能不會有任何錯誤訊息。
對策：每次記錄筆數與最早時間，覆蓋摘要中發現異常就能察覺。

---

## R2. Steam 官方資料

**Decision**：

| 需求 | 端點 | 驗證狀態 |
|---|---|---|
| 願望清單 | `GET api.steampowered.com/IWishlistService/GetWishlist/v1/?steamid=` 不需金鑰，回傳 `items[{appid, priority, date_added}]`，沒有名稱 | 實測 |
| 現價（台灣區） | `GET store.steampowered.com/api/appdetails?appids=a,b,c&cc=tw&filters=price_overview`，可以一次查多款；價格單位為「分」 | 實測 |
| 名稱、發行商、發售日、評論數、DLC 所屬本體 | `GET api.steampowered.com/IStoreBrowseService/GetItems/v1/?input_json=...`，可批次查詢、不需金鑰 | 實測（未公開文件） |
| 類型（genre，含 Indie）、本體或 DLC | `GET store.steampowered.com/api/appdetails?appids=N&cc=tw&l=tchinese`，一次一款 | 實測 |
| 套件內容（核對用） | `GET store.steampowered.com/api/packagedetails?packageids=N&cc=tw` | 舊專案使用 |
| 評論總數 | `GET store.steampowered.com/appreviews/N?json=1&num_per_page=0&language=all&purchase_type=all` | 實測 |

- appdetails 的回傳結果要以 `data.steam_appid` 判斷是哪一款遊戲，不能用外層的 key。實測時查 620，外層 key 卻是 323180。
- appdetails 的速率限制約為 5 分鐘 200 次，這是社群觀察值，Valve 沒有公開。
  實作採每次請求至少間隔 1.5 秒，遇到 429 或 403 就退避。
- Indie 在 genre 裡的 id 為 `"23"`，這是次要來源的資料（未驗證）。實作時以 genre 的**描述文字**比對
  「Indie／獨立」，並用實測資料確認 id。
- GetItems 只有在打折時才會給原價和折扣欄位（未驗證），所以現價一律改用 `appdetails filters=price_overview`，
  這個端點已實測確認。GetItems 只用來取中繼資料。
- 評論數：GetItems 的 `review_count` 是篩選過的數字，appreviews 的 `total_reviews` 才是全部。
  「排除評論數過少」用 `total_reviews`；兩個值都當作**變動屬性**保存。

**商品核對**（沿用舊專案驗證過的規則）：
1. 取得 ITAD 反向對應清單。如果只有 `["app/N"]`，就直接通過。
2. 每個 `app/X` 的 appdetails `steam_appid` 都必須等於 N，也就是 N 的別名。例如 Portal 2 的 659 對應到 620。
3. 每個 `sub/X` 的 packagedetails 都必須只包含 N 這一款，而且台幣原價和售價要與 N 的 `price_overview` 一致。
4. 某個 sub 查不到，而且它不在 N 目前的販售套件中時，只記警告，不擋下這款遊戲。Half-Life 2 就是這種情況。
5. ITAD 現價 ×100 必須等於 Steam 現價（分）。不一致時依 FR-009 處理：兩邊都保留，並標示不一致。

**請求效率（2026-09-25 實作後調整，核對規則不變）**：
- 套件的內容和價格改用 Web API 的 `IStoreBrowseService/GetItems` 查詢，以 `packageid` 批次查，一次最多 50 個。
  - 它回傳的 `included_appids` 和價格，與 store `packagedetails` 相同（Portal 2 的 sub 7877 實測一致）。
  - 無法公開查詢的套件回傳 `success: 15`，視同原本的 `success:false`。
  - store `packagedetails` 不支援一次查多個（實測回傳 `null`），而且 store 端點是整個流程的瓶頸，約每 5 分鐘 200 次。
- ITAD 的 AppID 對應與反向對應改成批次查詢；參考資料集會一次查接下來約 100 款候選。
- 官方類型（genre，用來判斷是否為獨立遊戲）與別名 App 的核對仍使用 store `appdetails`：
  - GetItems 沒有官方類型欄位。
  - GetItems 會把別名 App 當成獨立項目，無法和 DLC 區分。
- 實測效果（廣泛樣本，同樣 2 分鐘）：新增樣本從 38 款增加到 69 款，store 套件請求從 39 次降為 0 次，ITAD 對應請求從 72 次降為 8 次。

---

## R3. 廣泛樣本的候選清單來源

**Decision**：用 `IStoreService/GetAppList/v1`（需要 Steam Web API 金鑰）取得完整的遊戲清單，只保留遊戲本體
（`include_games=true`），存在本機。接著用固定種子隨機洗牌，逐款取得中繼資料與現價，依分層配額決定收或不收
（先抽樣再分類）。

- 原本不需金鑰的 `ISteamApps/GetAppList/v2` 已下架，實測回傳 404。
- `IStoreService/GetAppList` 參數：`max_results` 最多 50,000，用 `last_appid` 分頁。沒帶金鑰實測回傳 403。
- Steam Web API 條款：每天 100,000 次；金鑰不得公開。
- 金鑰從環境變數 `STEAM_WEB_API_KEY` 讀取。
- **沒有金鑰時的降級做法**：廣泛樣本停用，參考資料集只建立相關樣本，摘要會清楚標示「廣泛樣本停用：缺少 Steam Web API
  金鑰」。系統不會改用來源條款不明的替代來源。

**Alternatives considered**：
- SteamSpy `request=all`：沒有明確的授權條款，資料是估計值，服務也可能停止。不採用。
- Steam 商店搜尋翻頁：robots.txt 允許，但要解析 HTML，很脆弱，而且無法隨機抽樣。只用在找同發行商作品（R4）。

---

## R4. 相關樣本：同發行商與同開發商作品

**Decision**：用 Steam 商店搜尋 `store.steampowered.com/search/results/?publisher=<name>&category1=998&count=50&start=&infinite=1&cc=tw`
翻頁取得候選 AppID。開發商用 `developer=` 參數以同樣方式處理。候選再用 appdetails 確認發行商或開發商相符、
是遊戲本體、已發行。

- robots.txt 沒有禁止 `/search/`（2026-09-24 實際抓取 robots.txt 確認）。
- 翻頁檢查沿用舊專案：頁面重複或沒有前進都視為錯誤。進度會保存，中斷後可以續接。
- 為了不讓大發行商主導資料集，每家發行商或開發商最多取 30 款，用固定種子隨機挑選。所有候選 AppID 仍然保留。
- 可以從舊專案的 `publisher-catalog-v3` 快取匯入 58 家發行商的完整作品清單作為候選。
- 實作時發現的搜尋特性（2026-09-25 實測）：
  - `total_count` 也包含套裝或 package 列，這些列的 `data-ds-appid` 是逗號串接的多個 ID，不算單一遊戲。
    所以翻頁要依「結果列數」前進，不能依 AppID 數。
  - 查無結果時回傳 `total_count: 0`、`start: -1`，視為空目錄。
  - `start` 不是 50 的倍數時，Steam 會自動改回某個對齊的位置。發現回傳位置不一致時，從頭重翻一次；
    重翻後仍不一致，才判定為異常。
- 廣泛樣本先用 GetItems 批次預篩（一次 50 款）。GetItems 的篩選後評論數不會大於總評論數，
  所以低於門檻 80%（即 40 則）時直接排除；介於 40 到 50 則之間時，再查 `total_reviews` 確認。

---

## R5. 分層抽樣參數（FR-016）

**Decision**：
- 發售年份分 6 層：≤2015、2016–2018、2019–2020、2021–2022、2023–2024、2025 以後。
- 台灣區原價分 4 層：< NT$300、300–599、600–999、≥ NT$1,000。
- 是否為獨立遊戲分 2 層。
- 共 48 層，每層目標 25 款，廣泛樣本約 1,200 款。加上相關樣本和舊資料，合計可達 SC-006 的 2,000 款以上。
- 排除條件：免費、未發行、`total_reviews` < 50、台灣區無價格。
- 隨機種子固定寫在設定檔。改變種子或分層定義會產生新的「抽樣版本」，舊樣本保留。
- 這些切點屬於工程判斷，不是模型事實。feature 002 可以依回測需求調整，屬於憲章 VI 所說的可調參數。
- **實測調整（2026-09-25）**：
  - 高價獨立遊戲在 Steam 上很稀少，例如「2015 以前 / 1,000 元以上 / 獨立」一款也沒有，有 13 層無法填滿 25 款。
    - 原本的設計沒有停止條件，會掃完 18.8 萬款母體，而且每款都要查詳細資料才知道它屬於哪一層。
    - 第一次完整執行因此跑了 7.6 小時，仍停在 1,002 款。
  - 修正一：GetItems 預篩時就能知道年份和價位。如果該「年份 × 價位」的獨立和非獨立兩層都已滿，就直接拒絕，
    不再查詳細資料。這裡用的價格是「最佳購買選項」的價格，只用來決定是否跳過，不用來決定已接受樣本的分層。
  - 修正二：掃完整個母體仍未填滿的分層，就接受現有數量，並在摘要列出 `unfilled_strata`，
    如實反映 Steam 的分布（使用者 2026-09-25 選擇此做法）。
  - 效果：2 分鐘掃描的候選數從約 400 款增加到 4,001 款。

---

## R6. 本機儲存

**Decision**：單一 SQLite 檔（Python 標準庫 `sqlite3`），使用 WAL 模式，每款遊戲的寫入各自在一個 transaction 內完成。

- 理由：不需要安裝額外套件，單一檔案，支援 transaction 與索引。預估資料量（約 2,500 款 × 兩區 × 約 150 筆）
  為數十萬筆，對 SQLite 來說很輕鬆。強制中斷後也能保持一致（FR-015、SC-007）。
- 觀測只新增、不修改或刪除。以唯一鍵（商品、來源、區域、觀測時間、售價、原價、折扣）去重，重複匯入不會產生重複資料（FR-020）。
- 金額以「分」為單位的整數保存，未知值存 NULL，所以已知零元（0）和未知（NULL）可以區分（憲章 I）。
- 所有時間都轉成 UTC ISO-8601 保存，同時保留來源提供的原始時間字串。

**時點查詢（FR-012、使用情境 3）**：
- 價格觀測：`observed_at <= t`。ITAD 歷史描述的是當時已公開的價格，所以用觀測時間判斷；
  自行保存的現價，觀測時間就等於取得時間。
- 固定屬性（發行商、開發商、發售日、類型、genre、indie、DLC 所屬本體）不會因事後的市場表現而改變，
  時點查詢回傳最新的值。但發售日晚於 t 的商品，在 t 時點視為尚未發行。
- 變動屬性（評論數、標籤數）以「一次觀測」保存；時點查詢只回傳 `retrieved_at <= t` 的值，所以回測時通常是未知。
  這可以防止用「現在的熱門程度」去預測過去。

**Alternatives considered**：
- 每款遊戲一個 JSON 檔（舊專案的做法）：不能跨商品查詢、去重困難、檔案數量爆炸（舊專案有 5,632 個檔）。
- DuckDB 或 Parquet：分析方便，但多一個相依套件，而且寫入與 transaction 語意不如 SQLite 單純。
  feature 002 需要時可以從 SQLite 匯出。

---

## R7. HTTP 與可靠性

**Decision**：使用 `httpx`（同步）。每個來源一個 client，各自有：

- 節流：ITAD 間隔 0.4 秒並有 750 次 / 5 分鐘上限；Steam Store 間隔 1.5 秒；Steam Web API 間隔 1 秒。
- 重試最多 3 次，429 與 5xx 取 `Retry-After` 和 `2^n` 秒中較大的值。
  （2026-10-22 稽核補記，`sources/http.py`）`Retry-After` 超過該來源的 `max_retry_wait`（預設 120 秒；ITAD 330 秒；官方特賣頁 0 秒、不重試）時不等待，
  直接丟出 `RateLimited`，並記下解除時間：在那之前，對這個來源的請求只要剩下的時間還超過 `max_retry_wait` 就直接丟 `RateLimited`、不送出，剩下的時間不超過時先等完再送。
  014 T076 起，用完重試仍是 429 時也是 `RateLimited`（不論有沒有 `Retry-After`）；5xx 用完重試是一般的 `SourceError`。
- 401 或 403 時停用該來源，本次執行不再對它發出請求（FR-023）。
- 逾時：連線 10 秒、讀取 30 秒。回應大小上限 8 MB。
- 自訂 User-Agent：`SteamSage2/<version> (personal, non-commercial)`。
- 日誌與錯誤訊息中，所有 URL 和 header 的金鑰都會遮蔽（FR-028、SC-008）。
- 測試使用 `httpx.MockTransport` 搭配錄製的 fixture，不需要額外的 mock 套件。

---

## R8. 舊專案快取匯入

**Decision**：只匯入原始資料，不匯入舊模型推導出的資料。

| 舊快取類型 | 匯入內容 | 對應 |
|---|---|---|
| `itad-steam-verified-v1` / `identity` | AppID ↔ ITAD UUID（已核對） | 來源對應，核對狀態標為「舊專案核對」 |
| `itad-steam-verified-v1` / `history` | 台灣區原始歷史紀錄 | 價格觀測，來源標為 `legacy-itad` |
| `publisher-metadata-v1` | 發行商、開發商、genre、發售日 | 固定屬性 |
| `steam-release-v1` | 完整 appdetails | 固定屬性 |
| `publisher-catalog-v3` | 發行商的完整作品清單 | 相關樣本候選 |
| `itad-steam-verified-v1` / `current` | 不匯入：過時的現價快照 | — |
| `publisher-catalog-v1/v2` | 不匯入：清單被截斷 | — |
| `publisher-library-v1` | 不匯入：屬於舊模型的推導資料 | — |

- 舊快取的 `retrieved_at` 是整批執行的時間，不是每次請求的時間。匯入時照原樣保存，並在來源說明中註明。
- 每個檔案都驗證 wrapper 結構和 identity。格式錯誤就跳過並記錄原因（FR-020）。
- 舊專案目錄只讀取、不修改。

---

## R9. Steam 特賣行事曆

完整的日期表與每一筆的來源見 [research-sales-calendar.md](research-sales-calendar.md)，涵蓋 2019–2027 年。
主要來源是 Valve 官方的 Steam News、Steamworks 公告與 Upcoming Events 文件，沒有使用 SteamDB；
只有 4 筆使用次要來源（新聞媒體）。

**重要發現**：
- 開始與結束時間一律是**太平洋時間上午 10:00**（Valve 多篇公告明寫），也就是台灣時間隔天凌晨 1:00 或 2:00。
  `end` 是恢復原價的時間，所以最後一天有折扣的日子是 end − 1 天。
- **秋季特賣在 2025 年改期**：原本在感恩節那一週（11 月下旬），2025 年起改到 9 月底或 10 月初。
  11 月只剩「黑色星期五優惠」專區，那不是全站特賣。
- **2023 年起，春季特賣取代了農曆新年特賣**。2019–2022 年的農曆新年特賣記為主題節慶，不當作春季特賣。
- 冬季特賣長度從 14 天（到 2024 年）變成 18 天（2025、2026 年）。
- 已公告的日期：2026 秋特 10/01–10/08、2026 冬特 12/17–2027/01/04、2027 春特 03/18–03/25、2027 夏特 06/24–07/08。
  Valve 通常提前 6–11 個月公布半年的排程。

**Decision**：
- 正本是 `data/steam_sales.toml`，隨專案維護。每場特賣記錄 `name`、`kind`（seasonal／themed）、`season`
  （spring、summer、autumn、winter，主題節慶則為空）、`year`、`start`、`end`（帶時區，預設為太平洋時間 10:00）、
  `status`（ended／announced）、`source`。
  第一版收錄研究表中 2019 年起的全部季節特賣、萬聖節特賣，以及 Valve 主辦的主題節慶。
- **預估規則**：取「最近一年」同一季特賣的開始日，移到今年同一個星期幾（前後各 3 天內最接近的那天），
  持續天數沿用最近一年。
  - 不用多年中位數，因為秋季特賣在 2025 年改期。中位數會被舊制拉回 11 月，只看最近一年則能立刻反映新排程。
    這也符合「簡單優先」。
  - 推估依據（參考了哪一年、哪一場）一起記錄。
  - 預估結果存在資料庫。官方公告後保留原本的預估，供日後比對準確度（FR-032）。
- 觀測與特賣的對應在查詢時才計算，不寫死在觀測紀錄中。這樣行事曆修正後，對應結果會自動更新。
- 漏收特賣的偵測（FR-033b）：計算每一天（太平洋時間）有多少**不同發行商**的遊戲「開始打折」，
  超過門檻、卻不在任何已知特賣前後 1 天內，就提醒可能漏收。門檻為「資料期間內已知季節特賣開始日的發行商數中位數 × 30%」，
  且至少 20 家。
  - 實作時修正（2026-09-25）：原本計算「遊戲數」，實際資料標出 53 天誤報，因為參考資料集集中在少數發行商，
    單一發行商自辦特賣就有上百款遊戲同時打折。
  - 實測數字：真正的季節特賣開始日有 80–104 家發行商；行事曆以外的日子最多只有 16 家。
  - 改成計算發行商後，誤報降到 0。刻意拿掉 2025 夏特與秋特時，兩場都能被偵測到。
- 預估提醒（FR-033a）：未來 12 個月內，春、夏、秋、冬任一季既沒有公告也沒有預估時提醒。

---

## R10. 其他技術選擇

| 項目 | 決定 | 理由 |
|---|---|---|
| Python | ≥3.12（本機為 3.14.6） | 憲章規定 |
| 套件管理 | uv，`pyproject.toml` 加 `uv.lock` | 憲章規定 |
| 設定 | `steamsage.toml`，使用標準庫 `tomllib` | 不需額外套件；TOML 可以寫註解 |
| 資料模型 | 標準庫 `dataclasses` | 簡單優先 |
| 測試 | pytest | — |
| CLI | 標準庫 `argparse` | 指令少，不需要額外框架 |
| 單一寫入者 | `data/.lock` 鎖檔，內容記錄 PID；PID 已不存在的舊鎖可以接管 | FR-027 |
| 一鍵入口 | `更新資料.cmd` 呼叫 `uv run steamsage update` | 符合憲章「一鍵執行」；feature 003 會延伸成產生報告 |
