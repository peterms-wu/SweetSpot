# Contract: 模型介面（給基準模型與 feature 004 的模型）

模型只負責「填機率」。預測格子（時點 × 折扣等級）、證據截斷、狀態判定、輸出驗證與評分都由框架負責。
這樣，每個模型在同一份資料集上一定得到相同的評分單位，才能成對比較。

```python
class Model(Protocol):
    name: str                      # 例如 "seasonal-freq"
    version: str                   # 語意化版本；規則或參數改變就遞增（憲章 V）
    params: Mapping[str, Any]      # 會完整寫進每份輸出
    tw_only_params: frozenset[str] # 只影響台灣區目標的參數（基準模型為 {"history"}），供 compare 判斷美國區可否省略

    def prepare(self, population: PopulationView) -> None:
        """每個（分析時點, 目標區域）呼叫一次。population 已截斷到 as_of。"""

    def predict(self, game: GameEvidence, points: Sequence[SalePoint],
                levels: Sequence[int]) -> ModelOutput:
        """回傳 len(points) × len(levels) 的累積機率、信心等級、原因與證據摘要。"""

def build_model(name: str, params: Mapping[str, str]) -> Model   # 註冊表；參數不合法時丟出 ValueError
CURRENT_MODEL: tuple[str, str, Mapping[str, Any]]                 # 現行模型（R9）
```

> 2026-10-22 稽核補記：
> - `confidence_levels() -> Mapping[str, str]`（各信心等級的含義，寫進每份預測輸出的 `confidence_levels`）從 002 起就在 Protocol 裡，上面沒寫。
> - 已被 [004 contracts/model-api.md](../../004-deeper-discount-model/contracts/model-api.md) 擴充：Protocol 多了 `predicts_deeper: bool` 與 `deeper_caveat: str`。
> - 已被 [008 contracts/model-api.md](../../008-new-game-forecast/contracts/model-api.md) 取代：註冊表依（名稱、版本），`build_model(name, params=None, version=None)`，`name` 也可以寫成 `名稱@版本`；沒有版本時，和現行模型同名取現行版本，否則取最新版本。
> - `CURRENT_MODEL` 現在是 `("seasonal-record", "1.1.0", {min_sales=1, half_life=2, hazard_history="TW+US", low_base="new-split", shrink=0.5})`（008，2026-09-27 採用；見 [008 contracts/cli.md](../../008-new-game-forecast/contracts/cli.md)）。`seasonal-freq` 1.0.0 仍註冊，作為基準。

## 框架對模型的保證

1. `game` 與 `population` 中所有資料的時間都 ≤ as_of；`sale_history` 只含已結束的特賣（R3）。
2. 目標區域是 US 時，`game.series` 與 `population` 都只有 US（clarify 的決定）。
3. `prepare` 一定在同一個分析時點的 `predict` 之前呼叫。
4. 遊戲依 app_id 升冪處理，分析時點依時間升冪處理。

## 模型必須遵守

1. 不得讀取資料庫、檔案、網路或目前時間。只用傳入的參數，這是洩漏測試能夠成立的前提。
2. 相同輸入必須得到相同輸出。需要隨機性時，種子由參數與輸入決定。
3. 輸出必須符合 FR-004（範圍與單調性）；不符合時，框架記為 `model-error`。
4. `reasons` 用繁體中文，說明用了哪些資料與算法。美國區資料必須標示「美國區」。
5. 信心等級只能是 `normal` 或 `low`；新增等級需要修改本契約，並以回測證明（spec clarify）。
