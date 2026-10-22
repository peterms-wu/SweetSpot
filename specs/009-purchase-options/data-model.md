# Data Model: 使用者指定版本、列出其他購買選項

資料庫升為 **schema v4**（research R3）：只新增一張表與它的只新增觸發器，既有資料不變。遷移前自動備份成 `steamsage.db.bak-v3`。

## 1 新表 `purchase_options`（只新增）

每次每日更新的購買選項步驟，為願望清單（含移除後仍在追蹤期間）每款有購買選項的遊戲、**每個**購買選項寫一列。
來源錯誤或步驟被略過（`update --no-history`、沒有 ITAD 金鑰）時不寫，讀取時沿用上一次（FR-009）。

| 欄位 | 型別 | 說明 |
|---|---|---|
| `option_row_id` | INTEGER PK | 自動遞增 |
| `app_id` | INTEGER | 願望清單的 App |
| `checked_at` | TEXT (UTC) | 這次更新的時間；讀取時只用 `checked_at <= as_of`（無洩漏） |
| `run_id` | TEXT | 每日更新的執行 id |
| `kind` | TEXT | `sub` 或 `bundle` |
| `option_id` | INTEGER | 套件或組合包編號 |
| `name` | TEXT NULL | 購買選項名稱（`purchase_option_name`，只當資料顯示） |
| `original_cents`、`final_cents` | INTEGER | 台灣區原價與售價（沒有折扣時兩者相同） |
| `position` | INTEGER | 在 Steam 商店上的順序 |
| `is_default` | INTEGER | 是否為同一次更新 006 判定的 Steam 預設購買選項 |
| `role` | TEXT | `default`、`edition`（本體＋自己的 DLC）、`other-games`、`without-app`、`unknown`（內容查不到） |
| `contents_json` | TEXT NULL | 內容：`[{app_id, type, parent_app_id}]`；類型的取得時間見 `contents_checked_at` |
| `contents_checked_at` | TEXT NULL (UTC) | 內容中 App 類型的取得時間（沿用 30 天內的值時保留原始時間，憲章 II） |
| `external_id` | TEXT NULL | ITAD 商品（只有 `role = edition`） |
| `verification` | TEXT NULL | `verified`、`rejected`；沒有 ITAD 商品時為 NULL |
| `verified_by`、`verified_at` | TEXT NULL | 同 006：`version-check`、`cached`；原始驗證時間 |
| `reason_code`、`reason_detail` | TEXT NULL | 拒絕原因（006 的代碼；組合包是另一個組合包時 `bundle` + 別名） |
| `warnings_json`、`aliases_json` | TEXT NULL | 同 006 |
| `itad_steam_deals` | INTEGER NULL | ITAD 對這個商品的台灣區 Steam 現價筆數；0 = 停止追蹤；NULL = 本次沒查到 |

索引：`(app_id, checked_at)`、`(app_id, kind, option_id, checked_at)`。

`role = default` 的列只記錄價格與內容，驗證與歷史仍由 006 的 `app_versions` 負責（不重複）。

## 2 版本的價格歷史（既有表，新的來源值）

| 表 | 做法 |
|---|---|
| `price_observations` | `source = 'itad-option-history'`，`app_id` = 願望清單 App，`external_id` = 版本的 ITAD 商品；台灣區存價格，美國區只存折扣百分比（沿用） |
| `history_fetches` | `source = 'itad-option'`，`external_id` = 版本的 ITAD 商品 |

- 只抓 `role = edition` 且 `verification = verified` 的版本；和目前預設版本同一個 ITAD 商品時不抓（用預設的資料）。
- 台灣區每天抓（`history_hours`）；美國區只抓指定生效的版本（research D2）。
- 既有讀取依來源過濾，版本歷史不進入預設序列、季節特賣偵測、區域一致性與回測資料集（research R3 的讀取修正）。

## 3 設定：指定（`steamsage.toml`）

```toml
# 指定要追蹤的購買選項（使用者偏好；報告的「其他版本」會附上可複製的設定行）
[purchase_options]
# 1091500 = "bundle/32470"   # Cyberpunk 2077 → 《電馭叛客 2077：終極版》
```

- 讀成 `Config.purchase_options: dict[int, OptionRef]`，`OptionRef = (kind, option_id)`。
- 格式錯誤、鍵不是正整數、同一 App 重複 → 忽略該行，`load_config` 的警告中說明（FR-008）。
- 不在追蹤範圍的 App → 產生預測時忽略並警告。（2026-10-22，014 T074：追蹤範圍＝願望清單＋移除後仍在追蹤期間，`report`、`update`、本機程式相同。）

## 4 讀取介面（`PriceStore`）

| 方法 | 說明 |
|---|---|
| `purchase_options(app_ids, as_of) -> dict[int, list[OptionRecord]]` | 每款 `checked_at <= as_of` 最新一次步驟的所有列 |
| `option_keys(choices, as_of, default_keys) -> dict[int, OptionKey]` | 每款有指定的 App：追蹤的 `HistoryKey`（版本的 ITAD 商品，或退回時的預設 key）、`source`、退回原因（research R4 的表格） |
| `series_rows(..., sources=ITAD_SOURCES)` | 新增 `sources`；版本歷史用 `('itad-option-history',)` |
| `latest_observations`、`observations` | 修正：`itad-option-history` 依商品過濾，不當成商店現價 |
| `option_lows(app_ids, as_of)` | 每個版本台灣區歷史的最低價、日期、第一筆時間（報告清單用）。版本讀 `itad-option-history`；已指定時清單中的 Steam 預設版本讀預設版本的歷史（006 的 key 與來源） |

`OptionKey`：

| 欄位 | 說明 |
|---|---|
| `key` | `HistoryKey`；`basis` 新增 `user`（版本的商品）。退回時是 006 的預設 key |
| `source` | `user`、`user-fallback` |
| `requested` | 使用者指定的 `OptionRef` |
| `record` | 指定選項的 `OptionRecord`（找得到時） |
| `fallback_code`、`fallback_detail` | `not-offered`、`not-edition`、`not-in-itad`、`rejected`、`no-record`；拒絕時附 006 的原因 |
| `same_as_default` | 版本的商品等於預設版本的商品（直接用預設資料） |
| `stopped`、`last_confirmed` | 版本最新的購買選項紀錄 `itad_steam_deals = 0` 且 Steam 仍在販售：照 006 FR-009／FR-010 截短「已知至」並判低信心，不退回預設 |

## 5 輸出（contracts/outputs-options.md）

- `version` 新增 `source`、`option`、`fallback`；`editions` 清單新增在決策中。
- 預測紀錄 `data/forecasts/*.json.gz` 隨之新增選用欄位；`steamsage.forecast/1`、`steamsage.decision/2` 不升版。

## 6 狀態轉換（一款遊戲追蹤的購買選項）

```text
（沒有指定）──────────────▶ Steam 預設（006）             source = steam-default
    │ 使用者加了指定設定
    ▼
指定的選項可用 ─────────────▶ 指定的版本                  source = user，第一份報告：版本更換（使用者指定）
    │ 下架／變成含其他遊戲／驗證失敗
    ▼
退回 Steam 預設 ───────────▶ 預設版本＋原因               source = user-fallback，第一份報告：版本更換（指定的版本不能用）
    │ 選項又可用
    ▼
指定的版本（再標示一次版本更換）
任何狀態 ── 使用者刪掉設定 ──▶ Steam 預設                  source = steam-default，第一份報告：版本更換（取消指定）
指定的版本 ── Steam 換了預設 ──▶ 仍是指定的版本（不標示）
指定的版本 ── ITAD 停止追蹤 ──▶ 仍是指定的版本，006 的停止追蹤處理（低信心）
```
