# Contract: PriceStore 新增的唯讀方法

延伸 [feature 001 的 store-api](../../001-price-data-foundation/contracts/store-api.md)。既有方法與保證不變。

```python
class PriceStore:
    def history_known_until(self, app_id: int, region: str = "TW") -> datetime | None:
        """這款遊戲在這個區域的 ITAD 歷史，最後一次確認到的時間。

        = max(該區域最新的 history_fetches.fetched_at, 該區域 legacy-itad 觀測的最新 retrieved_at)。
        從未取得過歷史時回傳 None。
        """

    def series_rows(self, app_ids: Sequence[int], region: str, as_of: datetime
                    ) -> dict[int, list[Observation]]:
        """一次取得多款遊戲的 ITAD 歷史（itad-history 與 legacy-itad；不含 steam-current），
        只含 observed_at <= as_of、anomaly 為 NULL 的觀測，依 app_id、observed_at、source 排序。
        給回測一次讀取全部資料用（research R7）；語意與逐款呼叫 observations() 相同。"""
```

實作時補上的唯讀方法（狀態判定與分組需要，analyze 後發現 store-api 沒有提供）：

```python
    def history_known_until_all(self, region: str = "TW") -> dict[int, datetime]:
        """history_known_until() 的批次版本，一次查詢所有遊戲。"""

    def itad_mapping_state(self, app_id: int) -> str | None:
        """最新的 ITAD 對應核對結果：verified、verified-legacy、rejected、pending；沒有對應時為 None。"""

    def calendar_events(self) -> list[SaleEvent]:
        """行事曆中的所有特賣（含未來已公告的）。只給回測**評分**對照實際特賣日期用；預測一律用 sales(as_of)。"""

    def sample_pools(self) -> dict[int, str]:
        """每款遊戲的樣本來源，優先順序 wishlist > related > broad > legacy（research R4 的分組）。"""
```

## 保證事項（contract tests）

1. `history_known_until` 只用在評分，不得傳給模型（由 model-api 的框架保證）。
2. `series_rows(..., as_of)` 的每一筆都滿足 `observed_at <= as_of`，而且與逐款呼叫
   `observations(app, as_of, region)` 再過濾來源的結果完全相同。
3. 兩個方法都不寫入資料庫。
