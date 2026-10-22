# Contract: CLI 新增指令（feature 002）

延伸 [feature 001 的 CLI 契約](../../001-price-data-foundation/contracts/cli.md)。共用規則不變：
- 進度寫到 stderr，摘要寫到 stdout，`--json` 改為輸出 JSON 摘要。
- 3 個新指令都**只讀取**：以唯讀方式開啟資料庫、不取寫入鎖，可以和 `update` 同時執行（FR-035）。

## Exit codes

| code | 意義 |
|---|---|
| 0 | 完成 |
| 2 | 完成，但有遊戲是 `model-error`，或（compare）判定為「未優於」 |
| 1 | 整批失敗：參數錯誤、資料庫無法開啟、比較時資料集不同 |

（2026-10-22 稽核補記：014 T069 起，argparse 判定的參數錯誤（不認得的旗標、選項不在可選的值裡、型別不對）也以 1 結束；以前是 argparse 預設的 2，和上表的 2 撞號。見 [001 contracts/cli.md](../../001-price-data-foundation/contracts/cli.md)。）

## `steamsage forecast [--as-of 日期] [--app APPID]… [--scope wishlist|all] [--model 名稱] [--param k=v]… [--out 檔案]`

- 預設：願望清單、分析時點為現在、使用 `CURRENT_MODEL`。`--scope all` 為資料庫中所有商品（沒有歷史的也列出，附狀態與原因）。
- `--as-of`：過去的日期（UTC 00:00）。用於驗證與除錯，會套用和回測相同的截斷規則。
- `--out`：把 `steamsage.forecast/1` JSON 寫到檔案（原子寫入）。沒有指定時：
  - 加上 `--json`：stdout 輸出完整預測。
  - 沒有 `--json`：stdout 輸出人看的摘要，每款一行：名稱、狀態、信心、下一場特賣 ≥ -50% 的機率。
- 摘要欄位：`games`、`ok`、`low_confidence`、各狀態數量、`model`、`as_of`、`seconds`。

## `steamsage backtest [--model 名稱] [--param k=v]… [--region TW|US|all] [--cutoff 日期] [--apps-limit N]`

- 預設：`CURRENT_MODEL`、兩區、資料截止時間為資料庫中最新的資料已知時間（取到當天 00:00 UTC）。
- 資料集識別碼逐區域計算，所以 `--region TW` 的結果仍可以和兩區結果的台灣區部分比較。
- `--apps-limit`：只取前 N 款（依 app_id 排序），用於快速試跑。資料集識別碼會因此不同，不能和完整回測比較。
- 進度：`回測 TW 分析時點 n/N（YYYY-MM-DD）`。
- 結果寫入 `data/backtests/`（contracts/backtest-result.md），摘要列出結果檔路徑，以及各區的遊戲數、分析時點數、Brier、參照分數、評分與截斷與未舉辦的數量，和總耗時（FR-034）。

## `steamsage compare <結果A> <結果B> [--record] [--record-to PATH]`

- A 是現行模型（或比較基準），B 是候選。
- 依 contracts/backtest-result.md 的「可以比較的條件」逐區域檢查，不符合時 exit 1，並說明第一個不同的地方。
- 輸出兩區的 Brier、差距、95% 區間與判定。
- `--record`：把比較紀錄附加到 `docs/model/comparisons.md`（contracts/backtest-result.md）。
- `--record-to PATH`：附加到指定檔案，隱含 `--record`；供測試與草稿使用。
- `compare` **不會**改變現行模型。改變 `CURRENT_MODEL` 是一次程式修改，需要附上判定為「優於」的紀錄；唯一例外是第一個現行模型的「建立下限」（FR-031、research R9）。

> 2026-10-22 稽核補記：上面三個指令的語法與摘要已被後來的 feature 擴充，現在的行為以這些契約為準：
> - `--model 名稱@版本`（`forecast`、`backtest`）：沒有 `@版本` 時，和現行模型同名就取現行版本，否則取最新版本；版本不存在時以 1 結束（[008 contracts/cli.md](../../008-new-game-forecast/contracts/cli.md)「模型版本」）。只給 `--param`、沒給 `--model` 時，參數疊在現行模型的參數上。
> - `backtest --split all|tuning|validation`（預設 `all`；[004 contracts/cli.md](../../004-deeper-discount-model/contracts/cli.md)）。摘要多了 `split`，以及 `finished`：每區只計已結束的 `units`、`brier`，和預測 ≥ 0.7 的「預測 − 實際」`high_excess_pp`（百分點；008 contracts/cli.md）。
> - `compare` 多了 `--attempt N`、`--change "說明"`（004 contracts/cli.md）與 `--target-groups`（008 contracts/cli.md）；摘要多了 `split` 與 `groups`。兩份結果的切分不同時拒絕比較、結束代碼 1（004 FR-010）。
> - `forecast` 的摘要另有 `data_cutoff`，有 `--out` 時還有 `out`（從 002 起就這樣，上面沒寫）。
