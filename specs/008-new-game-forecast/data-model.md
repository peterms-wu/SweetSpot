# Data Model: 新遊戲與低信心的預測（feature 008）

不改資料庫。以下是程式內的資料結構與結果檔新增的欄位；決定依據見 [research.md](research.md)。

## 模型看得到的資料

### `GameEvidence`（新增欄位）

| 欄位 | 型別 | 說明 |
|---|---|---|
| `release_date` | `date \| None` | 目標遊戲的發行日（遊戲事實 `release_date`，靜態欄位）；未知為 None（憲章 I） |

### `PopulationView`（新增欄位）

| 欄位 | 型別 | 說明 |
|---|---|---|
| `release_dates` | `Mapping[int, date \| None]` | 傳入 `population_view` 的每款遊戲的發行日（包括沒有紀錄的遊戲），未知為 None |

- 框架在每次執行開始時，對所有遊戲讀一次發行日（research R3）。
- 模型不讀資料庫、不讀時鐘。

## 模型 `seasonal-record` 1.1.0

### 參數

| 參數 | 值域 | 1.0.0 的等價值 | 說明 |
|---|---|---|---|
| `min_sales` | ≥ 1 的整數 | 同 1.0.0 | 沿用 |
| `half_life` | ≥ 0 | 同 1.0.0 | 沿用 |
| `hazard_history` | `TW`／`TW+US` | 同 1.0.0 | 沿用 |
| `low_base` | `population`／`new`／`new-split` | `population` | 低信心路徑的依據（R1） |
| `shrink` | ≥ 0 的數字（場） | `0` | 見過的等級向全體比例收縮的強度（R2） |

- 參數驗證沿用 1.0.0 的做法：未知的參數或不合法的值直接拒絕，並說明原因。
- `tw_only_params` 不變。`low_base` 與 `shrink` 在美國區也有作用，所以美國區 MUST 一起回測。

### 結構常數

| 常數 | 值 | 依據 |
|---|---|---|
| 新遊戲的判定：第一場紀錄開始時距發行日 | ≤ 365 天 | research R0.2 |
| 經驗累積的最少序列數 | 30（不足時沿用前一場的值） | research R0.2 |

### 每個分析時點的準備結果（`prepare` 之後）

- **新遊戲序列**：三組，分別是全部新遊戲、預購（第一場在發行日以前）、其餘。每個序列是依時間排列的最大折扣。
- **經驗累積表** F[k][d]：依需要的場數建立並快取。保證隨 k 不遞減、隨 d 不遞增。
- **全體每場的比例** b(d)：沿用 `seasonal-freq` 的整體比例。

### 輸出（契約 `steamsage.forecast/1` 不變）

- **低信心路徑**（`low_base` ≠ `population`）：
  - 機率 = F[k][d]，信心 `low`。
  - `evidence` 新增 `low_sequences`（`all-new`／`pre-release`／`released`，用的是哪一組序列）、`new_games`（序列數）與 `release_date`。
- **一般信心**：見過的等級的每場比例為 (n · p_w + a · b) / (n + a)。
  - `evidence` 新增 `shrink`，以及收縮前的比例 `own_share_raw`（只記 d = M 這一格，供原因與檢查）。
- **原因**：依 contracts/model-api.md 的措辭。

## 回測結果 `steamsage.backtest/1`（只新增欄位）

**加權**：`finished_calibration.brier` 與各分組的 `brier` 照 002 的慣例，先算每款遊戲的平均再平均（每款同權重）；`bins` 與分組的 `n`、`predicted`、`actual` 是逐單位的平均。research R0.3 的「已結束 Brier 0.0594 → 0.0546」是逐單位平均，同一份資料每款同權重是 0.0725（`prototype/p6_gate_probe.py`）。

### 每個區域 `regions.<R>`

| 欄位 | 說明 |
|---|---|
| `by_own_sales` | 原本有 `0`、`1`、`2`、`3+`；新增 `3-5`、`6+`（`3+` 保留，舊結果照讀） |
| `finished_calibration` | 只計特賣在資料內已結束的單位（FR-011），結構見下 |

`finished_calibration`：

```text
{
  "units": 1015759,
  "brier": 0.0725,          # 002 的慣例：每款遊戲同權重；1.0.0 調參組台灣區
  "bins": [{"lo": 0.0, "n": ..., "predicted": ..., "actual": ...}, ...],        # 每 0.1 一組
  "groups": {
    "confidence": [{"group": "normal", "n": ..., "predicted": ..., "actual": ..., "brier": ...}, ...],
    "own_sales": ["0", "1", "2", "3-5", "6+"] 各一列,
    "seen": ["seen", "deeper"],
    "distance": ["M", "M-5", "M-10", "<=M-15", "M+5", ">=M+10"]
  }
}
```

### `per_game_by_own_sales.<R>.<app>`（頂層，和 `per_game` 並列）

{組名: [單位數, 誤差平方和]}，供場數分組的成對重抽樣。放在 `per_game` 旁邊而不是裡面，因為 `compare` 讀 `per_game` 的 `[n, sse]` 格式（實作時的調整，T010）。

### `release_facts`（頂層）

`{"count": 2583, "known": 2583, "sha256": "…"}`：本次用到的發行日。不影響資料集識別碼（research R3）。

## 比較紀錄（`docs/model/comparisons.md`，只附加）

`compare --target-groups 0,1` 時，紀錄新增：
- 條件說明：「另外要求本身 0 場、1 場兩組的台灣區 Brier 都較低（點估計）」。
- 各組兩個版本的 Brier、差距與 95% 區間。
- 只計已結束的「預測平均 − 實際比例」。
- 判定：兩個條件都成立才是「優於」；其中一個不成立時，寫出是哪一個。

## 網格結果

每一列新增 `excluded_reason` 的兩種值：
- `own-sales-worse:<組名>`：FR-004 排除，寫出是哪一組顯著變差。
- `fr-003`：見過的等級沒有收縮（`shrink = 0`），由模型類別的 `grid_exclusion(params)` 判斷；仍列出分數作為對照。

> 2026-10-22 稽核補記：`excluded_reason` 只在記憶體的 `GridRow`（`forecast/backtest/grid.py`），不輸出：`grid --json` 摘要的 `rows` 只有布林 `excluded`（`commands.py`），
> `docs/model/comparisons.md` 的網格紀錄寫的是中文句子（例如「0 場（低信心）顯著變差（FR-004），排除」「違反 FR-003（見過的等級沒有收縮），僅供對照」）。

## 規則回測

沒有新欄位。並列時，`compare-rule` 的願望清單差異照舊。
「低信心 → 現在買」的決策數由 quickstart 的比對步驟從兩份結果的 `cases` 計算，寫進比較紀錄。

## 狀態與生命週期

- `CURRENT_MODEL`：
  - 1.1.0 通過驗證組比較（FR-009 的兩個條件），而且使用者同意之後，才改成 1.1.0 與網格選定的參數。
  - 否則維持 1.0.0。
- 1.0.0 的類別永遠保留。紀錄、比較文件與舊結果檔上的標示不變。
