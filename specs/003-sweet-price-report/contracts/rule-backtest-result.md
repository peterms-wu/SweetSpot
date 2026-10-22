# Contract: 甜蜜價規則回測結果 `steamsage.rule-backtest/1`

`steamsage backtest-rule` 的輸出，寫到 `data/backtests/<開始時間>_sweet-price-<版本>_<模型>_TW_<資料集識別碼前 8 碼>.json`，採原子寫入。
評分方式見 research R10。
（2026-10-22 稽核補記：已被 004 US3（004 T023–T030）與 [005 contracts/cli.md](../../005-waiting-cost/contracts/cli.md) 取代）現在的檔名是 `data/backtests/<開始時間 YYYYMMDDTHHMMSSZ>_sweet-price-<規則版本>[-c<等待成本>]_<模型名稱>-<模型版本>_<參數雜湊前 6 碼>_TW_<資料集識別碼前 8 碼>.json`；`-c<值>` 只在等待成本規則（3.x）出現（`decision/backtest.py` 的 `result_filename`）。

```json
{
  "schema": "steamsage.rule-backtest/1",
  "rule": {"name": "sweet-price", "version": "1.0.0", "constants": {"…": "…"}},
  "preferences": {"…": "…"},
  "model": {"name": "seasonal-freq", "version": "1.0.0", "params": {"min_sales": 2, "history": "TW"}},
  "dataset": {"region": "TW", "dataset_id": "d547c29d…", "cutoff": "2026-09-25T00:00:00Z",
              "schedule": ["2025-02-01", "…"], "window_months": [0, 12], "games": 2528},
  "decisions": {"total": 46000, "now": 13033, "soon": 0, "wait": 0, "low": 0, "beyond_window": 380,
                "decision_error": 0},
  "hit_rate": {
    "overall": {"hits": 22365, "misses": 7176, "censored": 3263, "rate": 0.757},
    "by_group": [{"group": "soon", "hits": 0, "misses": 0, "censored": 0, "rate": null}, "…"],
    "by_confidence": [{"group": "normal", "…": "…"}, {"group": "low", "…": "…"}]
  },
  "timing_error": {"n": 23817, "mean": 0.02, "mean_abs": 0.29, "distribution": {"-1": 743, "0": 19430, "1": 2097}},
  "now_followup": {"evaluated": 3813, "deeper_within_12m": 1855, "rate": 0.487,
                   "by_confidence": [{"group": "normal", "evaluated": 3437, "deeper": 1762}, "…"],
                   "extra_saving_twd": {"median": 49, "p75": 90, "p90": 179}},
  "errors": [{"app_id": 1, "as_of": "2025-03-01", "reason": "…"}],
  "run": {"started_at": "…", "finished_at": "…", "seconds": 11.0, "steamsage_version": "…"}
}
```

範例數字取自 plan 階段的原型（research R0），只示範格式。

## 保證事項

1. 只用 002 台灣區回測資料集的遊戲與排程；`dataset.dataset_id` 與 `steamsage backtest --region TW` 在同一截止時間下相同。
2. 每個分析時點的決策只用當時可取得的資料，也就是截斷後的證據與 ITAD 序列在分析時點的狀態。洩漏測試的方式同 002：竄改分析時點之後的資料，決策不變。
3. 截斷的案例不計入到價率；超出 12 個月窗口的甜蜜時點只計數。
4. 「現在買的後續」只計算分析時點之後有完整 12 個月資料的案例。
5. 同一份資料、規則版本、偏好與模型重跑，結果（`run` 除外）完全相同。
