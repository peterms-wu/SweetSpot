# Contract: 回測結果、規則回測結果與決策輸出的新增欄位（feature 004）

三份契約都只**新增**欄位，schema 名稱與版本不變，舊的結果檔與紀錄仍可讀。

- `steamsage.backtest/1`（[002](../../002-backtest-baseline/contracts/backtest-result.md)）
- `steamsage.rule-backtest/1`（[003](../../003-sweet-price-report/contracts/rule-backtest-result.md)）
- `steamsage.decision/1`（[003](../../003-sweet-price-report/contracts/decision-output.md)）

缺少新欄位時，讀取端視為 `split = all`、沒有分組、沒有 `notes`。

## `steamsage.backtest/1`

```json
{
  "dataset": {
    "split": {"name": "tuning", "salt": "steamsage-004-split"},
    "regions": {"TW": {"dataset_id": "…", "games": 1270, "population_games": 2583, "…": "…"}}
  },
  "regions": {
    "TW": {
      "deeper_than_past": {"brier": 0.0960, "games": 1180, "units": 357676,
                           "calibration": [{"bin": [0.0, 0.1], "mean_forecast": 0.020, "observed_rate": 0.052, "units": 227635}]},
      "by_own_sales": [{"group": "0", "brier": 0.17, "games": 1245, "units": 0}, {"group": "1", "…": "…"},
                       {"group": "2", "…": "…"}, {"group": "3+", "…": "…"}]
    }
  }
}
```

**保證**：

- `split.name` 是 `all` 時，識別碼和 002 的算法相同。
- 其他切分的識別碼另外包含 `split`、鹽，以及全部合格遊戲的清單與序列。
- `deeper_than_past` 的條件由框架定義：本身至少有 1 場已結束的季節特賣，而且 d > 其中的最深折扣。和模型無關。
- 彙總方式和整體 Brier 相同：每款遊戲同權重。

## `steamsage.rule-backtest/1`

```json
{
  "rule": {"name": "sweet-price", "version": "2.0.0", "constants": {"p_min_months": 12, "…": "…"}},
  "dataset": {"split": {"name": "validation", "salt": "steamsage-004-split"}, "…": "…"},
  "sweet_timing": {"next": 15858, "within_1y": 6825, "beyond_1y": 0},
  "follow_advice": {
    "overall": {"evaluated": 20095, "censored": 2588,
                "saving_twd": {"mean": 208, "median": 120, "p75": 300, "p90": 520},
                "wait_days": {"mean": 52, "median": 0}},
    "by_group": [{"group": "now", "…": "…"}, {"group": "soon", "…": "…"}, {"group": "wait", "…": "…"},
                 {"group": "low", "…": "…"}],
    "by_confidence": [{"group": "normal", "…": "…"}, {"group": "low", "…": "…"}]
  },
  "hindsight": {"evaluated": 18000, "saving_twd": {"mean": 400, "median": 300}}
}
```

範例中的數字只是示意。

**照建議買的定義**（research R6）：

- **判為現在買**：以現價買，等 0 天。
- **其他分組**：分析時點之後，第一次折扣 ≥ 甜蜜價的折扣就買，任何折扣都算；
  實付價格 = 那個價格狀態的原價 × (100 − 折扣) / 100，以分為單位並無條件捨去。
- **12 個月內都沒到價**：以分析時點 + 12 個月的價格狀態買，等 365 天。
  （2026-10-22 稽核補記：程式的「+ 12 個月」是日曆月（`src/sweetspot/timeutil.py` 的 `add_months`），等待天數是兩個時刻相減，
  跨過 2 月 29 日時是 366 天。`src/sweetspot/decision/backtest.py` 的 `follow_advice`。）
- **截斷**：資料已知時間 < 分析時點 + 12 個月，而且還沒到價。
- **多省**：現價減實付價格，可以是負數，例如等到最後原價反而漲了。
- **事後最低價**：只算有完整 12 個月資料的決策，值為現價減 12 個月內的最低價格。

## `steamsage.decision/1`

```json
{
  "rule": {"name": "sweet-price", "version": "2.0.0", "constants": {"p_min_months": 12, "…": "…"}},
  "rule_backtest": {"date": "…", "region": "TW", "window_months": 12, "hit_rate": {"soon": 0.93, "wait": 0.6, "low": 0.07},
                    "now_deeper_within_12m": 0.42, "model": {"name": "seasonal-record", "version": "1.0.0", "params": {}},
                    "source": "docs/model/model-definition.md"},
  "notes": ["12 個月內最低價可能更低：回測中判為現在買之後 12 個月內，仍有 42% 出現更深折扣"]
}
```

**保證**：

- `rule_backtest` 只在「現行規則＋現行模型與參數」有對照的數字時才非 null，並記錄它屬於哪個模型（research R9）。
- `notes` 由決策核心產生；報告只顯示它，不寫死任何關於模型限制的文字。
- 規則 2.0.0 的決策原因把「長期最低價」改稱「12 個月內最低價」，範圍一律是「未來 12 個月（到某場特賣）」。
- `deeper-possible` 標籤只在現行模型的 `predicts_deeper` 為 False 時出現。
