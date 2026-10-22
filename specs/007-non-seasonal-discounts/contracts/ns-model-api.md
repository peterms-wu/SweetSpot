# Contract: 非季節預測模型介面

和季節模型的介面（004 [model-api](../../004-deeper-discount-model/contracts/model-api.md)）分開。
季節模型的輸出以「未來第 k 場季節特賣」為單位，非季節模型以「未來 h 天」為單位，兩者不共用 `Model` 協定。

## 介面

```text
class NSModel(Protocol):
    name: str                      # "non-seasonal"
    version: str                   # "1.0.0"
    params: Mapping[str, Any]      # {"smoothing": int, "history": "TW" | "TW+US", "clock": bool}

    @classmethod
    def from_params(cls, params) -> NSModel   # CLI 字串參數由模型轉換；未知參數或值 → ValueError

    def confidence_levels(self) -> Mapping[str, str]   # normal / low 的含義，寫進每份輸出
    def prepare(self, population: NSPopulation) -> None   # 每個 (as_of) 呼叫一次
    def predict(self, game: NSEvidence) -> NSOutput       # 見 data-model.md
```

- 註冊表 `NS_REGISTRY`、`build_ns_model(name, params)`，以及 `CURRENT_NS_MODEL: tuple[name, version, params] | None`。
  寫法同季節模型的 `REGISTRY` 與 `CURRENT_MODEL`。
- 框架負責：
  - 讀取資料，並截斷在分析時點。
  - 判定非季節到價與非季節促銷（依分析時點已開始的季節特賣）。
  - 產生 NSEvidence 與 NSPopulation。
  - 檢查輸出、計分。
- 模型只根據收到的結構計算，不讀資料庫、不讀時鐘。

## 輸出的保證（框架檢查，違反時該款為 `model-error`，憲章 III）

1. `probabilities` 是 3 × 19，順序為 h = (30, 60, 90)、d = (5, 10, …, 95)。
2. 每個值都在 [0, 0.99]，而且不是 NaN。
3. 同一個 h，d 越深值不增加；同一個 d，h 越長值不減少。
4. `confidence` ∈ `confidence_levels()` 的鍵。
5. `basis` 的日期都 ≤ `as_of`。

## `non-seasonal` 1.0.0 的規則

見 [research R1](../research.md)，採用時寫進模型定義。

| 參數 | 值域 | 網格 |
|---|---|---|
| `smoothing` | 正整數（月） | 1、2、5 |
| `history` | `TW`、`TW+US` | 兩者 |
| `clock` | `true`、`false` | 兩者 |

**預設參數**：`smoothing=2, history=TW+US, clock=true`（research R0.2 的 M3）。
`from_params({})` 用它們；未採用時產生依據、`ns-backtest` 沒有 `--param` 時也用它們。
依據的來源（`history_source`）因此在未採用時也是 TW+US。

## 原因的措辭（決策層產生，繁體中文）

| 情況 | 措辭（例） |
|---|---|
| 有促銷 | 過去一年季節特賣以外有 6 次促銷，約每 58 天一次，常見 -50%；上一次 2026-08-10（-50%），47 天前 |
| 只有 1 次 | 過去一年季節特賣以外有 1 次促銷：2026-05-02（-30%） |
| 沒有 | 過去一年季節特賣以外沒有促銷 |
| 用美國區補 | 台灣區的價格歷史從 2025-06-26 開始，之前以美國區同一商品的折扣日期補足 |
| 歷史太短 | 價格歷史不到 N 天，機率改用所有遊戲的整體比例（低信心） |
| 正在促銷 | 目前正在季節特賣以外的促銷（-50%，2026-09-20 開始）；以下機率是這次結束之後再次到價 |
| 機率（採用後） | 季節特賣以外降到甜蜜價 NT$X（-Y%）以下的機率：30 天內 35%、60 天內 72%、90 天內 81% |
| 更早到價（採用後） | 可能比 2026 冬特更早到價：60 天內有 72% 的機率在季節特賣以外降到甜蜜價以下（回測中這類說法有 72% 實際到價） |

特殊情況的措辭要在真實願望清單上抽查（004 的教訓），結果寫進驗收文件。
