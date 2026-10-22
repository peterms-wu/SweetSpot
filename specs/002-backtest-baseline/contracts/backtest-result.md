# Contract: 回測結果 `steamsage.backtest/1` 與比較紀錄

## 回測結果檔

位置：`data/backtests/<UTC 時間>_<模型名稱>-<版本>_<參數雜湊前 6 碼>_<區域>_<各區 dataset_id 合併雜湊前 8 碼>.json`
（本機，`.gitignore` 排除）。先寫 `.json.tmp`，完成後才改名（FR-017）。

```json
{
  "schema": "steamsage.backtest/1",
  "model": {"name": "seasonal-freq", "version": "1.0.0", "params": {"min_sales": 1, "history": "TW"}},
  "dataset": {
    "cutoff": "2026-09-24T00:00:00Z",
    "levels": [5, 10, "…", 95],
    "regions": {
      "TW": {"dataset_id": "3f9a…（64 位十六進位）", "schedule": ["2025-02-01", "…", "2026-09-01"],
             "window_months": [0, 12], "games": 2590},
      "US": {"dataset_id": "b71c…", "schedule": ["2012-08-01", "…", "2025-09-01"],
             "window_months": [12, 60], "games": 1744}
    },
    "calendar_hash": "…"
  },
  "regions": {
    "TW": {
      "brier": 0.1027,
      "reference_brier": 0.1427,
      "games": 2590,
      "units": {"scored": 2784074, "censored": 51230, "not_held": 0},
      "by_horizon": [{"group": "0-3m", "brier": 0.09, "games": 2590, "units": 812345}],
      "by_level": [{"group": 50, "brier": 0.13, "games": 2590, "units": 146530}],
      "by_confidence": [{"group": "normal", "brier": 0.10, "games": 2570, "units": 2700000},
                        {"group": "low", "brier": 0.16, "games": 900, "units": 84074}],
      "by_pool": [{"group": "wishlist", "brier": 0.11, "games": 66, "units": 70000}],
      "calibration": [{"bin": [0.0, 0.1], "mean_forecast": 0.03, "observed_rate": 0.05, "units": 900000}],
      "hit_rate": {"point_forecasts": 40000, "hits": 31000, "rate": 0.775,
                   "never_predicted": 8000, "never_predicted_but_occurred": 900, "censored": 1200},
      "timing_error": {"n": 30000, "mean": 0.4, "mean_abs": 0.9,
                       "distribution": {"-2": 100, "-1": 3000, "0": 20000, "1": 5000, "2": 1900},
                       "not_occurred_in_window": 2500}
    },
    "US": {"…": "同上；by_horizon 的分組為 12-24m、24-36m、36-60m"}
  },
  "per_game": {"TW": {"1145360": [1520, 118.4]}, "US": {"…": "…"}},
  "errors": [{"app_id": 123, "as_of": "2025-06-01", "reason": "model-error: …"}],
  "run": {"started_at": "…", "finished_at": "…", "seconds": 95.2, "steamsage_version": "0.2.0"}
}
```

- `per_game[region][app_id] = [評分單位數, 平方誤差總和]`。每款遊戲的平均 Brier = 總和 / 單位數。
- 所有 Brier 都是「先算每款遊戲的平均，再平均所有遊戲」（FR-018）。分組時在組內用同樣的方式計算。
- `calibration` 的 `mean_forecast` 與 `observed_rate` 用同樣的權重（1/該遊戲的單位數），`units` 是原始數量。
- 鍵依字母排序寫出。除了 `run` 以外，重跑的內容逐位元相同（SC-005）。

> 2026-10-22 稽核補記：格式名仍是 `steamsage.backtest/1`，後來只新增欄位（[004 contracts/results-and-decisions.md](../../004-deeper-discount-model/contracts/results-and-decisions.md)、[008 data-model](../../008-new-game-forecast/data-model.md)）：
> - `dataset.split`（`{"name": "all"|"tuning"|"validation", "salt": …}`）與 `dataset.regions.<區>.population_games`（004）。
> - `regions.<區>` 多了 `deeper_than_past`、`by_own_sales`（004；008 加上 `3-5`、`6+` 組）與 `finished_calibration`（008）。
> - 頂層多了 `per_game_by_own_sales` 與 `release_facts`（008）。
> - `errors[]` 每筆另有 `region`：從 002 起就有，上面的範例沒寫。

## 比較紀錄（`docs/model/comparisons.md`，只附加）

以下是格式範例；Brier 取自探索性回測，區間是示意數字。

```markdown
## 2026-10-02 · seasonal-freq 1.0.0 {history=TW+US, min_sales=1} vs 現行 seasonal-freq 1.0.0 {history=TW, min_sales=1}

- 資料集：台灣區 `3f9a1c2e…`、美國區 `b71c04d9…`（截止 2026-09-24）
- 結果檔：`…_a.json`、`…_b.json`

| 區域 | 現行 Brier | 候選 Brier | 差距（候選 − 現行） | 95% 區間 | 遊戲數 |
|---|---|---|---|---|---|
| 台灣區（≤12 個月） | 0.1027 | 0.1131 | +0.0104 | [+0.0085, +0.0124] | 2590 |
| 美國區（1–5 年） | 0.2178 | —（未重跑） | 0（依構造相同） | — | 1556 |

**判定：未優於**。台灣區的區間上限 +0.0124 ≥ 0。候選只跑了台灣區；兩者只差 `history` 參數（`tw_only_params`），美國區結果依構造相同，未重跑。
```

判定規則（FR-029）：台灣區區間上限 < 0，**而且**美國區區間下限 ≤ 0，才判定「優於」。
重抽樣 2,000 次，依遊戲成對抽樣；每區的種子 = `int(該區 dataset_id[:8], 16)`。

可以比較的條件（FR-028，逐區域）：
- 台灣區必須兩份都有；兩份都有的區域，`dataset_id` 必須相同，每款遊戲的評分單位數也必須相同。
- 只有一份有美國區時，兩個模型的名稱、版本相同，而且參數差異全部屬於模型的 `tw_only_params`，才可以比較。
  美國區差距視為 0，並在紀錄中註明「依構造相同，未重跑」。
- 其他情況拒絕比較。

  （2026-10-22 稽核補記）實際上兩份**都沒有**美國區時，也走上一條的條件：模型名稱、版本相同，而且參數差異全部屬於 `tw_only_params`（包括參數完全相同）就照樣比較，美國區記成「依構造相同，未重跑」、遊戲數 0、視為沒有變差；不符合時才拒絕（`forecast/backtest/compare.py` 的 `compare_results`）。
