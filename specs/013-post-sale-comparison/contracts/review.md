# Contract: `steamsage review` 與 `steamsage.review/1`

**Feature**: 013-post-sale-comparison | **Date**: 2026-10-12

## 1. 指令

```text
steamsage review [--config CONFIG] [--json] [--sale SEASON-YEAR] [--record FILE] [--today YYYY-MM-DD]
                 [--force] [--no-recompute] [--doc] [--out OUT]
```

| 參數 | 說明 |
|---|---|
| `--sale` | 例如 `autumn-2026`。預設：行事曆中最近一場已結束的季節特賣 |
| `--record` | 指定紀錄檔（`data/forecasts/` 中的檔名或路徑）。預設：特賣開始前最後一份正式紀錄（research R3）。（2026-10-22 稽核補記）給了 `--record` 時只要求紀錄讀得到、`as_of` 早於特賣**結束**，也接受非正式紀錄；`as_of` 在特賣開始之後時 `hours_before_start` 是負的（review/target.py） |
| `--today` | 執行對照的時點（UTC 日期，當天 00:00）；決定非季節期間是否到期。預設現在 |
| `--force` | 特賣結束不到 3 天也執行；結果的 `target.forced = true` |
| `--no-recompute` | 不做 US5 的重算（約省 12 秒） |
| `--doc` | stdout 改印 `comparisons.md`「事後對照」一節的草稿（Markdown），數字全部來自同一份結果 |
| `--out` | 結果 JSON 的路徑。預設 `data/reviews/<season>-<year>_<紀錄 as_of>_<today>.json` |

- **唯讀**：只讀資料庫（`PriceStore.open` 的唯讀連線）、`data/forecasts/`、行事曆檔；只寫 `--out` 一個檔案（暫存檔再改名）。不取寫入鎖、不連網。
  （2026-10-22 稽核補記）另外和其他指令一樣，在當天日誌 `data/logs/sweetspot-<YYYYMMDD>.log` 留一行結果行（2026-10-18 起每個指令共用，cli.py 的 `log_result`）。`--doc` 時也照樣寫 `--out`。
- stdout 預設是人看的摘要（第 4 節）；`--json` 時是 `summary` 物件。

### 結束代碼

| 代碼 | 情況 |
|---|---|
| 0 | 完成，沒有「無法對照」也沒有依每日紀錄補正的遊戲 |
| 2（部分完成） | 完成，但有 `no-actual`、補正（D2）、讀不到的紀錄被跳過、或 `forced` |
| 1（失敗） | 指定的特賣不存在或不是季節特賣、特賣未結束、結束不到 3 天而沒有 `--force`、找不到開賣前的正式紀錄、資料庫或紀錄讀取失敗。（2026-10-22 稽核補記）給了 `--record` 時改成：找不到可讀的這份紀錄、或它的 `as_of` 不在特賣結束以前 |

失敗時不寫任何結果檔（不輸出部分結果冒充完整）。

## 2. `steamsage.review/1`（JSON）

鍵依字母排序、`ensure_ascii = false`；同一份資料、同一組參數輸出逐位元組相同（`run` 區塊除外，見下）。

```jsonc
{
  "schema": "steamsage.review/1",
  "target": {
    "sale": {"season": "autumn", "year": 2026, "label": "2026 秋特", "start": "2026-10-01T17:00:00Z", "end": "2026-10-08T17:00:00Z"},
    "record": {"file": "20260930T183137Z.json.gz", "as_of": "2026-09-30T18:31:37Z", "schema": "steamsage.decision/2",
               "model": {...}, "rule": {...}, "bundle_rule": {...}, "hours_before_start": 22.5},
    "during": {"files": ["20261001T183501Z.json.gz", ...], "missing_days": []},
    "today": "2026-10-12T00:00:00Z", "forced": false, "skipped_records": []
  },
  "definitions": {"primary": "sale-max", "secondary": "crossing"},        // D1
  "games": [ GameReview, ... ],                                           // data-model §2，依 app_id 排序
  "summary": {
    "counts": {"records": 68, "reviewed": 65, "no_actual": 0, "not_scored": 3, "corrected": 1},
    "seasonal": {...}, "decisions": {...}, "bundles": [...], "non_seasonal": {...}, "recompute": {...} | null,
    "mismatches": [...]
  },
  "sources": {"backtest": {"seasonal": "docs/model/model-definition.md#seasonal-record-v110現行", "rule": "...", "non_seasonal": "..."}},
  "run": {"started_at": "...", "seconds": 3.1, "steamsage_version": "..."}
}
```

- 比例與分數的物件：`{"value": 0.9615, "n": 26, "interval": [0.88, 1.0], "backtest": 0.924, "backtest_source": "...", "differs": false}`。
- 機率與分數保留 4 位小數；金額以分（`*_cents`）。
- `run` 是唯一隨執行時間變動的區塊；逐位元組比較（FR-018、SC-004）時去掉它。

> 2026-10-22 稽核補記（review/contract.py、review/run.py、review/score.py）：
> - `summary.counts` 還有第 6 個鍵 `groups`：紀錄中各分組的款數（`{分組: 款數}`，沒有分組的記為 `na`）。
> - `summary.mismatches` 是物件 `{"corrected": [...], "noted": [...]}`（013 T019）：依每日紀錄補正的、只註記的；每一項是 `{app_id, name, history_max_cut, daily_max_cut}`。
> - `sources` 是平的 `{"seasonal", "rule", "non_seasonal"}`，沒有 `backtest` 這一層；`rule`、`non_seasonal` 取自紀錄的 `rule_backtest.source`、`non_seasonal.backtest.source`，紀錄沒有時是 `null`。

## 3. 計分規則（摘要；細節見 research R1–R7）

| 部分 | 單位 | 到價／結果 | 只計 |
|---|---|---|---|
| 季節機率 | 遊戲 × 等級（這一場） | 主要：特賣期間最深折扣 ≥ d；次要：分析時點之後首次進入 ≥ d、在特賣結束以前 | `reviewed` 而且曲線有這一場 |
| 決策 | 遊戲 | 特賣期間最低價 ≤ 甜蜜價 | `reviewed` 而且有決策 |
| 提早到價 | 遊戲 | 特賣期間第一份判為「現在買」的紀錄 | `timing = early` |
| 非季節 | 遊戲 × 期間 × 等級 | (as_of, as_of + h] 內季節特賣以外到價 | `due ≤ today` 而且價格歷史已知到 due |
| 組合包 | 組合包 | 每日紀錄的最低價、各內容是否到需要的等級 | 有建議的純粹組合包 |
| 重算 | 遊戲 × 等級 | 同季節機率的主要定義 | 三者都有這一場的遊戲 |

## 4. 文字摘要（stdout，例）

```text
事後對照：2026 秋特（台北 10/2 01:00 – 10/9 01:00）
預測紀錄：20260930T183137Z（開賣前 22.5 小時；seasonal-record 1.1.0、sweet-price 2.1.0）
對照 65/68 款（3 款紀錄中沒有預測）；依每日價格紀錄補正 1 款（劍星）

季節機率  Brier 0.040 [a, b]（特賣最深折扣）；回測的定義 0.125 [c, d]（回測：只計已結束 0.0604）……
即將到價  25/26 到甜蜜價 96% [a, b]（規則回測 92.4%）；未到：CRYMACHINA 慟哭奇機（整場沒有打折）
繼續等    提早到價 6 款，6 款在特賣第一天改成現在買；錯過 0
現在買    9 款：等到特賣 更低 0、相同 9、更高 0
組合包    E33 x Dispatch 推算 NT$1,063 → 實際 NT$1,062；DAVE THE DIVER x MiSide NT$366 → NT$350
非季節    0 個單位到期；30 天最早 2026-10-30 可對照
重算      正式紀錄 0.040、重算 0.040、基準模型 0.096（不判定優劣）
結果：data/reviews/autumn-2026_20260930T183137Z_20261012.json
```

（上例的數字是 plan 原型的結果，正式輸出以實作為準。）
