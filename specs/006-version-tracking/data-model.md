# Data Model: 版本追蹤

資料庫升為 **schema v3**（research R3）。只新增欄位與表；既有資料只在遷移時補 `external_id`，價格、時間與旗標都不變。

## 1 新表 `app_versions`（只新增）

每次每日更新，願望清單（含移除後仍在追蹤期間）的每款遊戲寫一列。本次無法取得預設購買選項（來源錯誤），或版本步驟無法執行
（`update --no-history`、沒有 ITAD 金鑰）時不寫，沿用上一列（FR-011）。

> 2026-10-22 稽核補記：實際只有這次現價結果是 priced、free、not-purchasable、delisted 的遊戲會寫列（`pipeline/daily.py` 的 `HISTORY_OUTCOMES`）；
> 沒有台灣區售價的（免費、不能購買、下架）寫 `no-option`。尚未發售、unsupported、not-found、現價查詢失敗的遊戲不寫列、不計入摘要的 `no_option`；
> 沒有任何版本紀錄時，它們的 `version.basis_reason` 是 `no-record`。ITAD 對應查詢失敗時整個版本步驟不執行，也不寫列。

| 欄位 | 型別 | 說明 |
|---|---|---|
| `version_row_id` | INTEGER PK | 自動遞增 |
| `app_id` | INTEGER | 願望清單的 App |
| `checked_at` | TEXT (UTC) | 這次更新的時間；讀取時只用 `checked_at <= as_of` 的列（無洩漏） |
| `run_id` | TEXT | 每日更新的執行 id |
| `status` | TEXT | `ok`、`no-option`（沒有預設購買選項）、`ambiguous`（無法唯一決定）、`not-in-itad`（ITAD 沒有這個購買選項） |
| `package_id` | INTEGER NULL | 預設購買選項（Steam 套件）；`no-option`、`ambiguous` 為 NULL |
| `package_name` | TEXT NULL | 購買選項的名稱（`purchase_option_name`，只當資料顯示） |
| `regular_cents`、`price_cents` | INTEGER NULL | 決定版本時的台灣區原價與售價（和 `price_overview` 相同） |
| `external_id` | TEXT NULL | 這個套件對應的 ITAD 商品 |
| `itad_title` | TEXT NULL | ITAD 商品名稱（只當資料顯示）。（2026-10-22 稽核補記：已被 006 T039 取代）ITAD 不提供批次的商品名稱，版本步驟不寫這一欄，永遠是 NULL；顯示用的名稱是 `package_name` |
| `verification` | TEXT NULL | `verified`、`rejected`；`status ≠ ok` 為 NULL |
| `verified_by` | TEXT NULL | `own-mapping`（和 001 的對應相同，沿用）、`version-check`（本次驗證）、`cached`（沿用 7 天內同一商品的驗證） |
| `verified_at` | TEXT NULL (UTC) | 驗證實際執行的時間（憲章 II：沿用的資料保留原始取得時間）。`version-check` 等於 `checked_at`；`cached` 是被沿用的那次驗證的時間；`own-mapping` 是 001 對應的 `checked_at`。`verification` 為 NULL 時為 NULL |
| `reason_code` | TEXT NULL | 拒絕原因：`bundle`、`other-games`、`price-mismatch`、`different-product`、`multiple-candidates`。（2026-10-22 稽核補記）另有 001 的 `not-found`（ITAD 查不到這個商品的任何別名）與 `package-mismatch`（仍在販售的套件無法公開查詢）（`pipeline/verify.py` 的 `verify_version`） |
| `reason_detail` | TEXT NULL | 人看得懂的細節，例如 `bundle/99003`、多出來的 App id |
| `warnings_json` | TEXT NULL | 驗證警告（無法公開查詢的套件等） |
| `aliases_json` | TEXT NULL | ITAD 商品的別名清單（`sub/…`、`app/…`、`bundle/…`），取得時間是 `verified_at` |
| `itad_steam_deals` | INTEGER NULL | ITAD 對這個商品在台灣區的 Steam 現價筆數；0 = 停止追蹤；NULL = 本次沒查到 |

索引：`(app_id, checked_at)`。只新增：`app_versions` 加入 `APPEND_ONLY_TABLES`，沿用觸發器。

### 衍生概念（讀取時計算，不另外存）

- **版本** = 一列的 `external_id`（`status = ok` 且 `verification = verified`）。
- **版本更換** = 同一 App 相鄰兩列的 `external_id` 不同（兩列都是 `ok`）。第一列和 App 本身的 001 對應比較（research R7）。
  只換 `package_id`、`external_id` 相同：套件改變，不是版本更換（FR-003）。

  > 2026-10-22 稽核補記：兩處的「上一列」不同。預測的 `change`（`store/query.py` 的 `_latest_switch`）只看 `status = ok` 的列，跳過非 ok 列；
  > 更新摘要的 `changed` 與 alert（`pipeline/versions.py` 的 `_label`）看緊鄰的上一列，上一列不是 ok 時拿 App 本身的 001 商品比。
  > 所以換版到商品 B 之後，某天變成 `ambiguous`／`not-in-itad`、隔天回到同一個 B 時，摘要會再報一次 `changed`（和 alert），預測的 `change` 仍是原本那次更換。
- **偵測時間** = 更換後那一列的 `checked_at`。
- **停止追蹤** = 在分析時點以前最新的一列 `itad_steam_deals = 0`，而且 `price_cents` 不是 NULL（Steam 仍在販售）。
- **最後確認時間** = 同一 `external_id` 的最新觀測，與 `itad_steam_deals ≥ 1` 的最新一列 `checked_at`，取較晚者。

## 2 既有表的新欄位

| 表 | 新欄位 | 說明 |
|---|---|---|
| `price_observations` | `external_id TEXT NULL` | ITAD 商品 id。ITAD 與舊專案匯入的歷史列必填（遷移時補上）；`steam-current` 為 NULL |
| `history_fetches` | `external_id TEXT NULL` | 這次抓的是哪個 ITAD 商品；「已知至」依 `(app_id, region, external_id)` 計算 |
| `current_price_checks` | `external_id TEXT NULL`、`itad_steam_deals INTEGER NULL` | 核對的是哪個 ITAD 商品，以及 ITAD 的 Steam 現價筆數 |

唯一索引 `ux_observation` 重建為
`(app_id, source, region, IFNULL(external_id, ''), observed_at, IFNULL(price_cents, -1), IFNULL(regular_cents, -1), IFNULL(cut_pct, -1))`。
（2026-10-22 稽核補記：schema v7 在最後加上 `anomaly IS NULL`，讓被隔離的列之後還能補上正常的同一筆；見 [001 data-model](../001-price-data-foundation/data-model.md)「schema v7（2026-10-13）」。）

## 3 遷移 v2 → v3

1. 備份 `steamsage.db` 成 `steamsage.db.bak-v2`（不存在時才備份）。
2. 同一個交易中：
   1. 新增欄位與 `app_versions` 表、索引。
   2. 暫時移除 `price_observations` 的 UPDATE 觸發器。
   3. 對每個**恰好有一個**非 NULL `external_id` 的 App（`source_mappings`, source = `itad`），把它的 ITAD 歷史列（`itad-history`、`legacy-itad`）與 `history_fetches` 的 `external_id` 補成那個 id。
   4. 重建唯一索引；恢復觸發器；`schema_version = 3`。
3. 失敗就回滾，資料庫維持 v2。

遷移後的保證（測試）：每一列除了 `external_id` 之外完全相同；`app_versions` 為空；只新增的觸發器全部存在。

## 4 讀取介面（`PriceStore`）

| 方法 | 說明 |
|---|---|
| `versions(app_ids, as_of) -> dict[int, VersionRecord]` | 每款 `checked_at <= as_of` 最新的一列，加上衍生的「版本更換」與「最後確認時間」 |
| `history_keys(app_ids, as_of) -> dict[int, HistoryKey]` | 每款在 as_of 應使用的 ITAD 商品：`(external_id, basis, reason)`；basis = `version`、`own`、`rejected` |
| `series_rows(app_ids, region, as_of, keys=None)` | 新增 `keys`：只回傳 `(app_id, external_id)` 相符的列；`external_id` 為 NULL 的列視為 App 本身的商品 |
| `history_known_until_all(region, keys=None, as_of=None)` | 依商品計算；有停止追蹤的版本紀錄時，截在最後確認時間（research R4） |

`keys` 省略時的行為和 v2 完全相同，但實際上所有呼叫都會傳入 `history_keys` 的結果：沒有版本紀錄的 App 就是 App 本身的商品，所以結果仍然相同。

## 5 預測與決策中的版本物件

`VersionInfo`（預測輸出與決策輸出共用，見 contracts）：

| 欄位 | 說明 |
|---|---|
| `basis` | `version`（依版本紀錄）、`own`（沿用 App 本身的對應） |
| `basis_reason` | `basis = own` 時的原因代碼：`no-record`、`no-option`、`ambiguous`、`not-in-itad` |
| `package_id`、`package_name` | 預設購買選項 |
| `itad_id`、`itad_title` | 使用的 ITAD 商品 |
| `history_start` | 這份台灣區歷史的第一筆時間 |
| `known_until` | 「已知至」 |
| `tracking` | `ok` 或 `stopped` |
| `last_confirmed` | `tracking = stopped` 時的最後確認時間 |
| `change` | 最近一次版本更換：`{from_itad_id, from_title, to_itad_id, to_title, detected_at}`；沒有更換為 NULL |

> 2026-10-22 稽核補記（已被 006 T039 與 009 的 [contracts/outputs-options.md](../009-purchase-options/contracts/outputs-options.md) 取代；實際欄位見 `forecast/contract.py` 的 `VersionInfo`）：
> - 沒有 `itad_title`（006 T039；輸出也沒有這個鍵）。另有 `own_itad_id`（App 本身 001 對應的商品）、`checked_at`（版本紀錄的時間）、`reason_code`、`reason_detail`（只在 `basis = rejected` 時有值）。
> - `basis` 實際是 `version`、`own`、`rejected`，009 另加 `user`（使用者指定的版本）。
> - 009 新增 `source`（`steam-default`／`user`／`user-fallback`）、`option`（`{kind, id, name}`）、`fallback`、`aux_pending`。

驗證失敗（`basis = rejected`）的遊戲沒有預測曲線，預測狀態為 `unverified`，`status_reason` 寫出原因；`version` 仍會輸出，方便報告顯示。

## 6 狀態轉換

```text
（第一次執行）── 和 App 本身相同 ──▶ 版本 A（basis=version）
       │
       └── 和 App 本身不同 ──▶ 版本 B，記錄一次更換（偵測時間 = 這次執行）

版本 A ── 預設套件換了，ITAD 商品相同 ──▶ 版本 A（套件改變，不算更換）
版本 A ── ITAD 商品變成 B，B 通過驗證 ──▶ 版本 B（更換）
版本 A ── ITAD 商品變成 B，B 驗證失敗 ──▶ unverified（更換，原因寫出）
版本 A ── 無法唯一決定／ITAD 沒有這個選項 ──▶ 沿用 App 本身的對應（basis=own）
版本 A ── 本次來源錯誤 ──▶ 不寫新列，仍是版本 A（標示確認時間）
版本 A ── ITAD 的 Steam 現價筆數 = 0 ──▶ 版本 A，tracking=stopped（已知至截短）
```
