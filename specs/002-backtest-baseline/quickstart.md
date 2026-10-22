# Quickstart: 回測框架與基準模型（驗收情境）

前提：feature 001 的資料庫已經建好（`data/steamsage.db`），`uv run pytest` 全部通過。
以下指令都不連網，也不修改資料庫。格式細節見 [contracts/](contracts/)。

## A. 自動測試

```powershell
uv run pytest
```

預期：全部通過。這些測試包括：
- 人工序列上的評分與指標，驗算結果和手算一致（SC-004）。
- 洩漏測試（SC-001）。
- 重跑結果相同（SC-005）。
- 比較判定（SC-008）。

**這只代表功能正確，不代表預測準確**（憲章：功能測試與預測準確分開報告）。

## B. 願望清單預測（使用情境 1、SC-002、SC-003）

```powershell
uv run steamsage forecast
uv run steamsage forecast --out data\forecast.json
```

預期：
- 每款遊戲一行：狀態、信心、下一場季節特賣 ≥ -50% 的機率。
- 已發行、有歷史的付費遊戲都是 `ok`，資料少的標 `low`。未發行的是 `unreleased`，並附原因。
- JSON 符合 `steamsage.forecast/1`：
  - 時點從下一場還沒開始的季節特賣算起，例如「2026 秋特」。
  - 未公告的特賣標 `estimated`。
  - 每款遊戲都有原因。
- 耗時 < 1 分鐘（SC-007）。

## C. 過去時點的預測（使用情境 1 AS5、FR-008）

```powershell
uv run steamsage forecast --as-of 2025-06-01 --app 1145360 --json
```

預期：
- 時點全是從 2025-06-01 以前的特賣推估的，不會出現事後才公告的日期。
- 證據只包含 2025-06-01 以前已結束的特賣。

## D. 回測（使用情境 2、SC-006、SC-007）

```powershell
uv run steamsage backtest --region TW --apps-limit 100    # 快速試跑
uv run steamsage backtest                                 # 完整回測，兩區
```

預期：
- 結果寫入 `data/backtests/`。
- 摘要列出兩區的 Brier、參照分數，以及評分、截斷、未舉辦的數量。
- 台灣區的分析時點從 2025-02-01 開始；美國區在行事曆補齊後從 2012 年開始。
- 完整回測 < 30 分鐘（SC-007），預期約 5 分鐘內。實際耗時記錄在 validation.md。
- 中斷時（Ctrl+C）只留下 `.json.tmp`，不留下看起來完整的結果。

## E. 比較與模型定義（使用情境 3、使用情境 4）

```powershell
uv run steamsage backtest --param history=TW --param min_sales=1
uv run steamsage backtest --param history=TW+US --param min_sales=2
uv run steamsage compare data\backtests\<A>.json data\backtests\<B>.json --record
```

> 2026-10-22 稽核補記：現行模型換成 `seasonal-record` 之後，沒有 `--model` 的 `--param` 疊在現行模型上，而它沒有 `history` 參數，上面兩行會以 1 結束（「seasonal-record 1.1.0 沒有這些參數：history」）。要重跑 002 的結果，指定基準模型（參數名是 `min_sales`、`history`）；`--cutoff` 預設是最新的資料，要和舊結果比較時給同一個截止日：
> `uv run sweetspot backtest --model seasonal-freq --param history=TW --param min_sales=1 --cutoff 日期`

預期：
- 輸出兩區的差距、95% 區間與判定，並附加一筆紀錄到 `docs/model/comparisons.md`。
- 對兩份不同資料集的結果（例如一份用 `--apps-limit`）執行 compare：exit 1，並說明差異。
- `docs/model/model-definition.md` 寫明：
  - 基準模型 v1.0.0 的規則與參數依據（網格結果）
  - 每個信心等級的回測分數
  - 已知限制（research R5）

## F. 行事曆補齊（FR-033）

```powershell
uv run steamsage calendar
uv run steamsage calendar --check
```

預期：
- 列出 2012 年起的每場季節特賣，每場都有 https 來源，沒有 SteamDB。
- `--check` 沒有新的漏收提醒。

## G. 洩漏檢查的實機抽查（SC-001）

複製一份資料庫，把某個分析時點之後的所有觀測折扣改成 99，再對同一個分析時點執行 `forecast --as-of`。
預期：輸出（`generated_at` 除外）和原資料庫完全相同。
