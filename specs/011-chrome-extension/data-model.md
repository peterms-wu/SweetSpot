# Data Model: Chrome 擴充功能（feature 011）

資料庫、正式紀錄、決策契約（`steamsage.decision/2`）都**不變**。本 feature 只新增一個呈現層的檔案與擴充功能的執行期狀態。

## 1. 擴充功能資料檔（新）

- 路徑：`<設定檔所在資料夾>/extension/data/steamsage-extension.json`（`.gitignore` 排除 `extension/data/`）。
- 產生：每次正式 `report`，從同一個決策字典產生（[contracts/extension-data.md](contracts/extension-data.md)）；先寫 `.tmp` 再改名。
- 格式：`steamsage.extension/1`，UTF-8 JSON、不縮排。實測 134 KB（68 款、6 個組合包）。

| 實體 | 主要欄位 | 來源 |
|---|---|---|
| 檔頭 | `format`、`generated_at`、`as_of`（報告產生／分析時間）、`data_time`（現價最後確認時間的中位數）、`stale_hours`（26）、`lowest_label`、`refresh_note`、`record`（正式紀錄檔名）、`versions`（模型、規則）、`summary`（各組款數） | 決策字典的 `generated_at`、`as_of`、`data_refresh.note`、`forecast.model`、`rule`、`summary`；`data_time` 由 `decisions[].current.confirmed_at` 計算 |
| 遊戲（`games[]`） | `app_id`、`name`、`group`、`status_reason`、`price_twd`、`cut_pct`、`stale`、`sweet_twd`、`sweet_pct`、`point`、`probability`、`p_min_twd`、`p_min_pct`、`tags`、`option`、`version_text`、`editions`、`bundle_hints`、`ns_reasons`、`reasons` | 決策（`decisions[]`）；句子用報告的同一段函式產生 |
| （2026-10-22 稽核補記；2026-10-14，015）遊戲多一欄 | `versions`（每款的版本陣列，欄位見 015 data-model §1） | 決策的 `version.option`、`editions[]`、`current` |
| 組合包（`bundles[]`） | `id`、`name`、`grade_text`、`discount_text`、`price_twd`、`lines`、`advice_text`、`advice_low`、`check_text`、`contents`、`owned_note` | 批次的 `bundles[]`；各行用報告卡片的同一段函式產生 |

### 規則

- `games` 依分組（now → soon → wait → low → na）排序，組內依報告的排序（`report/html.py` 的 `_sorted`）。擴充功能不重新排序。
- 未知一律是 `null`，不填 0（憲章 I）：例如現價未知時 `price_twd` 為 `null`，顯示「未知」。
- `data_time`：所有非 `null` 的 `current.confirmed_at` 取中位數（偶數個取較早的那個，和 `statistics.median_low` 相同）；全部未知時為 `null`，擴充功能視為過舊。
- `option`：追蹤的購買選項 `{kind: "sub"|"bundle", id, name, user}`；決策的 `version.option` 為 `null` 時為 `null`（頁面現價不並列）。
- 不含：金鑰、Cookie、曲線與每場機率、ITAD 識別碼、比較基準、其他版本的明細（只有數量）。
  （2026-10-22 稽核補記：「其他版本的明細」這點已被 015 data-model §1 取代）2026-10-14 起每款遊戲多一個 `versions` 陣列：追蹤中的版本與其他版本各一項（名稱、價格、折扣、是否預設、按鈕動作、不可指定的原因、手動做法）；`editions` 仍是數量。缺 `versions` 的舊資料檔，遊戲頁面板會顯示「資料檔是舊版…」提示（[contracts/extension-data.md](contracts/extension-data.md) 的規則末尾）。

## 2. 擴充功能的執行期狀態（瀏覽器內，不寫檔）

| 狀態 | 在哪裡 | 內容 |
|---|---|---|
| 讀檔結果 | Service Worker 記憶體（每次請求都重讀，不快取） | `{ok: true, data}` 或 `{ok: false, why: "missing"|"broken"|"format"}` |
| 圖示 | `chrome.action` | 文字：`now` 的款數（0 為空白）或「!」；底色：綠（正常）、橘（過舊）、紅（讀不到） |
| alarm | `chrome.alarms` | `refresh`，每 30 分鐘；安裝與 Chrome 啟動時建立或保留 |
| 頁面上的節點 | Steam 頁面 | `.steamsage-panel`（遊戲頁，一個）、`.steamsage-line[data-app]`（願望清單每列最多一個）；都用 shadow root |

擴充功能不使用 `chrome.storage`、IndexedDB 或 `localStorage`。

### 狀態轉換：資料檔

```text
不存在 ──報告寫檔──▶ 正常 ──超過 26 小時沒有新的確認時間──▶ 過舊 ──下一次報告──▶ 正常
   ▲                   │
   └──刪除─────────────┘      讀到一半／JSON 錯誤 → 損壞（下次讀取再試）；format 不是 steamsage.extension/1 → 格式不認得
```

## 3. 頁面的對應關係

| 頁面 | 對應方式 | 找不到時 |
|---|---|---|
| 遊戲頁 `/app/<id>/…` | 網址的 App 編號 → `games[].app_id` | 不在資料中：頁面不變 |
| 頁面現價 | `option.kind`、`option.id` → `#game_area_purchase form input[name="subid"|"bundleid"][value=id]` 所在的 `.game_area_purchase_game` → 其中的 `[data-price-final]`（分）與價格文字 | 不並列並說明：找不到選項／沒有價格／不是新台幣 |
| 已擁有 | `.game_area_already_owned` 存在 | 照常顯示完整面板 |
| 願望清單列 | `[data-index]` 中第一個 `a[href*="/app/<id>"]` 的 App 編號；名稱 = 沒有子元素且有文字的 App 連結；插入點 = 同一個 grid 中 `grid-row-start` 為 `mid` 的子元素 | 跳過那一列 |
