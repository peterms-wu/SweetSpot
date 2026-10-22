# Contract: 設定檔 `steamsage.toml`

設定檔不含任何金鑰。金鑰只從環境變數讀取（憲章 IX）：

| 環境變數 | 用途 | 沒有設定時 |
|---|---|---|
| `ITAD_API_KEY` | ITAD 的歷史、對應與現價 | 歷史相關功能停用；清單與 Steam 現價照常執行 |
| `STEAM_WEB_API_KEY` | 取得完整遊戲清單，作為廣泛樣本的母體 | 廣泛樣本停用；相關樣本照常執行 |

Windows 上若環境變數是透過 `setx` 設定、目前的程序還讀不到，會再從使用者層級的環境變數（登錄機碼 `HKCU\Environment`）讀取。

```toml
schema_version = 1

[wishlist]
url = "https://store.steampowered.com/wishlist/profiles/〈SteamID〉/"
max_items = 500
removed_tracking_months = 24

[market]
region = "TW"          # 固定值，不可更改（憲章 IX）
aux_region = "US"      # 輔助區域：只保存折扣百分比與時間

[storage]
data_dir = "data"      # 資料庫、鎖檔、日誌都放在這裡

[cache]
history_hours = 24
static_metadata_days = 30
volatile_metadata_days = 7
mapping_days = 7

[reference]
daily_budget_seconds = 120     # 0 表示停用日常小批次
seed = 20260924
per_publisher_cap = 30
broad_per_stratum = 25
min_total_reviews = 50
year_bins = [2015, 2018, 2020, 2022, 2024]    # 分出 ≤2015、2016–18、2019–20、2021–22、2023–24、2025+
price_bins_twd = [300, 600, 1000]

[legacy]
cache_path = '〈前身專案資料夾〉\state\cache'
```

驗證規則：
- 不認得的欄位：警告但繼續執行。
- 型別錯誤、`market.region` 不是 `TW`、願望清單網址格式不符：exit 1，並指出是哪個欄位。
- 設定檔不存在時，用上面的預設值建立一份，然後繼續執行。

> 2026-10-22 稽核補記（已被 014 T010、T013 取代；見 [014 data-model](../../014-publish-github/data-model.md)「設定檔」與 [014 contracts/cli.md](../../014-publish-github/contracts/cli.md) §1–§2）：
> - 設定檔不存在時**不再建立**：只有 `sweetspot setup` 會建立它；其他指令可以互動時先進入設定，不能互動時以 5 結束。
> - 程式內建的範本（`DEFAULT_TOML`）裡 `[wishlist] url` 與 `[legacy] cache_path` 都是空字串，不再是上面的個人值；`setup` 寫入網址。
> - 驗證多一條：`wishlist.url` 是空的 → 「還沒設定願望清單」，exit 1。`cache_path` 是空的 → 只有 `import-legacy` 受影響（說明用途並以 1 結束）。

> 2026-10-22 稽核補記：程式從 001 起還有三條驗證，違反時都是「設定錯誤：…」、exit 1（`config.py` 的 `load_config`、`_int_list`）：
> - `market.aux_region` 必須是兩碼大寫英文字母，而且不是 `TW`。
> - `wishlist.max_items` 必須介於 1 到 500。
> - `reference.year_bins`、`reference.price_bins_twd` 必須是由小到大排列的整數清單（程式只擋變小的值，相鄰兩個相等不擋；布林不算整數）。

> 2026-10-22 稽核補記：沒有給 `--config` 時讀的是**目前資料夾**的 `sweetspot.toml`；`[storage] data_dir` 是相對路徑時，以設定檔所在的資料夾為準（`config.py` 的 `data_dir_of`），
> 見 [cli.md](cli.md)「共用規則」。
