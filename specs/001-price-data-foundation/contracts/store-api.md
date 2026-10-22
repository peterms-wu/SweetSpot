# Contract: 資料查詢介面（提供給 feature 002 與 003）

分析核心透過這組唯讀的 Python 介面取得資料，不直接寫 SQL（憲章 VII）。
所有接受時點參數 `as_of` 的方法，都**保證**不會回傳 `as_of` 之後才發生的觀測（FR-012、SC-003）。

```python
class PriceStore:
    def open(path) -> PriceStore                     # 以唯讀方式開啟

    # 商品集合
    def wishlist_apps(state: set[str] = {"in_wishlist"}) -> list[int]
    def reference_apps(pool: str | None = None) -> list[int]

    # 時點查詢
    def observations(app_id: int, as_of: datetime, region: str = "TW",
                     include_tracking_start: bool = True) -> list[Observation]
    def facts(app_id: int, as_of: datetime) -> ProductFacts
    def sales(as_of: datetime, include_estimates: bool = True) -> list[SaleEvent]
    def sales_for(obs: Observation) -> list[SaleEvent]        # 空清單表示非活動期間
    def region_consistency(scope: int | Literal["ALL"]) -> RegionConsistency | None
    def coverage(app_id: int) -> Coverage
```

## 值物件

```python
@dataclass(frozen=True)
class Observation:
    app_id: int
    region: str                  # "TW" 或輔助區域
    source: str
    observed_at: datetime        # UTC
    retrieved_at: datetime
    regular_cents: int | None    # 輔助區域一定是 None
    price_cents: int | None      # 輔助區域一定是 None
    cut_pct: int | None
    is_tracking_start: bool

@dataclass(frozen=True)
class Fact[T]:
    value: T | None              # None 表示未知
    source: str | None
    retrieved_at: datetime | None

@dataclass(frozen=True)
class ProductFacts:
    app_id: int
    name: Fact[str]
    product_type: Fact[str]
    parent_app_id: Fact[int]
    publishers: Fact[list[str]]
    developers: Fact[list[str]]
    release_date: Fact[date]
    released_as_of: bool | None  # 由 release_date 與 as_of 推得
    genres: Fact[list[dict]]
    is_indie: Fact[bool]
    review_count_total: Fact[int]          # volatile：只取 as_of 以前取得的值
    publisher_catalog_size: Fact[int]      # volatile

@dataclass(frozen=True)
class SaleEvent:
    name: str                    # 例如 "Steam Spring Sale"
    name_zh: str                 # 例如 "春季特賣"
    kind: str                    # "seasonal" 或 "themed"
    season: str | None
    year: int
    start: datetime
    end: datetime
    status: str                  # "ended"、"announced" 或 "estimated"（相對於 as_of）
    source: str                  # 網址，或預估依據的說明
    confidence: str              # "official"、"secondary" 或 "estimated"
    basis: dict | None           # 預估的依據（參考年份、原始起訖）；非預估時為 None
```

## 保證事項（以 contract tests 驗證）

1. 對任何 `as_of`，`observations()` 回傳的每一筆都滿足 `observed_at <= as_of`。
2. 預設不回傳 `anomaly` 不是 NULL 的觀測。
   追蹤起點（每個序列的第一筆）預設**會**回傳並標示 `is_tracking_start`：它代表「在 observed_at 當下價格已經是這個狀態」，不是一次價格變動。
3. 輔助區域的觀測中，金額欄位一定是 None。
4. volatile 的 facts 滿足 `retrieved_at <= as_of`，否則值為 None。
5. 結果依 `observed_at` 升冪排序。同一時點有多個來源時全部回傳，排序依 source 名稱。
6. `sales(as_of)` 永遠回傳 `start <= as_of` 的特賣；**只有 as_of 是現在時**才附上已公告的未來特賣與預估。
   因為沒有記錄每場特賣的公告日期，回測時看到未來特賣等於偷看答案。回測需要未來特賣時，
   請用 `calendar.estimate_sale()` 對 as_of 以前的特賣推估。
   （2026-10-22 稽核補記）實作的「現在」是 `as_of >= 現在 - 1 天`（`store/query.py` 的 `LIVE_WINDOW`）：一天以內的 as_of 也附上未來特賣與預估。
