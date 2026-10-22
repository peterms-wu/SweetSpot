# Contract: CLI 新增指令與一鍵執行（feature 003）

延伸 [feature 001](../../001-price-data-foundation/contracts/cli.md) 與 [feature 002](../../002-backtest-baseline/contracts/cli.md) 的 CLI 契約。
共用規則不變：

- 進度寫到 stderr，摘要寫到 stdout。
- `--json` 改為輸出 JSON 摘要。

兩個新指令都以唯讀方式開啟資料庫、不取寫入鎖，可以和 `update` 同時執行。只寫 `data/forecasts/`、`data/reports/`、`data/backtests/`。
（2026-10-22 稽核補記：011 起，正式執行的 `report` 在專案資料夾有 `extension/manifest.json` 時，另外寫擴充功能資料檔 `extension/data/sweetspot-extension.json`，見 [011 contracts/extension-ui.md](../../011-chrome-extension/contracts/extension-ui.md)。）

## `steamsage report [--as-of 日期] [--out 檔案] [--open] [--update-exit N]`

**步驟**：

1. 預測願望清單，使用現行模型。
2. 查現價並做決策。
3. 找比較基準。
4. 寫預測紀錄（只有正式執行）。
5. 寫 HTML 報告。

**參數**：

| 參數 | 預設 | 說明 |
|---|---|---|
| `--as-of` | 現在 | 過去的分析時點，只供檢查：不寫紀錄、不比較 |
| `--out` | 正式執行：`data/reports/latest.html`；`--as-of`：`data/reports/asof-YYYY-MM-DD.html` | 報告路徑 |
| `--open` | 不開啟 | 完成後用系統預設瀏覽器開啟報告 |
| `--update-exit` | 無 | `更新資料.cmd` 傳入的 update 結束代碼，寫進 `data_refresh`。（2026-10-22，014 T069）接受任何整數：0–5 以外的代碼（例如被中止的 update 留下的 Windows 狀態碼）當作更新沒有完成，說明和 1 相同；以前只接受 0–5，其他代碼讓 `report` 以參數錯誤結束、不產生報告 |

**摘要欄位**：

- 各組款數：`now`、`soon`、`wait`、`low`、`na`、`decision_error`
- `changed`、`baseline`
- `record`（紀錄路徑，或未寫的原因）、`report`（報告路徑）
- `model`、`rule`、`as_of`、`seconds`

> 2026-10-22 稽核補記：後來新增的參數與摘要欄位——
> - `--rule 版本`（[005 contracts/cli.md](../../005-waiting-cost/contracts/cli.md)）：用非現行規則產生預覽，不寫紀錄、不比較，預設輸出 `data/reports/preview-<版本>.html`。
> - 摘要多了 `preview`（005）、`data_refresh`（`{"update_exit", "note"}`，從 003 起就有，上面沒寫）、`extension`（擴充功能資料檔的路徑；沒寫時 `null`，失敗時 `"未寫入：<錯誤>"`；011）與 `warnings`（009）。

沒有 `--json` 時，stdout 先印每組的款數與變動的遊戲，每款一行。

**結束代碼**：

| code | 意義 |
|---|---|
| 0 | 完成 |
| 2 | 完成，但有需要注意的項目：`model-error` 或 `decision-error`、紀錄寫入失敗、略過了損壞的紀錄、`--update-exit` 不是 0 |
| 1 | 失敗：參數錯誤、資料庫無法開啟、報告無法寫入 |

（2026-10-22 稽核補記）014 T069 起，argparse 判定的參數錯誤也以 1 結束（以前是 argparse 預設的 2），見 [001 contracts/cli.md](../../001-price-data-foundation/contracts/cli.md)。011 起，擴充功能資料檔寫入失敗也以 2 結束，報告與紀錄照常。

紀錄寫入失敗時仍然寫報告，報告頁首註明「本次紀錄未保存，下次仍與原比較基準比較」，結束代碼 2。

## `steamsage backtest-rule [--cutoff 日期] [--apps-limit N]`

- 以現行模型與目前的偏好設定，在 002 的台灣區回測資料集上回測甜蜜價規則。
- 結果見 [rule-backtest-result.md](rule-backtest-result.md)。
- 進度：`規則回測 分析時點 n/N（YYYY-MM-DD）`。
- 摘要欄位：結果檔路徑、到價率（整體、依分組、依信心）、時間誤差、現在買的後續、耗時。
- 結束代碼：0 完成；2 有決策錯誤；1 失敗。

> 2026-10-22 稽核補記：已被擴充。`backtest-rule` 多了 `--model`、`--param`、`--rule`、`--split`（[004 contracts/cli.md](../../004-deeper-discount-model/contracts/cli.md)；`--model` 可加 `@版本`，008）與 `--wait-cost N[,N…]`（只對等待成本規則有效；[005 contracts/cli.md](../../005-waiting-cost/contracts/cli.md)）。`--rule` 現在可選 `1.0.0`、`2.0.0`、`2.1.0`、`3.0.0`、`3.1.0`。給了多個等待成本時，每個值各寫一份結果檔，摘要是清單（每個值一筆）；只有一份時仍是單一物件。

## `steamsage.toml`：新增 `[preferences]`

見 [data-model.md](../data-model.md) 的 Preferences。沒有這個區段時使用預設值；型別或範圍錯誤時整批失敗，結束代碼 1。

## `更新資料.cmd`

```text
uv run steamsage update                                 → 記下 code
uv run steamsage report --open --update-exit <code>     → 記下 report_code
```

依兩個結束代碼顯示訊息：

| update | report | 訊息 |
|---|---|---|
| 0 | 0 | 更新完成，報告已開啟。 |
| 2 | 0/2 | 更新完成但有部分項目需要注意；報告已開啟。 |
| 1 | 0/2 | 資料更新失敗，報告使用既有資料並已開啟。 |
| 3 | 0/2 | 另一個更新正在執行；報告使用既有資料並已開啟。 |
| 任何 | 1 | 報告產生失敗，請看上方訊息或 data\logs。 |

整體結束代碼取兩者中較嚴重的一個，順序為 1 > 3 > 2 > 0。

> 2026-10-22 稽核補記：已被 014、016 取代（[014 contracts/cli.md](../../014-publish-github/contracts/cli.md) §5、[014 data-model](../../014-publish-github/data-model.md)「結束代碼」、[016 contracts/migrate.md](../../016-rename-internal-ids/contracts/migrate.md)）。現在的 `更新資料.cmd`：
> - 先檢查 `uv`，找不到時印出安裝說明、以 1 結束（從 001 起就這樣，上面沒寫）。
> - 沒有 `sweetspot.toml` 時先執行 `uv run sweetspot setup`；代碼不是 0 就暫停並以那個代碼結束（014）。
> - update 為 4 時印「找到舊名稱的檔案，請先執行搬家：uv run sweetspot migrate」（016）；為 5 時印「還沒設定願望清單：請先執行 uv run sweetspot setup」（014）。
> - update 的代碼不在 0–5 時印「資料更新沒有正常結束（代碼 N）…」，整體代碼算 1（014 T069）；代碼照樣傳給 `report --update-exit`。
> - 整體代碼順序為 1 > 5 > 4 > 3 > 2 > 0。
