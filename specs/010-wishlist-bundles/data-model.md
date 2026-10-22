# Data Model: 同時含多款願望清單遊戲的組合包（feature 010）

## 1. schema v5（research R2）

`purchase_options`（009，只新增）新增兩個可為 null 的欄位：

| 欄位 | 型別 | 說明 |
|---|---|---|
| `bundle_discount_pct` | INTEGER NULL | 組合包列：Steam 的 `bundle_discount_pct`（例如 10）；套件列與 v5 以前的紀錄為 null |
| `before_bundle_cents` | INTEGER NULL | 組合包列：Steam 的 `price_before_bundle_discount`（內容原價的加總）；同上 |

`contents_json` 的每個內容（009：`{app_id, type, parent_app_id}`）在 **FR-001 的組合包**多一個鍵：

| 鍵 | 說明 |
|---|---|
| `final_cents` | 那個 App 在同一次更新時的 Steam 台灣區現價（GetItems 的 `best_purchase_option`）；請求失敗或商店沒有價格時為 null（未知）。其他組合包與 v5 以前的紀錄沒有這個鍵 |
| `name` | 同一次請求帶回的名稱（台灣區商店）；DLC、原聲帶在本機沒有名稱，報告用它顯示（MVP 後使用者同意加入）。沒有時不寫這個鍵 |

- 遷移 v4 → v5：`ALTER TABLE purchase_options ADD COLUMN …` 兩次；只新增觸發器不變。遷移前把資料庫備份為 `steamsage.db.bak-v4`，沿用 `backup_before_migration`。
- 讀取：`OptionRecord` 新增 `bundle_discount_pct`、`before_bundle_cents`；`contents` 保留 `final_cents`。

## 2. 實體（決策時由紀錄計算，不另外儲存）

### WishlistBundle（願望清單組合包）

| 屬性 | 來源 |
|---|---|
| `id`、`name` | 購買選項紀錄（`kind = bundle`） |
| `checked_at` | 那次紀錄的時間 |
| `discount_pct`、`before_cents`、`price_cents` | `bundle_discount_pct`、`before_bundle_cents`、`final_cents` |
| `grade` | `pure`／`mixed`（research R1） |
| `contents` | `BundleContent` 的清單，依 Steam 的順序 |
| `check` | `FormulaCheck` |
| `comparison` | `BundleComparison` |
| `advice` | `BundleAdvice`（只有純粹組合包；混合為 null） |

識別：組合包編號。同一個分析時點、同一個編號只有一筆（取最新一次紀錄中任一列，內容相同）。

### BundleContent

| 屬性 | 說明 |
|---|---|
| `app_id`、`name` | 名稱：願望清單遊戲用決策的名稱，其他用 `steam_app_list`／`product_facts`，沒有時為 null |
| `role` | `wishlist`、`wishlist-dlc`、`other-game`、`other` |
| `price_cents` | 願望清單遊戲：決策的現價；其他：`final_cents`；未知為 null |
| `specified` | 這款遊戲有使用者指定的版本（009 `[purchase_options]` 生效）時為 true |

### FormulaCheck（research R3）

| 屬性 | 說明 |
|---|---|
| `expected_cents` | round((1 − b) × Σ `price_cents`)；有內容未知時為 null。每日更新的摘要用同一個函式，但所有內容的價格都取 `final_cents`（research R3） |
| `status` | `ok`、`mismatch`、`unknown` |
| `tolerance_cents` | max(200, 1% × expected) |

### BundleComparison

| 屬性 | 說明 |
|---|---|
| `separate_cents` | Σ 全部內容的 `price_cents`（未知時為 null） |
| `wishlist_cents` | Σ 願望清單遊戲的 `price_cents` |
| `extra_cents` | 混合：`price_cents − wishlist_cents`；純粹：null |
| `extra_items` | 混合：非願望清單內容的數量與名稱（遊戲、DLC 分開計數） |
| `plan_cents`、`plan_point` | 純粹：分開買的計畫（research R4 第 2 條）與最晚的甜蜜時點（全部「現在買」時為 null＝現在） |

### BundleAdvice（`bundle-advice` 1.0.0，research R4）

| 屬性 | 說明 |
|---|---|
| `status` | `ok`（有建議）或 `none`（不給建議）；`none` 時 `reason_code` 為 `no-forecast`、`specified`、`check-mismatch`、`check-unknown`、`stale-price`、`no-sale`、`error` |
| `kind` | `now`、`next-sale`、`separately` |
| `sale` | 下一場季節特賣（label、start、end、status） |
| `levels` | 每款在下一場的折扣等級 `[{app_id, pct, cents, probability}]` |
| `estimate_cents` | 下一場的組合包推算價 |
| `joint_probability` | 同時到價機率 |
| `saving_cents` | 分開買的計畫 − 建議的價格（現在：組合包現價；下一場：推算價）；分開買時為 null |
| `timing` | `earlier`（下一場早於最晚的甜蜜時點）、`same`、`now`；分開買時為 null |
| `hit_rate` | 同時到價機率所在區間的回測實際比例（模型定義；research R0.2）；`kind = now` 時為 null |
| `confidence` | `normal`／`low` |
| `text` | 核心寫好的建議句（報告只顯示） |

### 狀態

```text
組合包出現在紀錄中 ──► 內容未知 ──► 不列出（摘要計數）
          │
          ├─ 願望清單遊戲 < 2 ──► 不列出
          ├─ 混合 ──► 比較（多付、多得）
          └─ 純粹 ──► 比較 ──► 不給建議的條件？ ──是──► advice.status = none（原因）
                                       └─否──► 現在 / 下一場 / 分開買
```

每一天的判定只看當天（as_of 以前最新）的紀錄；沒有跨天的狀態，也沒有變動標示（spec 不包含）。

## 3. 讀取介面

| 介面 | 說明 |
|---|---|
| `PriceStore.purchase_options(apps, as_of)` | 009；v5 起 `OptionRecord` 多兩個欄位，`contents` 多 `final_cents` |
| `decision.bundles.build_bundles(store, decisions, forecast, as_of, chosen)` | 回傳 `(bundles, per_app_ids)`；任何例外讓 `bundles` 為 null、每款的 `bundles` 為 null，不影響決策（憲章 III） |
| `decision.bundles.advise(...)` | 純函式：R4 的規則，輸入各款的決策、下一場機率、原價、組合包折扣與現價 |
| `BUNDLE_BACKTESTS` | 命中率常數（依機率區間），和模型定義一致，由測試檢查 |
