# Contract: CLI 的新增與改變（feature 008）

只列新增或改變的部分，其餘沿用 002–007 的 CLI 契約。每個回測指令在本 feature 的驗收中都明確加 `--cutoff 2026-09-25`。

## 模型版本

- `--model 名稱@版本`：`forecast`、`backtest`、`backtest-rule`、`grid`、`compare` 都接受。
  例如 `--model seasonal-record@1.0.0`。
  （2026-10-22 稽核補記）清單裡的 `compare` 不適用：`compare` 只讀兩份回測結果檔，沒有 `--model`（`cli.py`）。
- 沒有 `@版本` 時：和現行模型同名就取現行版本（換版前 `seasonal-record` 仍是 1.0.0，舊指令的意義不變），否則取最新版本（實作時的調整，T015）。
- 版本不存在時拒絕執行，列出可用的版本。

## `backtest`

- 結果新增 `finished_calibration`、`by_own_sales` 的 `3-5`／`6+`、`per_game` 的場數分組與 `release_facts`（data-model）。
- 摘要（`--json` 與文字）新增一行：只計已結束的 Brier，以及預測 ≥ 0.7 的「預測 − 實際」。

## `grid`

```text
steamsage grid --model seasonal-record@1.1.0 --split tuning --cutoff 2026-09-25 \
  --grid low_base=new,new-split --grid shrink=0,0.25,0.5,1
```

- 選參數規則加上 FR-004 的排除（research R6）。被排除的列寫出 `own-sales-worse:<組名>`。
  （2026-10-22 稽核補記）這個原因代碼只在記憶體的 `GridRow.excluded_reason`（`forecast/backtest/grid.py`）；`grid --json` 摘要的 `rows` 只有布林 `excluded`，
  比較文件寫的是中文句子（例如「0 場（低信心）顯著變差（FR-004），排除」）（`commands.py`、`grid.py` 的 `_status`）。
- 整個網格的分數寫進比較文件（沿用 004）。

## `compare`

```text
steamsage compare 現行.json 候選.json --attempt 1 --target-groups 0,1
```

- `--target-groups`：以逗號分隔的場數組名（`0`、`1`、`2`、`3-5`、`6+`）。
  - 除了 002 FR-029，還要求這些組的台灣區 Brier 點估計都比現行低，才判定「優於」。
  - 條件寫進比較紀錄的標題下方。
- 驗證組的比較次數依候選模型版本計算（1.1.0 最多 3 次），和其他比較分開（沿用 004 FR-013、spec FR-010）。

## `backtest-rule`、`compare-rule`

沒有新參數；用 `--model seasonal-record@1.1.0 --param ...` 指定候選（沿用 004）。

## 退出碼與錯誤

沿用既有規則。版本不存在、`--target-groups` 的組名不合法時，退出碼 1（`EXIT_FAILED`，和其他輸入錯誤相同），並說明原因。
