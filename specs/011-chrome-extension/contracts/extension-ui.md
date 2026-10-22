# Contract: 擴充功能的三個呈現位置與 `report` 的變更

## manifest（`extension/manifest.json`）

| 項目 | 值 |
|---|---|
| `manifest_version` | 3 |
| `permissions` | `["alarms"]`（沒有 `host_permissions`、`cookies`、`storage`、`tabs`）。**015 起**是 `["alarms", "nativeMessaging"]`，並加上固定編號的 `key`：見 [015 的契約](../../015-choose-edition-on-steam/contracts/extension-ui.md) |
| `content_scripts` | `https://store.steampowered.com/app/*`、`https://store.steampowered.com/wishlist/*`；`["lib.js", "content.js"]`；`document_idle` |
| `content_security_policy.extension_pages` | `default-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self'; style-src 'self'; object-src 'none'` |
| `web_accessible_resources` | 無（資料檔只給 Service Worker 讀，網頁讀不到） |
| `action.default_popup` | `popup.html`（只在點圖示時打開，FR-009） |

## 訊息

內容腳本與彈出視窗 → Service Worker：`{type: "data"}`；回覆 `{ok: true, data, stale: bool}` 或 `{ok: false, why: "missing"|"broken"|"format"}`。
Service Worker 每次收到訊息都重讀檔案並更新圖示（FR-006、FR-011）。

## 彈出視窗（FR-009–FR-011）

| 區塊 | 內容 |
|---|---|
| 頂端 | 「資料時間 YYYY-MM-DD HH:MM（台北）· 報告 YYYY-MM-DD HH:MM」；過舊時橘色提示「資料超過 26 小時，請先執行更新」；`refresh_note` 時顯示該句；一行「買完遊戲後可執行 更新資料.cmd 立即更新」 |
| 分組 ×5 | 標題「現在買（11）」…；「現在買」「即將到價」預設展開。每列：名稱（連到 `https://store.steampowered.com/app/<id>/`，新分頁）、現價與折扣、甜蜜價與折扣、甜蜜時點、到價機率（2026-10-18 由「機率」改，`title` 見下方「到價機率的說明」）；「無法預測」為名稱＋原因。`option.user` 時名稱後加「指定版本」小標，`title`「追蹤 《版本》（使用者指定）：現價與甜蜜價都是這個版本的價格，不是 Steam 預設版本」（2026-10-14） |
| 組合包 | 名稱（連到 `https://store.steampowered.com/bundle/<id>/`）、分級、`discount_text`、`advice_text`（粗體，低信心加標籤）或 `lines` 的最後一行。（2026-10-22 稽核補記：實際是一般文字，低信心在句尾加「（低信心）」，記在 011 T023；`check_text` 不是 null 時句尾再加「（check_text）」。014 T075 起，原因句已經包含它時 `check_text` 是 null，不再重複） |
| 讀不到 | 「還沒有資料：請先執行 更新資料.cmd」（missing）／「資料檔損壞或正在寫入，請稍後再開」（broken）／「資料格式不認得（需要 steamsage.extension/1），請更新擴充功能或重新產生報告」（format）；不顯示任何遊戲 |

## 圖示（FR-011）

| 狀態 | 文字 | 底色 |
|---|---|---|
| 正常 | `now` 的款數；0 款為空白 | 綠 `#1e7d32` |
| 過舊 | 同上（0 款時顯示「!」） | 橘 `#b06000` |
| 讀不到 | `!` | 紅 `#a1261b` |

更新時機：Chrome 啟動、安裝或重新載入、打開彈出視窗、Steam 遊戲頁或願望清單頁載入、每 30 分鐘。

## 遊戲頁面板（FR-012、FR-013、FR-013a）

- 條件：網址 `/app/<id>/`、`id` 在 `games` 中、頁面有 `#game_area_purchase`。插在它正前方，每頁一個。
- 內容（由上而下）：分組標籤＋「SteamSage2 · 資料時間 …」（過舊時加提示；`refresh_note`）；
  一列五格：頁面現價｜甜蜜價 -Y%｜甜蜜時點（官方／預估）｜到價機率｜12 個月內最低 -Y%；
  頁面現價不並列時的一句說明；`version_text`；「另有 N 個版本」；`bundle_hints`；`ns_reasons`；「原因（N）」可展開。
- 無法預測：分組標籤＋`status_reason`。
- 已擁有：一行「你已擁有這款遊戲；以下是購買前（資料時間 …）的建議」＋展開按鈕；展開後是完整面板。

## 願望清單的行（FR-014–FR-016）

- 位置：該列 grid 的 `mid` 區元素最前面；每列最多一行，`data-app` = 該列的 App 編號。
- 內容：分組標籤（顏色）＋「甜蜜價 NT$X -Y% · 時點 · 到價機率 Z% · 12 個月內最低 NT$X -Y%」（最低價的名稱取 `lowest_label`）＋（在組合包中）「組合包」；`title` = 前三個原因以換行連接
  （2026-10-18 起前面先加一行到價機率的說明）。
- 無法預測：分組標籤＋ `status_reason`。
- 指定版本（2026-10-14）：`option.user`（使用者在 `[purchase_options]` 指定了 Steam 預設以外的版本）時，分組標籤後加「指定版本」小標，
  `title` 第一行「追蹤 《版本》（使用者指定），不是這一列顯示的版本」（`refresh_note` 仍在最前面）。Steam 願望清單那一列的價格是預設版本的，
  我們的數字是指定版本的，不標會誤解（例如 Cyberpunk 2077：本體 -70%、指定的終極版 -60%）。小標固定長度，版本名稱只放在 `title`，不擠掉後面的數字。
- （2026-10-22 稽核補記）資料過舊（現在 − `data_time` > `stale_hours` 小時，或 `data_time` 為 null）時，行的最前面（分組標籤之前）加橘色字「資料過舊 ·」；
  不放 spec FR-007 那句完整的「資料超過 26 小時，請先執行更新」，`title` 裡也沒有那句（行的空間有限；完整提示在彈出視窗與遊戲頁面板）。（`extension/lib.js` 的 `lineModel`、`extension/content.js` 的 `wishLine`；011 T031／T032）

## 到價機率的說明（2026-10-18，擴充功能 1.2.1）

彈出視窗、遊戲頁面板、願望清單的行與 HTML 報告（規則 3.0.0 的版面除外）的到價機率都有同一句 `title`：
「到 《甜蜜時點》為止，季節特賣打到 -Y%（NT$X）以上的機率；跟現價無關」。原因：「現在買」的遊戲現價已低於甜蜜價，
只寫「機率」或「到價機率」容易被讀成「現在買得到的機率」（使用者 2026-10-17 問 OPUS：龍脈常歌的 64%）。字放在 `title`，不加長欄位標籤。
- 處理：載入時一次，之後 `MutationObserver` 在每個畫面更新最多處理一次；列被 Steam 重複使用給另一款遊戲時移除舊的行。

## 錯誤處理（FR-008）

所有頁面處理包在 `try/catch`；錯誤只讓擴充功能自己的節點不出現，不丟到頁面，不改 Steam 元素的樣式或屬性。

## `report` 指令的變更（FR-001、FR-002）

| 項目 | 內容 |
|---|---|
| 何時寫 | `official`（沒有 `--as-of`、不是 `--rule` 預覽），而且 `<設定檔所在資料夾>/extension/manifest.json` 存在 |
| 寫什麼 | `extension/data/steamsage-extension.json`（暫存檔再改名） |
| 摘要（`--json` 輸出） | 新增 `extension`：寫入的路徑；沒寫時 `null`；失敗時 `"未寫入：<錯誤>"` |
| 失敗 | HTML 報告與正式紀錄照常；印出「擴充功能資料未寫入：…」；結束代碼為部分成功 |
| HTML 報告 | 不變（SC-009） |
