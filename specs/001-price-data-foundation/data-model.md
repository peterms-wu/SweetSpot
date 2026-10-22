# Data Model: 價格資料基礎

**Feature**: 001-price-data-foundation | **Date**: 2026-09-24

儲存方式見 [research.md R6](research.md)：單一 SQLite 檔 `data/steamsage.db`。

通用規則：
- 金額以「分」為單位的整數保存。**NULL 表示未知，0 表示已知零元**（憲章 I）。
- 時間一律以 UTC ISO-8601 字串保存（`...Z`）。來源提供的原始時間字串另外保存在 `raw_*` 欄位。
- 所有事實資料都**只新增、不修改或刪除**。「最新值」由查詢時取得。
- 每筆事實都有 `source` 與 `retrieved_at`（憲章 II）。

---

## 1. runs：執行紀錄

| 欄位 | 型別 | 說明 |
|---|---|---|
| run_id | TEXT PK | UUID |
| kind | TEXT | `daily`、`reference`、`legacy-import`、`calendar-check` |
| started_at / finished_at | TEXT | finished_at 在執行中為 NULL |
| status | TEXT | `running` → `completed`、`partial`、`failed` 或 `interrupted` |
| summary_json | TEXT | 執行摘要（FR-026），格式見 [contracts/cli.md](contracts/cli.md) |

**run_item_results**（逐商品結果，FR-024）：`run_id`、`app_id`、`stage`（`wishlist`、`current-price`、`metadata`、
`mapping`、`history-tw`、`history-aux`、`reference`、`import`）、`status`（`ok`、`reused`、`skipped`、`failed`、
`unsupported`、`delisted`、`not-found`）、`reason_code`、`message`。

`delisted`：商店查詢失敗（appdetails `success:false`），但資料庫已有該遊戲的資料。
`not-found`：商店查詢失敗，資料庫也沒有這款遊戲（FR-006）。

啟動時若發現 `status=running` 的舊紀錄，而且鎖檔的 PID 已經不存在，就把該紀錄改標為 `interrupted`。

> 2026-10-22 稽核補記（`store/schema.py`、`store/writer.py`、`pipeline/*.py`）：
> - 實際寫入的 kind 是 `daily`、`reference`、`legacy-import`；`calendar-check` 在允許清單裡，但沒有程式寫入（`calendar --check` 不建立 run）。
> - `failed` 只有兩處會寫：`update` 的「所有來源都不可用」（014 T072），以及 `import-legacy` 途中出例外。`update`、`reference` 途中出例外時，那一列留在 `running`，
>   要等下一個取得寫入鎖的指令（`update`、`reference`、`import-legacy`、`calendar`）啟動時才改成 `interrupted`；判斷方式是「`running` 而且 PID 不是自己」（持有鎖時不會有別的寫入者）。
> - stage 的 `reference`、`import` 在允許清單裡，但沒有程式寫入；參考資料集的逐款狀態在 `reference_candidates`，匯入的結果只在摘要。

---

## 2. 願望清單

**wishlist_syncs**：`sync_id` PK、`source_url`、`attempted_at`、`status`（`ok`、`empty`、`rejected`）、
`reject_reason`（`private`、`rate-limited`、`malformed`、`incomplete`、`duplicate-appid`、`invalid-appid`、
`over-limit`、`network`）、`item_count`、`run_id`。

**wishlist_items**：`sync_id`、`app_id`、`priority`、`date_added`。只有 `status=ok` 或 `empty` 的同步才會寫入。

**wishlist_membership**：每款遊戲一列，是目前清單狀態的來源。

| 欄位 | 說明 |
|---|---|
| app_id PK | |
| state | `in_wishlist`、`removed_tracking`、`reference_only` |
| first_added_at | 第一次在清單中出現的時間 |
| removed_at | 最近一次被移除的時間 |
| track_until | removed_at + 24 個月（可設定）；在這之前日常更新會繼續追蹤 |

狀態轉換（FR-003a）：

```text
(new) ──sync 出現──> in_wishlist ──sync 消失──> removed_tracking ──超過 track_until──> reference_only
                          ^                            |                                      |
                          └──────── sync 再次出現 ─────┴──────────────────────────────────────┘
```

只有成功的同步（`ok` 或 `empty`）才會觸發狀態轉換。`rejected` 的同步不影響任何狀態（FR-002）。

> 2026-10-22 稽核補記（`pipeline/wishlist.py` 的 `sync_wishlist`、`expire_tracking`）：被拒絕的同步仍然執行 `expire_tracking`：`track_until` 已過的 `removed_tracking` 轉成 `reference_only`。
> 這是依時間到期，不是由同步內容觸發；清單的加入、移除仍然不動。
> 拒絕原因 `incomplete` 目前沒有程式會產生，只有測試用的假來源用到。

---

## 3. products 與 product_facts：商品與中繼資料

**products**：每個 AppID 一列，只放識別資訊。

| 欄位 | 說明 |
|---|---|
| app_id PK | Steam AppID |
| first_seen_at | 第一次出現在系統中的時間 |
| first_seen_via | `wishlist`、`reference-related`、`reference-broad`、`legacy-import` |

**product_facts**：所有中繼資料，只新增。

| 欄位 | 說明 |
|---|---|
| app_id | |
| field | 見下表 |
| value_json | JSON 值。未知時為 `null` |
| volatility | `static` 或 `volatile` |
| source | `steam-appdetails`、`steam-getitems`、`steam-appreviews`、`itad-info`、`legacy-import`、`steam-applist` |
| retrieved_at | |
| run_id | |

| field | volatility | 內容 |
|---|---|---|
| name | static | 名稱（繁中優先，否則英文）。遊戲更名時會出現新值，屬於一般的最新值更新 |
| product_type | static | `game`、`dlc`、`package`、`bundle`、`other` |
| parent_app_id | static | DLC 所屬本體 |
| publishers / developers | static | 名稱清單 |
| release_date | static | 日期。未發行或未知時為 null |
| release_state | static | `released`、`coming_soon`、`unknown` |
| genres | static | `[{id, description}]` |
| is_indie | static | 由 genres 推導，未知時為 null |
| is_free | static | |
| publisher_catalog_size | volatile | 發行商在 Steam 上的作品數（FR-005） |
| review_count_total | volatile | appreviews 的 `total_reviews` |
| review_count_filtered / review_percent_positive | volatile | GetItems 的評論數值 |
| tags | volatile | 標籤 |

> 2026-10-22 稽核補記：`source` 實際會寫的是 `steam-appdetails`、`steam-getitems`、`steam-appreviews`、`legacy-import`，以及上表沒有的 `steam-search`
> （參考資料集的 `publisher_catalog_size`，`pipeline/reference.py`）；`itad-info`、`steam-applist` 沒有程式寫入（Steam 遊戲清單存在 `steam_app_list`，不是 facts）。

**時點查詢**（使用情境 3 AS2）：
- static：回傳該欄位最新的一筆，並附 `retrieved_at`。
- volatile：回傳 `retrieved_at <= t` 的最新一筆，沒有就回傳未知。

---

## 4. source_mappings：來源對應與核對

| 欄位 | 說明 |
|---|---|
| app_id | |
| source | `itad` |
| external_id | ITAD UUID |
| verification | `verified`、`verified-legacy`、`rejected`、`pending` |
| reason_code | 被拒絕的原因：`different-product`、`bundle`、`multiple-candidates`、`package-mismatch`、`price-mismatch`、`not-found` |
| warnings_json | 例如「無法公開查詢的舊 sub」 |
| aliases_json | ITAD 反向對應的 `app/N`、`sub/M` 清單 |
| checked_at | |

只有 `verified` 或 `verified-legacy` 的對應，才能寫入 ITAD 歷史觀測（FR-008）。每次核對都新增一列，最新的一列有效。

---

## 5. price_observations：價格觀測

| 欄位 | 型別 | 說明 |
|---|---|---|
| obs_id | INTEGER PK | |
| app_id | INTEGER | |
| source | TEXT | `itad-history`、`legacy-itad`、`steam-current`、`itad-current` |
| region | TEXT | `TW`，或輔助區域（預設 `US`） |
| currency | TEXT | 台灣區為 `TWD`；**輔助區域為 NULL**（不保存金額，憲章 IX） |
| regular_cents | INTEGER NULL | 當時原價；輔助區域為 NULL |
| price_cents | INTEGER NULL | 當時售價；輔助區域為 NULL |
| cut_pct | INTEGER NULL | 折扣百分比，0–100 |
| observed_at | TEXT | 價格生效的時間 |
| raw_observed_at | TEXT | 來源原始字串（例如 `+02:00`） |
| retrieved_at | TEXT | （2026-10-22 稽核補記）ITAD 歷史列（含輔助區域、版本歷史）是**回應到達的時間**（schema v7 起，見下方「schema v7」）；`steam-current` 是這次執行開始的時間 |
| is_tracking_start | INTEGER | 1 表示這是該來源在該區域序列的第一筆快照（原價或正在打折皆可），代表「當下已是此狀態」，不是價格變動（research R1；schema v2） |
| anomaly | TEXT NULL | `negative-price`、`price-above-regular`、`observed-after-retrieved`、`currency-mismatch` 等；不是 NULL 時，正常查詢會排除 |
| run_id | TEXT | |

- 唯一鍵為 (`app_id`, `source`, `region`, `observed_at`, `price_cents`, `regular_cents`, `cut_pct`)。
  重複寫入時忽略（FR-020）。
  （2026-10-22 稽核補記：已被 006 與 schema v7 取代）現在的唯一索引 `ux_observation` 是
  `(app_id, source, region, IFNULL(external_id, ''), observed_at, IFNULL(price_cents, -1), IFNULL(regular_cents, -1), IFNULL(cut_pct, -1), anomaly IS NULL)`（`store/schema.py` 的 `OBSERVATION_INDEX`）。
  `external_id` 與金額的 `IFNULL` 見 [006 data-model](../006-version-tracking/data-model.md)「`ux_observation`」（schema v3）；最後的 `anomaly IS NULL` 見下方「schema v7」。
- 語意：ITAD 歷史每一筆代表「從 observed_at 開始的價格狀態」。`steam-current` 則是「在 observed_at 這個時間看到的價格」。
- 限免：`price_cents = 0`、`regular_cents > 0`、`cut_pct = 100`。覆蓋摘要會把它和付費促銷分開計算。

**history_fetches**（FR-022）：`app_id`、`source`、`region`、`fetched_at`、`entries`、`run_id`。每次向歷史來源查詢都記一列，用來區分「查過但沒有歷史」和「還沒查過」，也用來判斷 24 小時快取。

### schema v7（2026-10-13）

> 2026-10-22 稽核補記（commit c4b5201「fix: price history events quarantined by the batch start time」；013 plan D3，使用者 2026-10-13 選 A）：
> - 原因一：每日更新把所有歷史列的 `retrieved_at` 都記成**批次開始的時間**。ITAD 在批次開始之後、實際抓取之前記下的事件，`observed_at` 晚於 `retrieved_at`，
>   被隔離成 `observed-after-retrieved`；某款遊戲 2026 秋季特賣開始時的降價就這樣遺失。
> - 原因二：唯一鍵不含 `anomaly`，之後每次抓到同一個事件都被當成重複而忽略，隔離永遠好不了。
> - 改成：ITAD 歷史列的 `retrieved_at` 與 `history_fetches.fetched_at` 記**回應到達的時間**（批次開始時間加上經過的秒數，不早於批次開始；`timeutil.elapsed_clock`）。
>   每日更新在開始時建立一個時鐘，給願望清單與版本的歷史、以及它的參考資料集小批次；`reference` 自己建立一個。
> - 唯一鍵 `ux_observation` 最後加上 `anomaly IS NULL` 這個運算式：同一個價格狀態的正常列和被隔離的列是不同的鍵，之後的抓取可以補上正常列。
>   不是只對正常列唯一的部分索引：兩筆相同的隔離列仍然互相重複。遷移只換索引、不動任何列（備份 `bak-v6`，失敗時整個退回 v6）。
> - 所有不加篩選讀 `price_observations` 的查詢都檢查過：都篩 `anomaly IS NULL`，或用 MAX／EXISTS／COUNT(DISTINCT)，不會重複計算。

**current_price_checks**（FR-009）：`run_id`、`app_id`、`steam_price_cents`、`steam_regular_cents`、
`itad_price_cents`、`itad_regular_cents`、`match`（1 或 0；缺少任一方時為 NULL）。

---

## 6. 參考資料集

**reference_candidates**

| 欄位 | 說明 |
|---|---|
| app_id | |
| pool | `related-publisher`、`related-developer`、`broad` |
| pool_detail | 發行商或開發商名稱；broad 時為分層鍵，例如 `y2019-2020/p300-599/indie` |
| sample_version | 抽樣設定（種子、分層定義）的雜湊 |
| shuffle_rank | 固定種子洗牌後的順序（broad 使用） |
| status | `pending` → `accepted` 或 `rejected` → `fetched` 或 `failed` |
| reject_reason | `free`、`unreleased`、`few-reviews`、`no-tw-price`、`not-game`、`stratum-full`、`publisher-cap` |
| updated_at | |

主鍵為 (`app_id`, `pool`, `pool_detail`, `sample_version`)。一款遊戲可以同時屬於多個候選來源，全部保留（FR-018）。

**catalog_progress**（相關樣本的翻頁進度，FR-017）：`kind`（`publisher` 或 `developer`）、`name`、`next_start`、
`total_count`、`complete`、`updated_at`。

**steam_app_list**（廣泛樣本的母體）：`app_id`、`name`、`last_modified`、`fetched_at`。

---

## 7. 特賣活動

**正本**是 `data/steam_sales.toml`，格式見 [contracts/sales-calendar.md](contracts/sales-calendar.md)，執行時載入。

**sale_estimates**（FR-032）：

| 欄位 | 說明 |
|---|---|
| season / year | 例如 `spring` / 2027 |
| est_start / est_end | |
| basis_json | 使用的歷年特賣與計算方式 |
| created_at | |
| superseded_at | 官方公告寫入行事曆後標記；該列保留不刪 |

**觀測與特賣的對應**：在查詢時計算。若 `observed_at`（或價格狀態持續的區間）與特賣的 [start, end) 重疊，就屬於該特賣；
一筆觀測可以對應多場特賣；都不重疊時為「非活動期間」（FR-031）。

---

## 8. region_consistency：區域折扣一致性

| 欄位 | 說明 |
|---|---|
| scope | AppID，或 `ALL` 表示整體 |
| aux_region | `US` |
| overlap_start / overlap_end | 兩區都有資料的期間。台灣區從第一筆**非追蹤起點**的狀態開始算 |
| days_compared / days_same_cut | 逐日比較兩區當天的折扣 |
| sales_tw / sales_matched | 台灣區的促銷次數，以及其中在美國區 ±1 天內有相同折扣的次數 |
| computed_at | |

---

## 9. 覆蓋摘要（查詢時計算，不另外保存）

每款遊戲輸出以下欄位（FR-021、FR-022）：
- `history_state`：`none`（已查詢但沒有歷史）、`not-fetched`（尚未查詢）或 `available`
- `earliest_observed` / `latest_observed`：台灣區與輔助區域分開列
- `data_gaps`：自行保存的 `steam-current` 紀錄中斷超過 90 天的區段，屬於真正的資料缺口
- `long_unchanged`：外部歷史（ITAD）超過 90 天沒有任何價格變動的區段。ITAD 只在價格變動時記錄，
  所以這一項只是提示，不代表缺資料（FR-021）
- `paid_sale_count`：`cut_pct > 0` 而且 `price_cents > 0` 的促銷次數
- `free_promo_count`：限免次數
- `mapping_state`：核對狀態與原因
- `aux_available`：是否有輔助區域的資料
